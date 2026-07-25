"""
DeFi91 Trading Bot - Scalping Bot (v3)
Strategi: Almarhum Doddy Ali Wijaya (CVD/Order Flow) + KJo Academy (RSI/MACD)
Exchange: Hyperliquid Perpetual Futures

Bot ini dijalankan oleh GitHub Actions (lihat .github/workflows/trading_workflow_v2.yml).

Perubahan penting dari v2:
  - Konfigurasi pindah ke config.py (semua lewat environment variable)
  - Indikator memakai indicators.py (MACD/RSI/ADX rumusnya sudah benar)
  - Ada risk_manager.py: batas rugi harian, drawdown, cooldown loss beruntun
  - Skor teknikal menyesuaikan regime pasar, tidak lagi saling meniadakan
  - Entry butuh konfirmasi dua sisi (order flow DAN teknikal searah)
  - Metadata coin (szDecimals, max leverage) diambil dari API, tidak hardcode
  - Data pasar di-cache per run supaya tidak memanggil API berulang kali
"""

import json
import time

import requests
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

import config
import risk_manager
from indicators import (
    calculate_adx,
    calculate_macd,
    calculate_rsi,
    swing_levels,
)
from market_regime_filter import detect_market_regime_global
from telegram_signals import send_close_signal, send_trade_signal

# ============================================================
# CACHE DATA PASAR (per run)
# ============================================================
# Bot lama memanggil endpoint yang sama berkali-kali: sekali saat mengelola
# posisi terbuka, sekali lagi saat mencari entry. Untuk 6 koin itu ~36 request
# per run dan gampang kena rate limit. Cache ini memangkasnya jadi setengah.
_CACHE = {}


def _cache_get(key, loader):
    if key not in _CACHE:
        _CACHE[key] = loader()
    return _CACHE[key]


def clear_cache():
    _CACHE.clear()


# ============================================================
# HELPER
# ============================================================
def get_wib_time():
    """Waktu sekarang dalam WIB (UTC+7)."""
    return risk_manager.now_wib()


def _post_info(payload):
    """POST ke endpoint info Hyperliquid. Melempar exception kalau gagal."""
    resp = requests.post(config.INFO_URL, json=payload, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_meta_map():
    """
    Ambil szDecimals dan maxLeverage per coin langsung dari exchange.

    Versi lama menyimpannya sebagai dict hardcode. Begitu Hyperliquid mengubah
    batas leverage sebuah coin, bot akan mengirim order dengan leverage yang
    ditolak - dan errornya cuma muncul di log.
    """
    def _load():
        try:
            universe = _post_info({"type": "meta"}).get("universe", [])
            return {
                m["name"]: {
                    "szDecimals": int(m.get("szDecimals", 4)),
                    "maxLeverage": int(m.get("maxLeverage", 10)),
                }
                for m in universe
                if m.get("name")
            }
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  [META] Gagal ambil metadata: {e}")
            return {}

    return _cache_get("meta", _load)


def round_size(coin, size):
    """Bulatkan ukuran order sesuai szDecimals coin."""
    decimals = get_meta_map().get(coin, {}).get("szDecimals", 4)
    return round(size, decimals)


def max_leverage_for(coin):
    return get_meta_map().get(coin, {}).get("maxLeverage", 10)


def format_price(price):
    """
    Format harga ke maksimal 5 angka penting (syarat Hyperliquid).
    """
    price = float(price)
    if price >= 10000:
        return round(price, 0)
    if price >= 1000:
        return round(price, 1)
    if price >= 100:
        return round(price, 1)
    if price >= 10:
        return round(price, 2)
    if price >= 1:
        return round(price, 3)
    if price >= 0.1:
        return round(price, 4)
    return round(price, 5)


def get_candles(coin, interval="15m", lookback=100):
    """
    Ambil candle dari Hyperliquid.

    Return (closes, highs, lows, volumes). List kosong kalau gagal - pemanggil
    WAJIB memeriksa ini dan melewati coin tersebut, bukan menganggapnya netral.
    """
    def _load():
        interval_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}
        ms = interval_ms.get(interval, 900000)
        end_time = int(time.time() * 1000)
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": end_time - (lookback * ms),
                "endTime": end_time,
            },
        }
        try:
            data = _post_info(payload)
            if not isinstance(data, list) or not data:
                return [], [], [], []
            return (
                [float(c["c"]) for c in data],
                [float(c["h"]) for c in data],
                [float(c["l"]) for c in data],
                [float(c["v"]) for c in data],
            )
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  [DATA] Candle {coin} gagal: {e}")
            return [], [], [], []

    return _cache_get(f"candles:{coin}:{interval}:{lookback}", _load)


def get_recent_trades(coin, limit=200):
    """Ambil trade terakhir untuk perhitungan CVD."""
    def _load():
        try:
            trades = _post_info({"type": "recentTrades", "coin": coin})
            if not isinstance(trades, list):
                return []
            return trades[-limit:]
        except (requests.RequestException, ValueError) as e:
            print(f"  [DATA] recentTrades {coin} gagal: {e}")
            return []

    return _cache_get(f"trades:{coin}", _load)


def calculate_cvd(trades):
    """
    CVD - Cumulative Volume Delta (indikator utama strategi almarhum).

    Return (cvd, buy_ratio). buy_ratio None kalau tidak ada data, supaya
    pemanggil bisa membedakan "seimbang" dari "tidak tahu".
    """
    if not trades:
        return 0.0, None

    buy_volume = 0.0
    sell_volume = 0.0
    for trade in trades:
        try:
            size = float(trade.get("sz", 0))
        except (TypeError, ValueError):
            continue
        if trade.get("side") == "B":
            buy_volume += size
        else:
            sell_volume += size

    total = buy_volume + sell_volume
    if total == 0:
        return 0.0, None
    return buy_volume - sell_volume, buy_volume / total


