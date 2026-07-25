"""
Risk management & rekonsiliasi trade untuk DeFi91 Trading Bot.

Dua masalah besar yang diperbaiki modul ini:

1. Bot lama tidak punya SATU PUN pengaman di level akun. Tidak ada batas rugi
   harian, tidak ada batas drawdown, tidak ada jeda setelah loss beruntun.
   Bot hanya berhenti kalau saldo habis - itu terlalu terlambat.

2. `trades.json` tidak pernah di-update. Semua 525 entri berstatus "OPEN"
   dengan pnl 0, padahal posisinya sudah lama tertutup. Akibatnya dashboard
   salah, dan `optimize_params.py` selalu bilang "Not enough closed trades"
   karena memfilter status == "CLOSED" yang tidak pernah ada.

Modul ini menutup keduanya: `check_all()` sebagai gerbang sebelum entry,
dan `reconcile_trades()` untuk mencocokkan trades.json dengan fill asli
dari Hyperliquid.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import requests

import config

WIB = timezone(timedelta(hours=7))


def now_wib():
    return datetime.now(WIB)


# ============================================================
# STATE PERSISTEN
# ============================================================
def _default_state():
    return {
        "date": now_wib().strftime("%Y-%m-%d"),
        "daily_pnl": 0.0,
        "daily_trades": 0,
        "consecutive_losses": 0,
        "cooldown_until": None,
        "peak_equity": 0.0,
        "last_equity": 0.0,
        "halt_reason": None,
        "updated_at": None,
    }


def load_state(path=None):
    path = path or config.RISK_STATE_FILE
    state = _default_state()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                state.update(json.load(f))
        except (OSError, ValueError) as e:
            print(f"  [RISK] Gagal baca {path}: {e} - pakai state baru.")

    # Reset counter harian kalau sudah ganti hari (WIB).
    today = now_wib().strftime("%Y-%m-%d")
    if state.get("date") != today:
        state["date"] = today
        state["daily_pnl"] = 0.0
        state["daily_trades"] = 0
        # Penghentian karena batas rugi harian ikut lepas di hari baru.
        # Penghentian karena drawdown TIDAK - itu dihitung dari puncak ekuitas
        # sepanjang waktu, bukan per hari.
        halt = state.get("halt_reason") or ""
        if halt.startswith("DAILY_LOSS"):
            state["halt_reason"] = None
    return state


def save_state(state, path=None):
    path = path or config.RISK_STATE_FILE
    state["updated_at"] = now_wib().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print(f"  [RISK] Gagal simpan {path}: {e}")


# ============================================================
# PEMBARUAN STATE DARI FILL NYATA
# ============================================================
def fetch_fills(wallet=None, hours=48):
    """Ambil fill dari Hyperliquid untuk N jam terakhir."""
    wallet = wallet or config.MAIN_WALLET
    try:
        resp = requests.post(
            config.INFO_URL,
            json={"type": "userFills", "user": wallet},
            timeout=config.HTTP_TIMEOUT,
        )
        fills = resp.json()
        if not isinstance(fills, list):
            return []
    except (requests.RequestException, ValueError) as e:
        print(f"  [RISK] Gagal ambil fills: {e}")
        return []

    cutoff_ms = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000
    return [f for f in fills if float(f.get("time", 0)) >= cutoff_ms]


def refresh_from_fills(state, fills):
    """
    Hitung ulang PnL harian dan loss beruntun dari fill yang punya closedPnl.
    Fee ikut dikurangkan supaya angkanya sama dengan yang benar-benar masuk
    ke saldo - ini yang selama ini bikin laporan bot terlihat lebih bagus
    dari kenyataan.
    """
    start_of_day = now_wib().replace(hour=0, minute=0, second=0, microsecond=0)
    start_ms = start_of_day.timestamp() * 1000

    closing = sorted(
        (f for f in fills if float(f.get("closedPnl", 0) or 0) != 0),
        key=lambda f: float(f.get("time", 0)),
    )

    daily_pnl = 0.0
    daily_trades = 0
    for f in closing:
        if float(f.get("time", 0)) >= start_ms:
            net = float(f.get("closedPnl", 0) or 0) - float(f.get("fee", 0) or 0)
            daily_pnl += net
            daily_trades += 1

    streak = 0
    for f in reversed(closing):
        net = float(f.get("closedPnl", 0) or 0) - float(f.get("fee", 0) or 0)
        if net < 0:
            streak += 1
        else:
            break

    state["daily_pnl"] = round(daily_pnl, 6)
    state["daily_trades"] = daily_trades
    state["consecutive_losses"] = streak
    return state


def update_equity(state, equity):
    """Catat ekuitas dan puncaknya untuk perhitungan drawdown."""
    equity = float(equity)
    state["last_equity"] = round(equity, 6)
    if equity > float(state.get("peak_equity", 0) or 0):
        state["peak_equity"] = round(equity, 6)
    return state


def current_drawdown_percent(state):
    peak = float(state.get("peak_equity", 0) or 0)
    last = float(state.get("last_equity", 0) or 0)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - last) / peak * 100.0)


# ============================================================
# GERBANG SEBELUM ENTRY
# ============================================================
def check_all(state, balance):
    """
    Evaluasi semua pengaman. Return (boleh_entry: bool, alasan: str).

    Dipanggil SEBELUM bot mencari sinyal baru. Pengelolaan posisi yang sudah
    terbuka (trailing stop, smart exit) tetap jalan meski gerbang ini tutup -
    menutup posisi harus selalu diizinkan.
    """
    if not config.BOT_ENABLED:
        return False, "BOT_ENABLED=false (kill switch aktif)"

    if not config.WATCHLIST:
        return False, "WATCHLIST kosong"

    # 1. Cooldown setelah loss beruntun
    cooldown_until = state.get("cooldown_until")
    if cooldown_until:
        try:
            until = datetime.fromisoformat(cooldown_until)
            if until.tzinfo is None:
                until = until.replace(tzinfo=WIB)
            if now_wib() < until:
                sisa = (until - now_wib()).total_seconds() / 3600
                return False, f"COOLDOWN aktif {sisa:.1f} jam lagi (loss beruntun)"
            state["cooldown_until"] = None
        except ValueError:
            state["cooldown_until"] = None

    # 2. Saldo minimum
    if balance < config.MIN_ACCOUNT_BALANCE:
        return False, (
            f"SALDO_MINIMUM: ${balance:.2f} < ${config.MIN_ACCOUNT_BALANCE:.2f}"
        )

    # 3. Batas rugi harian
    daily_pnl = float(state.get("daily_pnl", 0) or 0)
    if daily_pnl <= -abs(config.DAILY_LOSS_LIMIT):
        return False, (
            f"DAILY_LOSS_LIMIT: rugi hari ini ${daily_pnl:.2f} "
            f"melewati batas ${config.DAILY_LOSS_LIMIT:.2f}"
        )

    # 4. Maksimum drawdown dari puncak ekuitas
    dd = current_drawdown_percent(state)
    if dd >= config.MAX_DRAWDOWN_PERCENT:
        return False, (
            f"MAX_DRAWDOWN: {dd:.1f}% >= {config.MAX_DRAWDOWN_PERCENT:.1f}% dari puncak"
        )

    # 5. Loss beruntun -> pasang cooldown
    streak = int(state.get("consecutive_losses", 0) or 0)
    if streak >= config.MAX_CONSECUTIVE_LOSSES:
        until = now_wib() + timedelta(hours=config.COOLDOWN_HOURS)
        state["cooldown_until"] = until.isoformat()
        return False, (
            f"LOSS_BERUNTUN: {streak}x berturut-turut, jeda "
            f"{config.COOLDOWN_HOURS:.0f} jam sampai {until.strftime('%H:%M')} WIB"
        )

    return True, "OK"


def validate_order(coin, size, price, leverage):
    """
    Validasi order sebelum dikirim ke exchange.

    Hyperliquid menolak order dengan nilai notional di bawah $10. Bot lama
    tidak pernah memeriksa ini, jadi koin ber-leverage rendah (contoh VVV
    maks 3x -> $3 x 3 = $9 notional) selalu ditolak dan run terbuang percuma.
    """
    if size <= 0:
        return False, f"{coin}: ukuran order 0 setelah pembulatan desimal"

    notional = size * price
    if notional < config.MIN_ORDER_VALUE_USD:
        return False, (
            f"{coin}: notional ${notional:.2f} < minimum "
            f"${config.MIN_ORDER_VALUE_USD:.2f} (naikkan margin atau leverage)"
        )

    # Cek apakah TP masih menutupi biaya fee round-trip.
    gross_tp = config.TP_PERCENT * leverage
    fee = 2 * config.TAKER_FEE * leverage
    if gross_tp <= fee * 2:
        return False, (
            f"{coin}: TP {config.TP_PERCENT*100:.2f}% terlalu kecil dibanding "
            f"fee round-trip - edge tidak cukup"
        )

    return True, "OK"


# ============================================================
# REKONSILIASI trades.json
# ============================================================
def reconcile_trades(trades_path=None, wallet=None, hours=72):
    """
    Cocokkan entri "OPEN" di trades.json dengan posisi & fill sebenarnya.

    - Coin yang sudah tidak punya posisi terbuka -> tandai CLOSED
    - Isi realized PnL (sudah dikurangi fee) dari fill terdekat
    - Entri lama yang tidak ketemu fill-nya tetap ditandai CLOSED dengan
      pnl None supaya tidak selamanya nyangkut sebagai "OPEN"

    Return dict ringkasan.
    """
    trades_path = trades_path or config.TRADES_FILE
    wallet = wallet or config.MAIN_WALLET

    try:
        with open(trades_path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"  [RECONCILE] Tidak bisa baca {trades_path}: {e}")
        return {"updated": 0, "still_open": 0}

    trades = data.get("trades", [])
    open_entries = [t for t in trades if t.get("status") == "OPEN"]
    if not open_entries:
        return {"updated": 0, "still_open": 0}

    # Posisi yang benar-benar masih terbuka di exchange.
    try:
        resp = requests.post(
            config.INFO_URL,
            json={"type": "clearinghouseState", "user": wallet},
            timeout=config.HTTP_TIMEOUT,
        )
        state_data = resp.json()
        live_coins = {
            p.get("position", {}).get("coin")
            for p in state_data.get("assetPositions", [])
            if float(p.get("position", {}).get("szi", 0) or 0) != 0
        }
    except (requests.RequestException, ValueError) as e:
        print(f"  [RECONCILE] Gagal ambil posisi: {e}")
        return {"updated": 0, "still_open": len(open_entries)}

    fills = fetch_fills(wallet, hours=hours)
    # Kelompokkan fill penutup per coin, urut waktu.
    closes_by_coin = {}
    for f in fills:
        if float(f.get("closedPnl", 0) or 0) == 0:
            continue
        closes_by_coin.setdefault(f.get("coin"), []).append(f)
    for coin in closes_by_coin:
        closes_by_coin[coin].sort(key=lambda f: float(f.get("time", 0)))

    used = set()
    updated = 0
    still_open = 0

    for entry in open_entries:
        coin = entry.get("coin")
        if coin in live_coins:
            still_open += 1
            continue

        # Cari fill penutup pertama setelah waktu entry yang belum terpakai.
        matched = None
        entry_ms = _parse_entry_time_ms(entry.get("time"))
        for f in closes_by_coin.get(coin, []):
            fid = f.get("tid") or f.get("oid") or f.get("time")
            if fid in used:
                continue
            if entry_ms is not None and float(f.get("time", 0)) < entry_ms:
                continue
            matched = f
            used.add(fid)
            break

        entry["status"] = "CLOSED"
        if matched:
            net = float(matched.get("closedPnl", 0) or 0) - float(matched.get("fee", 0) or 0)
            entry["pnl"] = round(net, 6)
            entry["exit"] = float(matched.get("px", 0) or 0)
            entry["closed_at"] = datetime.fromtimestamp(
                float(matched.get("time", 0)) / 1000, tz=WIB
            ).strftime("%Y-%m-%d %H:%M:%S")
            entry["close_reason"] = "RECONCILED_FILL"
        else:
            entry["pnl"] = None
            entry["close_reason"] = "RECONCILED_NO_FILL"
        updated += 1

    data["trades"] = trades
    data["last_reconcile"] = now_wib().strftime("%Y-%m-%d %H:%M:%S")
    data["summary"] = _summarize(trades)

    try:
        with open(trades_path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"  [RECONCILE] Gagal simpan {trades_path}: {e}")

    print(f"  [RECONCILE] {updated} trade ditandai CLOSED, {still_open} masih OPEN")
    return {"updated": updated, "still_open": still_open}


def _parse_entry_time_ms(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=WIB)
            return dt.timestamp() * 1000
        except ValueError:
            continue
    return None


def _summarize(trades):
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]
    wins = [t for t in closed if float(t["pnl"]) > 0]
    losses = [t for t in closed if float(t["pnl"]) < 0]
    total = sum(float(t["pnl"]) for t in closed)
    return {
        "total_logged": len(trades),
        "closed_with_pnl": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "net_pnl": round(total, 4),
        "avg_win": round(sum(float(t["pnl"]) for t in wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(float(t["pnl"]) for t in losses) / len(losses), 4) if losses else 0.0,
    }


if __name__ == "__main__":
    print("=== REKONSILIASI trades.json ===")
    print(reconcile_trades())
