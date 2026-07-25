"""
Analisa performa untuk menyetel parameter bot.

Versi lama memfilter trade dengan status == "CLOSED", padahal tidak ada satu
pun entri di trades.json yang pernah diubah dari "OPEN" - jadi script ini
selalu mencetak "Not enough closed trades" dan tidak pernah berguna.

Sekarang script mengambil data langsung dari fill Hyperliquid (sumber
kebenaran yang sesungguhnya), dengan trades.json sebagai pelengkap untuk
melihat skor sinyal apa yang menghasilkan trade tersebut.

Jalankan: python optimize_params.py
"""

import json
import os
from collections import defaultdict

import config
import risk_manager


def load_json(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def analyze_from_fills(hours=24 * 30):
    """Analisa PnL nyata per coin dari fill exchange (sudah dikurangi fee)."""
    fills = risk_manager.fetch_fills(hours=hours)
    closing = [f for f in fills if float(f.get("closedPnl", 0) or 0) != 0]

    if not closing:
        print("Tidak ada fill penutup dalam rentang waktu ini.")
        return {}

    stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "fees": 0.0})
    for f in closing:
        coin = f.get("coin", "?")
        fee = float(f.get("fee", 0) or 0)
        net = float(f.get("closedPnl", 0) or 0) - fee
        s = stats[coin]
        s["trades"] += 1
        s["pnl"] += net
        s["fees"] += fee
        if net > 0:
            s["wins"] += 1

    print(f"\n{'='*70}")
    print(f"PERFORMA PER COIN (dari {len(closing)} fill penutup, {hours//24} hari)")
    print(f"{'='*70}")
    print(f"{'COIN':<8}{'TRADE':>7}{'WIN%':>8}{'NET PnL':>12}{'FEE':>10}{'PnL/TRADE':>12}")
    print("-" * 70)

    total_pnl = total_fees = total_trades = 0
    for coin, s in sorted(stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        per = s["pnl"] / s["trades"] if s["trades"] else 0
        print(f"{coin:<8}{s['trades']:>7}{wr:>7.1f}%{s['pnl']:>12.3f}"
              f"{s['fees']:>10.3f}{per:>12.4f}")
        total_pnl += s["pnl"]
        total_fees += s["fees"]
        total_trades += s["trades"]

    print("-" * 70)
    print(f"{'TOTAL':<8}{total_trades:>7}{'':>8}{total_pnl:>12.3f}{total_fees:>10.3f}")

    if total_trades:
        print(f"\nFee memakan {abs(total_fees):.2f} USD "
              f"({abs(total_fees)/max(abs(total_pnl)+abs(total_fees), 1e-9)*100:.0f}% "
              f"dari pergerakan kotor).")

    return stats


def analyze_signal_quality():
    """
    Lihat skor sinyal seperti apa yang menghasilkan trade menang vs kalah.
    Membutuhkan trades.json yang sudah direkonsiliasi.
    """
    data = load_json(config.TRADES_FILE)
    if not data:
        return

    trades = data.get("trades", [])
    closed = [t for t in trades
              if t.get("status") == "CLOSED" and t.get("pnl") is not None]

    if not closed:
        print("\nBelum ada trade terekonsiliasi. Jalankan: python risk_manager.py")
        return

    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    for t in closed:
        score = t.get("total_score")
        if score is None:
            score = t.get("cvd_score")
        try:
            score = int(float(score))
        except (TypeError, ValueError):
            continue
        b = buckets[abs(score)]
        b["n"] += 1
        b["pnl"] += float(t["pnl"])
        if float(t["pnl"]) > 0:
            b["wins"] += 1

    if not buckets:
        return

    print(f"\n{'='*70}")
    print("KUALITAS SINYAL: |skor| saat entry vs hasil")
    print(f"{'='*70}")
    print(f"{'|SKOR|':<9}{'TRADE':>7}{'WIN%':>8}{'NET PnL':>12}{'PnL/TRADE':>12}")
    print("-" * 70)
    for score in sorted(buckets):
        b = buckets[score]
        wr = b["wins"] / b["n"] * 100
        print(f"{score:<9}{b['n']:>7}{wr:>7.1f}%{b['pnl']:>12.3f}"
              f"{b['pnl']/b['n']:>12.4f}")

    print("\nCara membacanya: kalau win-rate naik seiring |skor|, ambang entry "
          "(ENTRY_THRESHOLD) layak dinaikkan. Kalau datar, skor tidak punya "
          "daya prediksi dan strateginya yang perlu diganti - bukan ambangnya.")


def show_risk_math():
    """Tampilkan matematika dasar strategi saat ini."""
    be = config.breakeven_win_rate()
    print(f"\n{'='*70}")
    print("MATEMATIKA STRATEGI SAAT INI")
    print(f"{'='*70}")
    print(f"  TP {config.TP_PERCENT*100:.2f}% | SL {config.SL_PERCENT*100:.2f}% "
          f"| Leverage {config.TARGET_LEVERAGE}x")
    print(f"  Rasio R:R          : 1 : {config.TP_PERCENT/config.SL_PERCENT:.2f}")
    print(f"  Win-rate impas     : {be*100:.1f}%  (termasuk fee round-trip)")
    print(f"  Ekspektasi @ 40% WR: {config.expected_value_per_trade(0.40)*100:+.2f}% dari margin")
    print(f"  Ekspektasi @ 50% WR: {config.expected_value_per_trade(0.50)*100:+.2f}% dari margin")
    print(f"  Ekspektasi @ 60% WR: {config.expected_value_per_trade(0.60)*100:+.2f}% dari margin")


if __name__ == "__main__":
    show_risk_math()
    if os.getenv("SKIP_NETWORK"):
        print("\n(SKIP_NETWORK di-set - analisa fill dilewati)")
    else:
        analyze_from_fills()
    analyze_signal_quality()