def get_orderbook_ratio(coin):
    """
    Rasio volume bid vs ask di 10 level teratas.

    Return None kalau gagal, bukan 1.0. Bot lama mengembalikan 1.0 (netral)
    saat error, jadi kegagalan jaringan diam-diam berubah jadi "sinyal netral".
    """
    def _load():
        try:
            data = _post_info({"type": "l2Book", "coin": coin})
            levels = data.get("levels", [[], []])
            bid_volume = sum(float(b.get("sz", 0)) for b in levels[0][:10])
            ask_volume = sum(float(a.get("sz", 0)) for a in levels[1][:10])
            if bid_volume <= 0 or ask_volume <= 0:
                return None
            return bid_volume / ask_volume
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            print(f"  [DATA] Orderbook {coin} gagal: {e}")
            return None

    return _cache_get(f"ob:{coin}", _load)


def get_funding_rate(coin):
    """Funding rate saat ini. None kalau gagal."""
    def _load_all():
        try:
            data = _post_info({"type": "metaAndAssetCtxs"})
            assets = data[0].get("universe", [])
            ctxs = data[1]
            return {
                asset.get("name"): float(ctxs[i].get("funding", 0))
                for i, asset in enumerate(assets)
                if i < len(ctxs)
            }
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            print(f"  [DATA] Funding gagal: {e}")
            return {}

    return _cache_get("funding", _load_all).get(coin)


# ============================================================
# ANALISA ORDER FLOW (STRATEGI ALMARHUM)
# ============================================================
def analyze_onchain(coin):
    """
    Analisa order flow ala almarhum Doddy Ali Wijaya:
      1. CVD (Cumulative Volume Delta) - bobot terbesar
      2. Order Book Ratio (bid vs ask)
      3. Funding Rate (kontrarian)

    Return: (score -7..+7, details dict).
    `details["data_ok"]` False berarti data tidak lengkap -> jangan entry.
    """
    score = 0
    details = {"data_ok": True}

    # 1. CVD (bobot ±3)
    _, buy_ratio = calculate_cvd(get_recent_trades(coin))
    if buy_ratio is None:
        details["data_ok"] = False
        details["cvd_signal"] = "NO DATA"
        details["cvd_buy_ratio"] = "N/A"
    else:
        details["cvd_buy_ratio"] = f"{buy_ratio*100:.0f}%"
        if buy_ratio > 0.65:
            score += 3
            details["cvd_signal"] = "STRONG BUY"
        elif buy_ratio > 0.55:
            score += 2
            details["cvd_signal"] = "BUY"
        elif buy_ratio < 0.35:
            score -= 3
            details["cvd_signal"] = "STRONG SELL"
        elif buy_ratio < 0.45:
            score -= 2
            details["cvd_signal"] = "SELL"
        else:
            details["cvd_signal"] = "NEUTRAL"

    # 2. Order book (bobot ±2)
    ob_ratio = get_orderbook_ratio(coin)
    if ob_ratio is None:
        details["ob_signal"] = "NO DATA"
        details["orderbook_ratio"] = "N/A"
    else:
        details["orderbook_ratio"] = f"{ob_ratio:.2f}"
        if ob_ratio > 2.0:
            score += 2
            details["ob_signal"] = "BID HEAVY (Bullish)"
        elif ob_ratio > 1.3:
            score += 1
            details["ob_signal"] = "BID LEAN"
        elif ob_ratio < 0.5:
            score -= 2
            details["ob_signal"] = "ASK HEAVY (Bearish)"
        elif ob_ratio < 0.77:
            score -= 1
            details["ob_signal"] = "ASK LEAN"
        else:
            details["ob_signal"] = "BALANCED"

    # 3. Funding rate - kontrarian (bobot ±2)
    funding = get_funding_rate(coin)
    if funding is None:
        details["funding_signal"] = "NO DATA"
        details["funding_rate"] = "N/A"
    else:
        details["funding_rate"] = f"{funding*100:.4f}%"
        if funding > 0.01:
            score -= 2  # terlalu ramai long -> kontrarian short
            details["funding_signal"] = "HIGH LONG (Contrarian SHORT)"
        elif funding > 0.005:
            score -= 1
            details["funding_signal"] = "MODERATE LONG"
        elif funding < -0.01:
            score += 2
            details["funding_signal"] = "HIGH SHORT (Contrarian LONG)"
        elif funding < -0.005:
            score += 1
            details["funding_signal"] = "MODERATE SHORT"
        else:
            details["funding_signal"] = "NEUTRAL"

    details["onchain_score"] = score
    return score, details


