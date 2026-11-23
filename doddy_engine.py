"""
doddy_engine.py — "otak" keputusan DeFi91 berbasis DNA trading alm. Doddy Ali Wijaya.

Modul MURNI: tidak ada request jaringan, tidak ada order, tidak ada state global.
Semua fungsi menerima data candle yang SUDAH TERTUTUP dan mengembalikan keputusan
yang bisa diuji offline. Bot live (github_bot_v3.py) dan backtest memakai kode yang
sama persis, sehingga apa yang diuji = apa yang dijalankan.

Sumber DNA (arsip kanal DeFi 91, Nov 2021 – Jan 2023; lihat docs/DODDY_DNA.md):
  1. Bias besar dulu (weekly/daily, BTC "tf4"), eksekusi di TF kecil. [2489][3179]
  2. BTC = kompas; alt hanya searah BTC. [3179]
  3. "TA untuk open posisi, PA untuk langkah lanjutan." [3207]
  4. CVD spot dan perp DIPISAH; spot lebih menentukan. Spot kuat tapi perp tidak
     mendukung -> marking saja, jangan haka. Berlawanan & imbang -> WNS. [3396][3475][3468]
  5. Marking/probe kecil (BTC, ETH, BNB dulu); tidak jalan -> cepat tutup;
     tambah basket HANYA setelah posisi awal profit. [3179][2370]
  6. Tambah yang menang, jangan average yang rugi (kegagalan terbesarnya). [2986][1641]
  7. Ambil "secukupnya"; SL entry / SL+ untuk melindungi profit; tutup bila
     kelanjutan gagal (PA A-B-C). [3135][3382]
  8. Margin sama setiap entry; tidak membesar setelah menang. [3456]
  9. Berhenti setelah kalah / jangan re-entry impulsif. [1646][2335]

Ini rekonstruksi PRINSIP, bukan salinan sinyal. Tidak ada jaminan profit.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

CORE_COINS = ("BTC", "ETH", "BNB")

# Status flow (CVD spot vs perp)
FLOW_CONFIRMED = "CONFIRMED"   # spot kuat searah + perp searah -> boleh entry penuh & pyramid
FLOW_MARKING = "MARKING"       # spot kuat searah, perp belum mendukung -> probe saja
FLOW_AGAINST = "AGAINST"       # spot kuat melawan arah -> jangan entry; posisi searah ditutup
FLOW_WNS = "WNS"               # lemah / imbang / data kurang -> wait and see
FLOW_UNKNOWN = "UNKNOWN"       # data spot tidak tersedia -> fail-closed utk entry penuh


@dataclass
class DnaConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    slope_lookback: int = 5          # kemiringan EMA cepat dibanding N bar lalu
    flow_window: int = 6             # jam (bar 1h) utk CVD spot & A/D perp
    spot_strong: float = 0.06        # |CVD spot ternormalisasi| minimal agar dianggap "kuat"
    adx_min: float = 20.0            # tren 1h minimal (pullback dalam tren HTF)
    rsi_long: tuple = (45.0, 68.0)   # pita RSI 1h utk long: momentum ada, belum mengejar pucuk
    rsi_short: tuple = (32.0, 55.0)
    sl_atr: float = 1.5
    tp_atr: float = 2.5
    pyramid_atr: float = 1.0         # tranche terbaru harus sudah +1 ATR sebelum boleh tambah
    be_atr: float = 1.0              # profit >= 1 ATR -> SL entry (break-even + fee)
    lock_atr: float = 1.5            # profit >= 1.5 ATR -> SL+ (kunci 0.5 ATR)
    lock_keep_atr: float = 0.5
    trail_start_atr: float = 2.0     # profit >= 2 ATR -> trailing close - 1 ATR
    trail_dist_atr: float = 1.0
    fee_buffer_pct: float = 0.12     # % harga; SL entry diletakkan entry + biaya putaran
    probe_max_bars: int = 8          # probe (MARKING) tidak jalan dalam 8 jam -> tutup
    loss_cooldown_bars: int = 4      # setelah rugi di koin X, tunggu 4 jam sebelum re-entry X
    max_losses_per_day: int = 2      # setelah 2 kekalahan dalam satu hari WIB -> WNS sisa hari


# ------------------------------------------------------------------ indikator dasar
def ema_series(values: Sequence[float], n: int) -> List[float]:
    """EMA dengan seed = nilai pertama (sama dgn ema_calc di bot)."""
    if not values:
        return []
    k = 2.0 / (n + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(float(v) * k + out[-1] * (1 - k))
    return out


def rsi_wilder(closes: Sequence[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for a, b in zip(closes[:-1], closes[1:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag = (ag * (n - 1) + g) / n
        al = (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def atr_price(highs, lows, closes, n: int = 14) -> Optional[float]:
    """ATR dalam satuan harga (rata-rata sederhana 14 true range, sama dgn bot)."""
    if len(closes) < n + 1:
        return None
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
           for i in range(1, len(closes))]
    return sum(trs[-n:]) / n


def adx_wilder(highs, lows, closes, n: int = 14) -> Optional[float]:
    """ADX Wilder sejati. None bila data kurang (BUKAN default 50 seperti helper lama)."""
    m = len(closes)
    if m < 2 * n + 1:
        return None
    pdm, mdm, trs = [], [], []
    for i in range(1, m):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    def smooth(xs):
        s = [sum(xs[:n])]
        for x in xs[n:]:
            s.append(s[-1] - s[-1] / n + x)
        return s

    sp, sm_, st = smooth(pdm), smooth(mdm), smooth(trs)
    dxs = []
    for p, q, t in zip(sp, sm_, st):
        if t <= 0:
            dxs.append(0.0)
            continue
        dip, dim = 100 * p / t, 100 * q / t
        dxs.append(abs(dip - dim) / (dip + dim) * 100 if (dip + dim) > 0 else 0.0)
    if len(dxs) < n:
        return None
    adx = sum(dxs[:n]) / n
    for d in dxs[n:]:
        adx = (adx * (n - 1) + d) / n
    return adx


# ------------------------------------------------------------------ lapis 1: bias besar
def trend_state(closes: Sequence[float], cfg: DnaConfig = DnaConfig()) -> int:
    """+1 naik / -1 turun / 0 tidak jelas. EMA20 vs EMA50 + arah kemiringan EMA20."""
    if len(closes) < cfg.ema_slow + cfg.slope_lookback:
        return 0
    f = ema_series(closes, cfg.ema_fast)
    s = ema_series(closes, cfg.ema_slow)
    rising = f[-1] > f[-1 - cfg.slope_lookback]
    falling = f[-1] < f[-1 - cfg.slope_lookback]
    if f[-1] > s[-1] and rising:
        return 1
    if f[-1] < s[-1] and falling:
        return -1
    return 0


def htf_bias(closes_4h: Sequence[float], closes_1d: Sequence[float],
             cfg: DnaConfig = DnaConfig()) -> int:
    """Bias "gambaran daily dulu, lalu tf4": 4h menentukan arah, daily boleh netral
    tapi TIDAK boleh berlawanan. Berlawanan -> 0 (WNS)."""
    t4 = trend_state(closes_4h, cfg)
    t1d = trend_state(closes_1d, cfg)
    if t4 == 1 and t1d != -1:
        return 1
    if t4 == -1 and t1d != 1:
        return -1
    return 0


# ------------------------------------------------------------------ lapis 2: flow
def spot_cvd_norm(volumes: Sequence[float], taker_buys: Sequence[float],
                  window: int) -> Optional[float]:
    """CVD spot ternormalisasi pada `window` bar terakhir:
    sum(taker_buy - taker_sell) / sum(volume) = sum(2*tb - v)/sum(v), rentang -1..+1.
    Ini delta taker SUNGGUHAN (Binance spot), bukan proxy A/D."""
    if len(volumes) < window or len(taker_buys) < window:
        return None
    v = sum(volumes[-window:])
    if v <= 0:
        return None
    return sum(2 * tb - vv for tb, vv in zip(taker_buys[-window:], volumes[-window:])) / v


def perp_ad_sign(highs, lows, closes, volumes, window: int) -> int:
    """Arah tekanan perp (Hyperliquid) dari Accumulation/Distribution candle pada window
    terakhir. Proxy (HL tidak menyediakan taker delta historis) -> hanya dipakai sebagai
    konfirmasi pendukung, tidak pernah sebagai pemicu tunggal."""
    if len(closes) < window:
        return 0
    s = 0.0
    for h, l, c, v in zip(highs[-window:], lows[-window:], closes[-window:], volumes[-window:]):
        if h > l:
            s += ((c - l) - (h - c)) / (h - l) * v
    return 1 if s > 0 else (-1 if s < 0 else 0)


def classify_flow(direction: int, spot_norm: Optional[float], perp_sign: int,
                  cfg: DnaConfig = DnaConfig()) -> str:
    if direction == 0:
        return FLOW_WNS
    if spot_norm is None:
        return FLOW_UNKNOWN
    strong = abs(spot_norm) >= cfg.spot_strong
    spot_dir = 1 if spot_norm > 0 else (-1 if spot_norm < 0 else 0)
    if strong and spot_dir == -direction:
        return FLOW_AGAINST
    if strong and spot_dir == direction:
        return FLOW_CONFIRMED if perp_sign == direction else FLOW_MARKING
    return FLOW_WNS


# ------------------------------------------------------------------ lapis 3: pemicu TA
def entry_trigger(closes_1h, highs_1h, lows_1h, direction: int,
                  cfg: DnaConfig = DnaConfig()):
    """TA untuk open: tren 1h hidup (ADX), harga di sisi EMA20 yang benar, RSI di pita
    momentum yang belum mengejar pucuk. Return (ok, info)."""
    info = {}
    adx = adx_wilder(highs_1h, lows_1h, closes_1h, 14)
    rsi = rsi_wilder(closes_1h, 14)
    e20 = ema_series(closes_1h, cfg.ema_fast)[-1] if closes_1h else None
    info.update({"adx": adx, "rsi": rsi, "ema20": e20})
    if adx is None or rsi is None or e20 is None:
        info["why"] = "data kurang"
        return False, info
    if adx < cfg.adx_min:
        info["why"] = f"ADX {adx:.1f} < {cfg.adx_min}"
        return False, info
    c = closes_1h[-1]
    if direction == 1:
        lo, hi = cfg.rsi_long
        ok = c > e20 and lo <= rsi <= hi
    elif direction == -1:
        lo, hi = cfg.rsi_short
        ok = c < e20 and lo <= rsi <= hi
    else:
        ok = False
    if not ok:
        info["why"] = f"pemicu tak terpenuhi (close vs EMA20 / RSI {rsi:.1f})"
    return ok, info


# ------------------------------------------------------------------ lapis 4: tahap entry
@dataclass
class Decision:
    action: str                 # SKIP | OPEN | ADD
    direction: int = 0          # +1 LONG / -1 SHORT
    stage: str = ""             # MARKING | CONFIRMED
    reasons: List[str] = field(default_factory=list)


def decide_entry(coin: str, bias: int, btc_bias: int, flow: str, trigger_ok: bool,
                 position_dir: int, newest_tranche_profit_atr: Optional[float],
                 core_in_profit_dir: Optional[int], cap_allows: bool,
                 slots_free: bool, discipline_ok: bool,
                 cfg: DnaConfig = DnaConfig()) -> Decision:
    """Urutan keputusan DNA:
    - bias HTF wajib ada; alt wajib searah kompas BTC
    - TA harus memicu (open); flow AGAINST/WNS/UNKNOWN -> tidak entry
    - posisi BARU hanya saat MARKING (spot kuat memimpin, perp belum ikut)
    - alt hanya bila ada posisi core searah yang sudah profit (ekspansi basket)
    - pyramid (ADD) hanya bila tranche terbaru sudah +pyramid_atr (tambah yg menang)
    - tidak pernah average posisi rugi; tidak pernah buka lawan posisi yg ada
    """
    d = Decision("SKIP", bias)
    r = d.reasons
    if not discipline_ok:
        r.append("disiplin: cooldown/batas kalah harian (jangan re-entry impulsif)")
        return d
    if bias == 0:
        r.append("bias HTF tidak jelas -> WNS")
        return d
    is_core = coin in CORE_COINS
    if not is_core and btc_bias != bias:
        r.append("alt tidak searah kompas BTC")
        return d
    if position_dir == -bias:
        r.append("ada posisi berlawanan; biarkan manajemen posisi yg memutuskan")
        return d
    if flow in (FLOW_AGAINST, FLOW_WNS, FLOW_UNKNOWN):
        r.append(f"flow {flow}")
        return d
    if not trigger_ok:
        r.append("pemicu TA belum ada")
        return d
    if not cap_allows:
        r.append("cap margin per koin penuh")
        return d

    if position_dir == bias:  # pyramid: "tambah setelah konfirmasi + profit dari marking" [3477]
        if newest_tranche_profit_atr is None or newest_tranche_profit_atr < cfg.pyramid_atr:
            r.append("tranche terbaru belum cukup profit -> jangan tambah (anti average-down)")
            return d
        d.action, d.stage = "ADD", flow
        r.append("tambah posisi yang sudah menang")
        return d

    # Posisi BARU hanya lewat marking: spot kuat, perp belum ikut [3475][3476].
    # Bila spot & perp sudah sama-sama searah (CONFIRMED) gerakan sudah ramai -> jangan
    # dikejar dengan posisi baru (data TRAIN: entry baru CONFIRMED rata-rata rugi).
    if flow != FLOW_MARKING:
        r.append("flow sudah ramai (spot+perp searah) -> jangan kejar dengan posisi baru")
        return d
    if not slots_free:
        r.append("slot simbol penuh")
        return d
    if is_core:
        d.action, d.stage = "OPEN", FLOW_MARKING
        r.append("core: marking (spot memimpin, perp belum ikut)")
        return d
    if core_in_profit_dir != bias:
        r.append("basket alt menunggu posisi core searah yang sudah profit")
        return d
    d.action, d.stage = "OPEN", FLOW_MARKING
    r.append("ekspansi basket: core sudah profit, spot alt memimpin")
    return d


# ------------------------------------------------------------------ lapis 5: manajemen
def stop_ladder(entry: float, ref_price: float, atr: float, direction: int,
                current_sl: Optional[float], cfg: DnaConfig = DnaConfig()) -> Optional[float]:
    """SL entry -> SL+ -> trailing. Hanya memperketat. Return SL baru atau None."""
    if atr is None or atr <= 0 or direction == 0:
        return None
    prof = (ref_price - entry) * direction / atr
    cand = None
    if prof >= cfg.trail_start_atr:
        cand = ref_price - direction * cfg.trail_dist_atr * atr
    elif prof >= cfg.lock_atr:
        cand = entry + direction * cfg.lock_keep_atr * atr
    elif prof >= cfg.be_atr:
        cand = entry * (1 + direction * cfg.fee_buffer_pct / 100)
    if cand is None:
        return None
    if current_sl is not None:
        tighter = cand > current_sl if direction == 1 else cand < current_sl
        if not tighter:
            return None
    return cand


def exit_reason(direction: int, coin: str, bias: int, btc_bias: int, flow: str,
                stage: str, bars_open: int, pnl_atr: float,
                cfg: DnaConfig = DnaConfig()) -> Optional[str]:
    """PA untuk langkah lanjutan: tutup bila alasan memegang posisi hilang."""
    if bias == -direction:
        return "bias HTF berbalik"
    if coin not in CORE_COINS and btc_bias == -direction:
        return "kompas BTC berbalik (close basket)"
    if flow == FLOW_AGAINST:
        return "flow spot kuat melawan (kelanjutan gagal)"
    if stage == FLOW_MARKING and bars_open >= cfg.probe_max_bars and pnl_atr <= 0:
        return "marking tidak jalan -> cepat tutup"
    return None
