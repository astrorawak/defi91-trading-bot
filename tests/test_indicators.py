"""
Uji indikator dan logika keputusan.

Tanpa tes seperti ini, kesalahan rumus MACD di versi lama bisa bertahan
berbulan-bulan tanpa ketahuan - hasilnya tetap berupa angka, hanya saja
angka yang salah.

Jalankan: python -m pytest tests/ -v    (atau: python tests/test_indicators.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import (  # noqa: E402
    calculate_adx,
    calculate_atr,
    calculate_bollinger_band_width,
    calculate_macd,
    calculate_rsi,
    ema,
    swing_levels,
)


def _series(n=120, start=100.0, step=1.0):
    return [start + step * i for i in range(n)]


# ------------------------------------------------------------
# EMA
# ------------------------------------------------------------
def test_ema_konstan():
    """EMA dari deret konstan harus sama dengan nilai itu sendiri."""
    out = ema([50.0] * 40, 12)
    assert abs(out[-1] - 50.0) < 1e-9


def test_ema_lebih_responsif_dari_sma():
    """
    Saat harga melompat, EMA harus bereaksi lebih cepat dari rata-rata
    sederhana. Inilah alasan MACD memakai EMA, bukan SMA seperti versi lama.
    """
    prices = [100.0] * 40 + [130.0]
    sma = sum(prices[-12:]) / 12
    assert ema(prices, 12)[-1] > sma


# ------------------------------------------------------------
# RSI
# ------------------------------------------------------------
def test_rsi_naik_terus():
    """Harga naik monoton -> RSI harus mendekati 100."""
    assert calculate_rsi(_series(60), 14) > 95


def test_rsi_turun_terus():
    """Harga turun monoton -> RSI harus mendekati 0."""
    assert calculate_rsi(_series(60, start=200, step=-1), 14) < 5


def test_rsi_data_kurang():
    assert calculate_rsi([1, 2, 3], 14) == 50.0


def test_rsi_dalam_rentang():
    import random

    random.seed(42)
    prices = [100.0]
    for _ in range(200):
        prices.append(max(1.0, prices[-1] * (1 + random.uniform(-0.02, 0.02))))
    assert 0.0 <= calculate_rsi(prices, 14) <= 100.0


# ------------------------------------------------------------
# MACD
# ------------------------------------------------------------
def test_macd_uptrend_positif():
    """Tren naik -> MACD line di atas nol."""
    macd, _, _ = calculate_macd(_series(80))
    assert macd > 0


def test_macd_downtrend_negatif():
    macd, _, _ = calculate_macd(_series(80, start=200, step=-1))
    assert macd < 0


def test_macd_momentum_konstan_histogram_nol():
    """
    Kenaikan linear = momentum konstan = tidak ada akselerasi,
    jadi histogram harus ~nol. Ini justru pembeda MACD yang benar:
    rumus lama (selisih dua rata-rata sederhana) tidak punya sifat ini.
    """
    _, _, hist = calculate_macd(_series(80))
    assert abs(hist) < 1e-6


def test_macd_akselerasi_histogram_positif():
    """Tren naik yang makin cepat -> MACD di atas signal, histogram positif."""
    prices = [100 * (1.01 ** i) for i in range(80)]
    macd, signal, hist = calculate_macd(prices)
    assert macd > signal
    assert hist > 0


def test_macd_pembalikan_histogram_negatif():
    """Naik lalu berbalik turun -> histogram harus jadi negatif."""
    prices = [100 + i for i in range(40)] + [140 - 0.5 * i for i in range(40)]
    _, _, hist = calculate_macd(prices)
    assert hist < 0


def test_macd_datar_nol():
    macd, signal, hist = calculate_macd([100.0] * 80)
    assert abs(macd) < 1e-6
    assert abs(hist) < 1e-6


def test_macd_histogram_konsisten():
    """Histogram harus persis macd - signal, bukan rumus lain."""
    macd, signal, hist = calculate_macd(_series(80))
    assert abs(hist - (macd - signal)) < 1e-9


def test_macd_data_kurang():
    assert calculate_macd([1, 2, 3]) == (0.0, 0.0, 0.0)


# ------------------------------------------------------------
# ADX
# ------------------------------------------------------------
def test_adx_tren_kuat():
    """Tren naik bersih -> ADX tinggi dan DI+ di atas DI-."""
    n = 120
    closes = _series(n)
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    adx, di_plus, di_minus = calculate_adx(highs, lows, closes, 14)
    assert adx > 40
    assert di_plus > di_minus


def test_adx_sideways_rendah():
    """Harga bolak-balik di range sempit -> ADX rendah."""
    closes = [100 + (1 if i % 2 else -1) for i in range(120)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    adx, _, _ = calculate_adx(highs, lows, closes, 14)
    assert adx < 25


def test_adx_data_kurang():
    assert calculate_adx([1, 2], [1, 2], [1, 2], 14) == (0.0, 0.0, 0.0)


# ------------------------------------------------------------
# ATR & Bollinger
# ------------------------------------------------------------
def test_atr_positif():
    closes = _series(60)
    highs = [c + 2 for c in closes]
    lows = [c - 2 for c in closes]
    assert calculate_atr(highs, lows, closes, 14) > 0


def test_bb_width_datar_nol():
    assert calculate_bollinger_band_width([100.0] * 40, 20, 2) == 0.0


def test_bb_width_volatil_lebih_lebar():
    tenang = [100 + (0.1 if i % 2 else -0.1) for i in range(40)]
    ribut = [100 + (5 if i % 2 else -5) for i in range(40)]
    assert calculate_bollinger_band_width(ribut) > calculate_bollinger_band_width(tenang)


def test_swing_levels_pakai_wick():
    """Support/resistance harus dari high/low, bukan dari close saja."""
    closes = [100] * 30
    highs = [100] * 29 + [110]
    lows = [90] + [100] * 29
    resistance, support = swing_levels(highs, lows, 30)
    assert resistance == 110
    assert support == 90


# ------------------------------------------------------------
# Logika keputusan entry
# ------------------------------------------------------------
def test_konfluensi_menolak_sinyal_bertentangan():
    """
    Order flow sangat bullish tapi teknikal bearish -> jangan entry,
    walaupun jumlah skornya melewati ambang.
    """
    import config
    from github_bot_v2 import decide_direction

    direction, total, why = decide_direction(7, -2)
    assert total >= config.ENTRY_THRESHOLD
    assert direction is None
    assert "konfluen" in why


def test_konfluensi_menerima_sinyal_searah():
    from github_bot_v2 import decide_direction

    assert decide_direction(4, 2)[0] == "LONG"
    assert decide_direction(-4, -2)[0] == "SHORT"


def test_skor_lemah_tidak_entry():
    from github_bot_v2 import decide_direction

    assert decide_direction(1, 1)[0] is None


# ------------------------------------------------------------
# Matematika risiko
# ------------------------------------------------------------
def test_breakeven_win_rate_masuk_akal():
    """
    Dengan R:R sekarang, win-rate impas harus di antara 0 dan 1 dan
    lebih rendah dari 50% (karena TP lebih besar dari SL).
    """
    import config

    be = config.breakeven_win_rate()
    assert 0.0 < be < 1.0
    if config.TP_PERCENT > config.SL_PERCENT:
        assert be < 0.5


def test_ekspektasi_negatif_di_bawah_breakeven():
    import config

    be = config.breakeven_win_rate()
    assert config.expected_value_per_trade(be - 0.05) < 0
    assert config.expected_value_per_trade(be + 0.05) > 0


def test_validate_order_tolak_notional_kecil():
    import config
    import risk_manager

    ok, reason = risk_manager.validate_order("TEST", 0.001, 1000.0, 5)
    assert not ok
    assert "notional" in reason

    ok, _ = risk_manager.validate_order(
        "TEST", 1.0, config.MIN_ORDER_VALUE_USD * 10, config.TARGET_LEVERAGE
    )
    assert ok


def test_validate_order_tolak_size_nol():
    import risk_manager

    ok, reason = risk_manager.validate_order("TEST", 0.0, 100.0, 10)
    assert not ok


if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    gagal = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            gagal += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - gagal}/{len(tests)} tes lolos")
    sys.exit(1 if gagal else 0)