# ============================================================
# ANALISA TEKNIKAL (KJO ACADEMY) - SADAR REGIME
# ============================================================
def analyze_technical(coin, regime="NEUTRAL"):
    """
    Analisa teknikal yang menyesuaikan kondisi pasar.

    Masalah di versi lama: RSI dipakai secara mean-reversion (oversold = beli)
    sementara MACD dipakai secara trend-following (bullish = beli). Di pasar
    yang sedang tren naik kuat, RSI tinggi memberi -2 sedangkan MACD memberi
    +2 - keduanya saling meniadakan, skor total mengambang di sekitar nol,
    dan bot justru paling sering entry saat sinyalnya paling lemah.

    Sekarang mode-nya dipilih berdasarkan regime:
      - TRENDING  -> ikut tren (MACD & posisi harga di range jadi konfirmasi)
      - selain itu -> mean reversion (RSI ekstrem & dekat support/resistance)

    Return: (score -5..+5, details dict).
    """
    score = 0
    details = {"data_ok": True, "mode": "TREND" if regime == "TRENDING" else "REVERSION"}

    closes, highs, lows, _ = get_candles(coin, "15m", 100)
    if len(closes) < 35:
        details["data_ok"] = False
        details["technical_error"] = "Data candle tidak cukup"
        return 0, details

    rsi = calculate_rsi(closes, 14)
    macd_line, signal_line, hist = calculate_macd(closes)
    adx, di_plus, di_minus = calculate_adx(highs, lows, closes, 14)
    resistance, support = swing_levels(highs, lows, 20)

    price = closes[-1]
    rng = resistance - support
    pos_in_range = (price - support) / rng if rng > 0 else 0.5

    details["rsi"] = f"{rsi:.1f}"
    details["macd"] = f"{macd_line:.4f}"
    details["macd_hist"] = f"{hist:.4f}"
    details["adx"] = f"{adx:.1f}"
    details["price_position"] = f"{pos_in_range*100:.0f}%"
    details["support"] = support
    details["resistance"] = resistance

    if details["mode"] == "TREND":
        # --- Mode ikut tren ---
        # MACD (±2): histogram positif dan MACD di atas signal = momentum naik
        if macd_line > signal_line and hist > 0:
            score += 2
            details["macd_signal"] = "BULLISH CROSS"
        elif macd_line > signal_line:
            score += 1
            details["macd_signal"] = "BULLISH"
        elif macd_line < signal_line and hist < 0:
            score -= 2
            details["macd_signal"] = "BEARISH CROSS"
        else:
            score -= 1
            details["macd_signal"] = "BEARISH"

        # Arah tren dari DI (±2)
        if adx > 25 and di_plus > di_minus:
            score += 2
            details["trend_signal"] = f"UPTREND KUAT (ADX {adx:.0f})"
        elif adx > 25 and di_minus > di_plus:
            score -= 2
            details["trend_signal"] = f"DOWNTREND KUAT (ADX {adx:.0f})"
        else:
            details["trend_signal"] = f"TREN LEMAH (ADX {adx:.0f})"

        # Momentum RSI (±1) - di mode tren, RSI kuat justru konfirmasi
        if rsi > 55:
            score += 1
            details["rsi_signal"] = "MOMENTUM NAIK"
        elif rsi < 45:
            score -= 1
            details["rsi_signal"] = "MOMENTUM TURUN"
        else:
            details["rsi_signal"] = "NETRAL"
    else:
        # --- Mode mean reversion ---
        # RSI ekstrem (±2)
        if rsi < 30:
            score += 2
            details["rsi_signal"] = "OVERSOLD (Buy)"
        elif rsi < 40:
            score += 1
            details["rsi_signal"] = "LOW (Lean Buy)"
        elif rsi > 70:
            score -= 2
            details["rsi_signal"] = "OVERBOUGHT (Sell)"
        elif rsi > 60:
            score -= 1
            details["rsi_signal"] = "HIGH (Lean Sell)"
        else:
            details["rsi_signal"] = "NEUTRAL"

        # Posisi terhadap support/resistance (±2)
        if pos_in_range < 0.15:
            score += 2
            details["sr_signal"] = "DI SUPPORT (Buy)"
        elif pos_in_range < 0.30:
            score += 1
            details["sr_signal"] = "DEKAT SUPPORT"
        elif pos_in_range > 0.85:
            score -= 2
            details["sr_signal"] = "DI RESISTANCE (Sell)"
        elif pos_in_range > 0.70:
            score -= 1
            details["sr_signal"] = "DEKAT RESISTANCE"
        else:
            details["sr_signal"] = "MID RANGE"

        # Histogram MACD sebagai konfirmasi pembalikan (±1)
        if hist > 0:
            score += 1
            details["macd_signal"] = "HIST POSITIF"
        elif hist < 0:
            score -= 1
            details["macd_signal"] = "HIST NEGATIF"
        else:
            details["macd_signal"] = "FLAT"

    details["technical_score"] = score
    return score, details


def decide_direction(onchain_score, tech_score):
    """
    Tentukan arah trade dengan syarat konfluensi.

    Bot lama hanya menjumlahkan skor, sehingga order flow +7 dengan teknikal -3
    tetap menghasilkan LONG (total +4) walau kedua sisi saling bertentangan.
    Sekarang kedua sisi harus searah, dan tidak boleh ada yang melawan.

    Return: ("LONG" | "SHORT" | None, total_score, alasan)
    """
    total = onchain_score + tech_score

    if total >= config.ENTRY_THRESHOLD:
        if onchain_score > 0 and tech_score >= 0:
            return "LONG", total, ""
        return None, total, (
            f"skor total {total} lolos tapi tidak konfluen "
            f"(order flow {onchain_score:+d}, teknikal {tech_score:+d})"
        )

    if total <= -config.ENTRY_THRESHOLD:
        if onchain_score < 0 and tech_score <= 0:
            return "SHORT", total, ""
        return None, total, (
            f"skor total {total} lolos tapi tidak konfluen "
            f"(order flow {onchain_score:+d}, teknikal {tech_score:+d})"
        )

    return None, total, f"WNS - skor {total} di antara ±{config.ENTRY_THRESHOLD}"


# ============================================================
# EKSEKUSI ORDER
# ============================================================
def execute_trade(exchange, coin, direction, current_price):
    """
    Kirim market order (IOC) beserta TP dan SL sebagai satu grup order.
    """
    is_buy = direction == "LONG"
    actual_leverage = min(config.TARGET_LEVERAGE, max_leverage_for(coin))

    position_value = config.MARGIN_PER_TRADE * actual_leverage
    size = round_size(coin, position_value / current_price)

    ok, reason = risk_manager.validate_order(coin, size, current_price, actual_leverage)
    if not ok:
        print(f"  [TOLAK] {reason}")
        return {"success": False, "error": reason}

    if is_buy:
        tp_price = format_price(current_price * (1 + config.TP_PERCENT))
        sl_price = format_price(current_price * (1 - config.SL_PERCENT))
        limit_px = format_price(current_price * (1 + config.ENTRY_SLIPPAGE))
    else:
        tp_price = format_price(current_price * (1 - config.TP_PERCENT))
        sl_price = format_price(current_price * (1 + config.SL_PERCENT))
        limit_px = format_price(current_price * (1 - config.ENTRY_SLIPPAGE))

    print(f"\n  EKSEKUSI {direction} {coin}")
    print(f"  Size: {size} | Notional: ${size*current_price:.2f} | "
          f"Margin: ${config.MARGIN_PER_TRADE} | Leverage: {actual_leverage}x")
    print(f"  Entry ~${current_price} | TP: ${tp_price} | SL: ${sl_price}")

    if config.DRY_RUN:
        print("  [DRY_RUN] Order tidak dikirim ke exchange.")
        return {
            "success": False, "dry_run": True, "coin": coin, "direction": direction,
            "entry_price": current_price, "tp_price": tp_price, "sl_price": sl_price,
            "size": size, "leverage": actual_leverage,
        }

    try:
        exchange.update_leverage(actual_leverage, coin, is_cross=True)
        print(f"  Leverage di-set {actual_leverage}x untuk {coin}")
    except Exception as e:
        print(f"  Peringatan: gagal set leverage: {e}")

    orders = [
        {
            "coin": coin, "is_buy": is_buy, "sz": size, "limit_px": limit_px,
            "order_type": {"limit": {"tif": "Ioc"}}, "reduce_only": False,
        },
        {
            "coin": coin, "is_buy": not is_buy, "sz": size, "limit_px": tp_price,
            "order_type": {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}},
            "reduce_only": True,
        },
        {
            "coin": coin, "is_buy": not is_buy, "sz": size, "limit_px": sl_price,
            "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
            "reduce_only": True,
        },
    ]

    try:
        result = exchange.bulk_orders(orders, grouping="normalTpsl")
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])

        order_filled = False
        tp_set = sl_set = False
        entry_price = current_price

        for i, status in enumerate(statuses):
            if "filled" in status:
                order_filled = True
                entry_price = float(status["filled"]["avgPx"])
                print(f"  ORDER FILLED @ ${entry_price}")
            elif "resting" in status:
                if i == 1:
                    tp_set = True
                    print(f"  TP terpasang (OID {status['resting']['oid']})")
                elif i == 2:
                    sl_set = True
                    print(f"  SL terpasang (OID {status['resting']['oid']})")
            elif "error" in status:
                print(f"  Error order: {status['error']}")

        # Kalau entry tidak terisi, TP/SL yang tersisa harus dibatalkan supaya
        # tidak jadi order nyangkut yang menghalangi entry berikutnya.
        if not order_filled and (tp_set or sl_set):
            print("  Entry tidak terisi - membatalkan TP/SL sisa.")
            _cancel_orders_for_coin(exchange, coin)

        # Verifikasi bahwa SL benar-benar ada di exchange.
        # Riwayat trades.json menunjukkan 514 trade berturut-turut dengan
        # sl_set=False - artinya bot tidak pernah tahu apakah stop loss-nya
        # terpasang, dan tetap lanjut seolah-olah aman. Posisi tanpa SL di
        # leverage tinggi adalah cara tercepat kehilangan seluruh akun.
        if order_filled:
            sl_set = _ensure_stop_loss(
                exchange, coin, size, is_buy, sl_price, entry_price
            )

        return {
            "success": order_filled, "entry_price": entry_price,
            "tp_set": tp_set, "sl_set": sl_set,
            "tp_price": tp_price, "sl_price": sl_price,
            "size": size, "direction": direction, "coin": coin,
            "leverage": actual_leverage,
        }
    except Exception as e:
        print(f"  Gagal eksekusi: {e}")
        return {"success": False, "error": str(e)}


def _ensure_stop_loss(exchange, coin, size, entry_is_buy, sl_price, entry_price):
    """
    Pastikan stop loss benar-benar terpasang setelah entry terisi.

    Tiga tingkat pertahanan:
      1. Cek ke exchange apakah ada trigger order stop untuk coin ini
      2. Kalau tidak ada, pasang SL susulan
      3. Kalau pemasangan susulan pun gagal, TUTUP POSISI SEKARANG JUGA

    Tingkat ketiga terdengar ekstrem, tapi memegang posisi leverage tinggi
    tanpa stop loss jauh lebih berbahaya daripada keluar rugi tipis.
    """
    time.sleep(1.0)  # beri waktu exchange mendaftarkan trigger order

    try:
        fe_orders = _post_info({"type": "frontendOpenOrders", "user": config.MAIN_WALLET})
        for order in fe_orders:
            if (order.get("coin") == coin
                    and order.get("orderType") == "Stop Market"
                    and order.get("reduceOnly", False)):
                print(f"  SL terverifikasi di exchange @ ${order.get('triggerPx')}")
                return True
    except (requests.RequestException, ValueError) as e:
        print(f"  Tidak bisa memverifikasi SL: {e}")

    print(f"  PERINGATAN: SL tidak ditemukan di exchange - memasang susulan...")
    try:
        result = exchange.order(
            coin, not entry_is_buy, size, sl_price,
            {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
            reduce_only=True,
        )
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        if statuses and "resting" in statuses[0]:
            print(f"  SL susulan terpasang @ ${sl_price}")
            return True
        print(f"  SL susulan ditolak: {statuses}")
    except Exception as e:
        print(f"  SL susulan gagal: {e}")

    # Pertahanan terakhir - keluar dari posisi yang tidak terlindungi.
    print(f"  DARURAT: {coin} terbuka tanpa SL. Menutup posisi sekarang.")
    try:
        close_px = format_price(
            entry_price * (1 - config.EXIT_SLIPPAGE) if entry_is_buy
            else entry_price * (1 + config.EXIT_SLIPPAGE)
        )
        exchange.bulk_orders([{
            "coin": coin, "is_buy": not entry_is_buy, "sz": size,
            "limit_px": close_px, "order_type": {"limit": {"tif": "Ioc"}},
            "reduce_only": True,
        }])
        _cancel_orders_for_coin(exchange, coin)
        print(f"  Posisi {coin} ditutup darurat.")
    except Exception as e:
        print(f"  KRITIS: gagal menutup {coin} yang tanpa SL: {e}")
        print(f"  >>> PERIKSA MANUAL DI HYPERLIQUID SEKARANG <<<")

    return False


def _cancel_orders_for_coin(exchange, coin):
    """Batalkan semua open order (termasuk trigger) untuk sebuah coin."""
    try:
        fe_orders = _post_info({"type": "frontendOpenOrders", "user": config.MAIN_WALLET})
        for order in fe_orders:
            if order.get("coin") == coin:
                try:
                    exchange.cancel(coin, order["oid"])
                except Exception as e:
                    print(f"    Gagal cancel OID {order.get('oid')}: {e}")
    except (requests.RequestException, ValueError) as e:
        print(f"    Gagal ambil open orders: {e}")


# ============================================================
# SMART EXIT + TRAILING STOP
# ============================================================
def manage_open_positions(exchange, info, all_mids):
    """
    Untuk setiap posisi terbuka:
      1. Analisa ulang; kalau sinyal berbalik sangat kuat -> tutup lebih awal
      2. Kalau profit >= ambang -> geser SL ke breakeven, lalu kunci profit

    Fungsi ini SELALU dijalankan, bahkan saat gerbang risiko menutup entry
    baru - menutup posisi tidak boleh ikut terblokir.
    """
    print(f"\n{'='*60}\nPENGELOLAAN POSISI TERBUKA\n{'='*60}")

    user_state = info.user_state(config.MAIN_WALLET)
    positions = user_state.get("assetPositions", [])
    actions_taken = []

    for pos in positions:
        p = pos.get("position", {})
        coin = p.get("coin")
        szi = float(p.get("szi", 0) or 0)
        entry_px = float(p.get("entryPx", 0) or 0)

        if szi == 0 or entry_px == 0:
            continue

        is_long = szi > 0
        direction = "LONG" if is_long else "SHORT"
        current_price = float(all_mids.get(coin, 0) or 0)
        if current_price == 0:
            continue

        pnl_percent = (
            (current_price - entry_px) / entry_px if is_long
            else (entry_px - current_price) / entry_px
        )

        print(f"\n  [{coin}] {direction} | Entry ${entry_px:.4f} | "
              f"Now ${current_price:.4f} | PnL {pnl_percent*100:.2f}%")

        # --- STEP 1: SMART EXIT ---
        regime = _CACHE.get("regime_by_coin", {}).get(coin, "NEUTRAL")
        onchain_score, _ = analyze_onchain(coin)
        tech_score, _ = analyze_technical(coin, regime)
        total_score = onchain_score + tech_score
        print(f"    Skor analisa ulang: {total_score:+d}/12")

        should_close = False
        close_reason = ""
        if is_long and total_score <= -config.SMART_EXIT_THRESHOLD:
            should_close = True
            close_reason = f"Sinyal berbalik STRONG SHORT (skor {total_score})"
        elif not is_long and total_score >= config.SMART_EXIT_THRESHOLD:
            should_close = True
            close_reason = f"Sinyal berbalik STRONG LONG (skor {total_score})"

        if should_close:
            if config.DRY_RUN:
                print(f"    [DRY_RUN] Akan smart exit: {close_reason}")
                continue
            action = _smart_exit(exchange, coin, szi, is_long, direction,
                                 entry_px, current_price, close_reason)
            if action:
                actions_taken.append(action)
            continue

        # --- STEP 2: TRAILING STOP ---
        if pnl_percent < config.TRAILING_BREAKEVEN:
            print(f"    Hold (PnL {pnl_percent*100:.2f}% < "
                  f"{config.TRAILING_BREAKEVEN*100:.2f}% ambang trailing)")
            continue

        if pnl_percent >= config.TRAILING_LOCK:
            factor = 1 + config.TRAILING_LOCK_PROFIT if is_long else 1 - config.TRAILING_LOCK_PROFIT
            new_sl = format_price(entry_px * factor)
            trail_type = f"LOCK +{config.TRAILING_LOCK_PROFIT*100:.1f}%"
        else:
            new_sl = format_price(entry_px)
            trail_type = "BREAKEVEN"

        if config.DRY_RUN:
            print(f"    [DRY_RUN] Akan geser SL ke ${new_sl} ({trail_type})")
            continue

        action = _trail_stop(exchange, coin, szi, is_long, new_sl, trail_type, pnl_percent)
        if action:
            actions_taken.append(action)

    if actions_taken:
        print(f"\n  {len(actions_taken)} aksi dilakukan:")
        for a in actions_taken:
            print(f"    - {a['coin']}: {a['action']} ({a['reason']})")
    else:
        print("\n  Tidak ada penyesuaian posisi.")

    return actions_taken


def _smart_exit(exchange, coin, szi, is_long, direction, entry_px, current_price, reason):
    """Tutup posisi dengan IOC order, lalu bersihkan TP/SL sisa."""
    print(f"    SMART EXIT: {reason}")
    close_is_buy = not is_long
    close_px = format_price(
        current_price * (1 + config.EXIT_SLIPPAGE) if close_is_buy
        else current_price * (1 - config.EXIT_SLIPPAGE)
    )

    try:
        result = exchange.bulk_orders([{
            "coin": coin, "is_buy": close_is_buy, "sz": abs(szi),
            "limit_px": close_px, "order_type": {"limit": {"tif": "Ioc"}},
            "reduce_only": True,
        }])
    except Exception as e:
        print(f"    Gagal smart exit: {e}")
        return None

    exit_price = current_price
    closed = False
    if isinstance(result, dict) and result.get("status") == "ok":
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        if statuses and "filled" in statuses[0]:
            exit_price = float(statuses[0]["filled"]["avgPx"])
            closed = True
        else:
            print(f"    Order close tidak terisi: {statuses}")
    else:
        print(f"    Respons API tidak terduga: {result}")

    if not closed:
        # Posisi tetap terlindungi karena TP/SL lama masih terpasang.
        print("    Close gagal - TP/SL lama masih aktif, posisi tetap terlindungi.")
        return None

    time.sleep(0.5)
    _cancel_orders_for_coin(exchange, coin)

    actual_pnl = (
        (exit_price - entry_px) / entry_px if is_long
        else (entry_px - exit_price) / entry_px
    )
    print(f"    Posisi DITUTUP @ ${exit_price} | PnL {actual_pnl*100:.2f}%")

    leverage = min(config.TARGET_LEVERAGE, max_leverage_for(coin))
    usd_pnl = config.MARGIN_PER_TRADE * leverage * actual_pnl
    send_close_signal(coin, direction, exit_price, usd_pnl, reason)

    return {
        "coin": coin, "action": "SMART_EXIT", "reason": reason,
        "pnl_percent": actual_pnl, "entry": entry_px, "exit": exit_price,
    }


def _trail_stop(exchange, coin, szi, is_long, new_sl, trail_type, pnl_percent):
    """Geser SL kalau SL baru lebih menguntungkan dari yang terpasang."""
    try:
        fe_orders = _post_info({"type": "frontendOpenOrders", "user": config.MAIN_WALLET})
    except (requests.RequestException, ValueError) as e:
        print(f"    Gagal ambil open orders: {e}")
        return None

    current_sl_oid = None
    current_sl_price = None
    for order in fe_orders:
        if (order.get("coin") == coin
                and order.get("orderType") == "Stop Market"
                and order.get("reduceOnly", False)):
            current_sl_oid = order["oid"]
            current_sl_price = float(order.get("triggerPx", 0))
            break

    if current_sl_price is not None:
        better = new_sl > current_sl_price if is_long else new_sl < current_sl_price
        if not better:
            print(f"    SL sudah optimal (sekarang ${current_sl_price}, target ${new_sl})")
            return None
    elif current_sl_oid is not None:
        return None

    print(f"    TRAILING STOP: {trail_type} -> SL baru ${new_sl}")
    try:
        if current_sl_oid:
            exchange.cancel(coin, current_sl_oid)
        order_type = {"trigger": {"triggerPx": new_sl, "isMarket": True, "tpsl": "sl"}}
        result = exchange.order(coin, not is_long, abs(szi), new_sl, order_type, reduce_only=True)
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        if statuses and "resting" in statuses[0]:
            print(f"    SL diperbarui ke ${new_sl} ({trail_type})")
            return {
                "coin": coin, "action": "TRAILING_STOP", "reason": trail_type,
                "old_sl": current_sl_price, "new_sl": new_sl, "pnl_percent": pnl_percent,
            }
        print(f"    Gagal pasang SL baru: {statuses}")
        # SL lama sudah terlanjur dibatalkan - pasang ulang supaya posisi tidak telanjang.
        if current_sl_price:
            try:
                exchange.order(
                    coin, not is_long, abs(szi), current_sl_price,
                    {"trigger": {"triggerPx": current_sl_price, "isMarket": True, "tpsl": "sl"}},
                    reduce_only=True,
                )
                print(f"    SL lama ${current_sl_price} dipasang kembali.")
            except Exception as e:
                print(f"    KRITIS: posisi {coin} tanpa SL! {e}")
    except Exception as e:
        print(f"    Error trailing stop: {e}")
    return None


# ============================================================
# SALDO
# ============================================================
def get_balances(info):
    """
    Ambil saldo perps dan spot secara terpisah.

    Bot lama memakai saldo USDC di *spot* sebagai account value, lalu
    menguranginya dengan margin yang dipakai di *perps*. Dua dompet yang
    berbeda. Kalau USDC menumpuk di spot, bot mengira punya margin bebas
    yang sebenarnya tidak bisa dipakai, dan ordernya ditolak exchange.
    """
    perp_value = 0.0
    perp_withdrawable = 0.0
    margin_used = 0.0
    try:
        user_state = info.user_state(config.MAIN_WALLET)
        summary = user_state.get("marginSummary", {})
        perp_value = float(summary.get("accountValue", 0) or 0)
        margin_used = float(summary.get("totalMarginUsed", 0) or 0)
        perp_withdrawable = float(user_state.get("withdrawable", 0) or 0)
    except Exception as e:
        print(f"  [SALDO] Gagal ambil state perps: {e}")
        user_state = {}

    spot_usdc = 0.0
    try:
        spot_data = _post_info(
            {"type": "spotClearinghouseState", "user": config.MAIN_WALLET}
        )
        for bal in spot_data.get("balances", []):
            if bal.get("coin") == "USDC":
                spot_usdc = float(bal.get("total", 0) or 0)
                break
    except (requests.RequestException, ValueError) as e:
        print(f"  [SALDO] Gagal ambil saldo spot: {e}")

    return {
        "user_state": user_state,
        "perp_value": perp_value,
        "perp_withdrawable": perp_withdrawable,
        "margin_used": margin_used,
        "spot_usdc": spot_usdc,
        "total": perp_value + spot_usdc,
    }


# ============================================================
# MAIN
# ============================================================
def run_bot():
    print("=" * 60)
    print("DeFi91 SCALPING BOT")
    print(f"Waktu : {get_wib_time().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print(f"Config: {config.summary()}")
    print("=" * 60)

    if not config.PRIVATE_KEY:
        print("ERROR: HYPERLIQUID_PRIVATE_KEY belum di-set.")
        return

    account = Account.from_key(config.PRIVATE_KEY)
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(account, constants.MAINNET_API_URL)

    # --- Saldo ---
    bal = get_balances(info)
    available = max(0.0, bal["perp_withdrawable"])
    print(f"\nEkuitas perps  : ${bal['perp_value']:.2f}")
    print(f"USDC spot      : ${bal['spot_usdc']:.2f}")
    print(f"Margin terpakai: ${bal['margin_used']:.2f}")
    print(f"Margin bebas   : ${available:.2f}")

    # --- Rekonsiliasi & risk state ---
    print("\n[RISK] Sinkronisasi state dari fill nyata...")
    risk_state = risk_manager.load_state()
    fills = risk_manager.fetch_fills(hours=48)
    risk_manager.refresh_from_fills(risk_state, fills)
    risk_manager.update_equity(risk_state, bal["total"])
    print(f"  PnL hari ini: ${risk_state['daily_pnl']:.2f} "
          f"({risk_state['daily_trades']} trade) | "
          f"Loss beruntun: {risk_state['consecutive_losses']} | "
          f"Drawdown: {risk_manager.current_drawdown_percent(risk_state):.1f}%")

    risk_manager.reconcile_trades()

    # --- Posisi terbuka ---
    positions = bal["user_state"].get("assetPositions", [])
    open_coins = [
        p["position"]["coin"] for p in positions
        if float(p.get("position", {}).get("szi", 0) or 0) != 0
    ]
    if open_coins:
        print(f"\nPosisi terbuka: {', '.join(open_coins)}")

    all_mids = info.all_mids()

    # --- Deteksi regime pasar (dipakai juga oleh grid bot) ---
    scan_list = sorted(set(config.WATCHLIST) | set(open_coins))
    print(f"\n[REGIME] Mendeteksi kondisi pasar untuk {len(scan_list)} koin...")
    regime_data = detect_market_regime_global(scan_list)
    global_regime = regime_data["global_regime"]
    _CACHE["regime_by_coin"] = {
        c: d.get("regime", "NEUTRAL") for c, d in regime_data["coins"].items()
    }
    print(f"  Global: {global_regime} "
          f"({regime_data['trending_coins']} trending / "
          f"{regime_data['neutral_coins']} neutral / "
          f"{regime_data['chopsaw_coins']} chopsaw)")

    try:
        with open(config.MARKET_REGIME_FILE, "w") as f:
            json.dump(regime_data, f, indent=2)
    except OSError as e:
        print(f"  Gagal simpan {config.MARKET_REGIME_FILE}: {e}")

    # --- Kelola posisi terbuka (selalu jalan) ---
    if open_coins:
        actions = manage_open_positions(exchange, info, all_mids)
        if actions:
            bal = get_balances(info)
            available = max(0.0, bal["perp_withdrawable"])
            positions = bal["user_state"].get("assetPositions", [])
            open_coins = [
                p["position"]["coin"] for p in positions
                if float(p.get("position", {}).get("szi", 0) or 0) != 0
            ]
            print(f"\n  [Update] Posisi terbuka: {len(open_coins)} | "
                  f"Margin bebas: ${available:.2f}")

    # --- Gerbang risiko sebelum entry baru ---
    can_trade, reason = risk_manager.check_all(risk_state, bal["total"])
    risk_state["halt_reason"] = None if can_trade else reason
    risk_manager.save_state(risk_state)

    if not can_trade:
        print(f"\n[STOP] Tidak mencari entry baru: {reason}")
        save_trades_json([], "HALTED", reason)
        return

    if len(open_coins) >= config.MAX_OPEN_POSITIONS:
        print(f"\n[STOP] Posisi maksimal tercapai "
              f"({len(open_coins)}/{config.MAX_OPEN_POSITIONS}).")
        save_trades_json([], "MAX_POSITIONS", "Batas posisi tercapai")
        return

    if available < config.MARGIN_PER_TRADE:
        print(f"\n[STOP] Margin bebas ${available:.2f} < "
              f"${config.MARGIN_PER_TRADE:.2f} per trade.")
        save_trades_json([], "NO_MARGIN", "Margin tidak cukup")
        return

    # --- Cari entry baru ---
    trades_executed = []

    for coin in config.WATCHLIST:
        if coin in open_coins:
            print(f"\n--- {coin}: SKIP (sudah punya posisi) ---")
            continue
        if len(open_coins) + len(trades_executed) >= config.MAX_OPEN_POSITIONS:
            print(f"\n--- {coin}: SKIP (batas {config.MAX_OPEN_POSITIONS} posisi) ---")
            break
        if available < config.MARGIN_PER_TRADE:
            print(f"\n--- {coin}: SKIP (margin habis) ---")
            break

        print(f"\n{'='*40}\nANALISA {coin}\n{'='*40}")

        current_price = float(all_mids.get(coin, 0) or 0)
        if current_price == 0:
            print(f"  Harga {coin} tidak tersedia - skip.")
            continue
        print(f"  Harga: ${current_price}")

        coin_regime = _CACHE["regime_by_coin"].get(coin, "UNKNOWN")
        print(f"  Regime: {coin_regime}")

        if coin_regime == "CHOPSAW" and coin not in config.CHOPSAW_ALLOWED_COINS:
            print("  SKIP: coin sedang chopsaw dan bukan koin likuiditas tinggi.")
            continue
        if global_regime == "CHOPSAW" and coin not in config.CHOPSAW_ALLOWED_COINS:
            print("  SKIP: pasar global chopsaw, coin ini tidak masuk whitelist.")
            continue

        onchain_score, onchain_details = analyze_onchain(coin)
        print(f"\n  [ORDER FLOW]")
        print(f"  CVD        : {onchain_details.get('cvd_signal')} "
              f"({onchain_details.get('cvd_buy_ratio')})")
        print(f"  Order Book : {onchain_details.get('ob_signal')} "
              f"(rasio {onchain_details.get('orderbook_ratio')})")
        print(f"  Funding    : {onchain_details.get('funding_signal')} "
              f"({onchain_details.get('funding_rate')})")
        print(f"  Skor order flow: {onchain_score:+d}/7")

        tech_score, tech_details = analyze_technical(coin, coin_regime)
        print(f"\n  [TEKNIKAL - mode {tech_details.get('mode')}]")
        print(f"  RSI  : {tech_details.get('rsi')} - {tech_details.get('rsi_signal')}")
        print(f"  MACD : {tech_details.get('macd')} - {tech_details.get('macd_signal')}")
        print(f"  ADX  : {tech_details.get('adx')} - {tech_details.get('trend_signal', '-')}")
        print(f"  S/R  : {tech_details.get('sr_signal', '-')} "
              f"(posisi {tech_details.get('price_position')})")
        print(f"  Skor teknikal: {tech_score:+d}/5")

        if not onchain_details.get("data_ok") or not tech_details.get("data_ok"):
            print("  SKIP: data tidak lengkap, tidak entry berdasarkan tebakan.")
            continue

        direction, total_score, why = decide_direction(onchain_score, tech_score)
        print(f"\n  TOTAL SKOR: {total_score:+d}/12")

        if direction is None:
            print(f"  KEPUTUSAN: TUNGGU - {why}")
            continue

        print(f"  KEPUTUSAN: {direction} (skor {total_score:+d}, "
              f"ambang ±{config.ENTRY_THRESHOLD})")

        trade_result = execute_trade(exchange, coin, direction, current_price)

        if trade_result.get("success"):
            trade_result["onchain_score"] = onchain_score
            trade_result["tech_score"] = tech_score
            trade_result["total_score"] = total_score
            trade_result["regime"] = coin_regime
            trade_result["rsi"] = tech_details.get("rsi", "N/A")
            trades_executed.append(trade_result)
            available -= config.MARGIN_PER_TRADE
            print("  TRADE BERHASIL DIEKSEKUSI")

            send_trade_signal(
                coin, direction, trade_result["entry_price"],
                trade_result["tp_price"], trade_result["sl_price"],
                trade_result.get("leverage", config.TARGET_LEVERAGE),
                config.MARGIN_PER_TRADE, total_score,
            )
        elif not trade_result.get("dry_run"):
            print(f"  Trade gagal: {trade_result.get('error', 'tidak diketahui')}")

    save_trades_json(trades_executed, "COMPLETED", "Run selesai")
    risk_manager.save_state(risk_state)

    print(f"\n{'='*60}")
    print(f"RUN SELESAI - {len(trades_executed)} trade dieksekusi")
    print(f"{'='*60}")


# ============================================================
# PENYIMPANAN DATA
# ============================================================
def save_trades_json(new_trades, status, message):
    """Simpan trade baru ke trades.json untuk dashboard."""
    try:
        with open(config.TRADES_FILE, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {"mode": "LIVE", "trades": [], "last_update": "", "bot_status": "ACTIVE"}

    data["mode"] = "DRY_RUN" if config.DRY_RUN else "LIVE"
    data["last_update"] = get_wib_time().strftime("%Y-%m-%d %H:%M:%S")
    data["bot_status"] = status
    data["status_message"] = message
    data["account_wallet"] = config.MAIN_WALLET

    trades = data.setdefault("trades", [])
    next_id = max((t.get("id", 0) for t in trades), default=0) + 1

    for i, trade in enumerate(new_trades):
        trades.append({
            "id": next_id + i,
            "time": get_wib_time().strftime("%Y-%m-%d %H:%M:%S"),
            "coin": trade["coin"],
            "signal": trade["direction"],
            "entry": trade["entry_price"],
            "tp": trade["tp_price"],
            "sl": trade["sl_price"],
            "size": trade["size"],
            "margin": config.MARGIN_PER_TRADE,
            "leverage": trade.get("leverage", config.TARGET_LEVERAGE),
            "tp_set": trade["tp_set"],
            "sl_set": trade["sl_set"],
            "status": "OPEN",
            "pnl": 0.0,
            "regime": trade.get("regime", "N/A"),
            "onchain_score": trade.get("onchain_score"),
            "tech_score": trade.get("tech_score"),
            "total_score": trade.get("total_score"),
            "rsi": trade.get("rsi", "N/A"),
        })

    try:
        with open(config.TRADES_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n  {config.TRADES_FILE} diperbarui ({len(new_trades)} trade baru)")
    except OSError as e:
        print(f"\n  Gagal simpan {config.TRADES_FILE}: {e}")


def update_performance_mini():
    """
    Tambah satu titik equity curve per run.

    Bot lama menulis titik baru setiap kali dipanggil, termasuk saat run
    berhenti lebih awal, sehingga grafiknya penuh nilai identik. Sekarang
    titik hanya ditambah kalau nilainya berubah dari titik terakhir.
    """
    try:
        with open(config.PERFORMANCE_FILE, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {"total_pnl": 0.0, "equity_curve": []}

    try:
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info.user_state(config.MAIN_WALLET)
        unrealized = sum(
            float(p.get("position", {}).get("unrealizedPnl", 0) or 0)
            for p in user_state.get("assetPositions", [])
            if float(p.get("position", {}).get("szi", 0) or 0) != 0
        )
    except Exception as e:
        print(f"\n  Lewati update performance.json: {e}")
        return

    current_equity = round(float(data.get("total_pnl", 0) or 0) + unrealized, 4)
    curve = data.setdefault("equity_curve", [])

    if curve and curve[-1].get("equity") == current_equity:
        print(f"\n  Equity tidak berubah (${current_equity:.4f}) - titik tidak ditambah.")
        return

    curve.append({
        "time": get_wib_time().strftime("%d/%m %H:%M"),
        "equity": current_equity,
    })
    data["equity_curve"] = curve[-100:]

    try:
        with open(config.PERFORMANCE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n  performance.json equity: ${current_equity:.4f}")
    except OSError as e:
        print(f"\n  Gagal simpan performance.json: {e}")


if __name__ == "__main__":
    run_bot()
    update_performance_mini()
