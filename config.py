"""
Konfigurasi terpusat untuk DeFi91 Trading Bot.

Semua parameter yang sebelumnya tersebar (dan di-hardcode) di masing-masing
file sekarang dibaca dari environment variable dengan default yang aman.
Tujuannya: ganti parameter tanpa mengedit kode, dan tidak ada rahasia yang
ikut ter-commit ke repo.

Cara pakai (GitHub Actions -> Settings -> Secrets and variables):
  - Secrets : HYPERLIQUID_PRIVATE_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY
  - Variables: BOT_ENABLED, WATCHLIST, MARGIN_PER_TRADE, dst.
"""

import os

# ============================================================
# HELPER PARSER
# ============================================================
def _env_str(name, default=""):
    return os.getenv(name, default).strip()


def _env_float(name, default):
    try:
        return float(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return int(float(os.getenv(name, "").strip() or default))
    except (TypeError, ValueError):
        return int(default)


def _env_bool(name, default=False):
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on", "aktif")


def _env_list(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


# ============================================================
# KILL SWITCH
# ============================================================
# Default False supaya bot TIDAK otomatis menaruh order uang sungguhan
# setelah update kode. Set BOT_ENABLED=true kalau memang mau live.
BOT_ENABLED = _env_bool("BOT_ENABLED", False)
GRID_ENABLED = _env_bool("GRID_ENABLED", False)

# DRY_RUN=true -> semua analisa tetap jalan & tercatat, tapi tidak ada order
# yang dikirim ke exchange. Berguna untuk uji strategi tanpa risiko.
DRY_RUN = _env_bool("DRY_RUN", False)

# ============================================================
# AKUN & API
# ============================================================
PRIVATE_KEY = _env_str("HYPERLIQUID_PRIVATE_KEY")
MAIN_WALLET = _env_str(
    "HYPERLIQUID_ADDRESS", "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
)
INFO_URL = "https://api.hyperliquid.xyz/info"
HTTP_TIMEOUT = _env_int("HTTP_TIMEOUT", 15)

# ============================================================
# WATCHLIST
# ============================================================
# Koin yang secara historis paling layak (berdasar 873+ fills di akun ini).
DEFAULT_WATCHLIST = ["ETH", "XRP", "SOL", "SUI", "BTC", "BNB"]
WATCHLIST = _env_list("WATCHLIST", DEFAULT_WATCHLIST)

# Koin yang tetap boleh ditrade meski pasar global CHOPSAW (likuiditas tinggi).
CHOPSAW_ALLOWED_COINS = _env_list(
    "CHOPSAW_ALLOWED_COINS", ["ETH", "XRP", "SOL", "BTC"]
)

# ============================================================
# PARAMETER TRADE
# ============================================================
MARGIN_PER_TRADE = _env_float("MARGIN_PER_TRADE", 3.00)
TARGET_LEVERAGE = _env_int("TARGET_LEVERAGE", 10)

# TP/SL dalam fraksi harga (0.02 = 2%).
# Rasio R:R minimal 1:2 supaya masih untung di win-rate ~40%.
TP_PERCENT = _env_float("TP_PERCENT", 0.024)
SL_PERCENT = _env_float("SL_PERCENT", 0.012)

ENTRY_THRESHOLD = _env_int("ENTRY_THRESHOLD", 5)
MAX_OPEN_POSITIONS = _env_int("MAX_OPEN_POSITIONS", 3)

# Slippage maksimum yang diterima saat entry (IOC limit band).
# 0.5% di leverage 20x = 10% dari margin -> terlalu longgar. 0.15% jauh lebih aman.
ENTRY_SLIPPAGE = _env_float("ENTRY_SLIPPAGE", 0.0015)
EXIT_SLIPPAGE = _env_float("EXIT_SLIPPAGE", 0.01)

# ============================================================
# SMART EXIT & TRAILING STOP
# ============================================================
SMART_EXIT_THRESHOLD = _env_int("SMART_EXIT_THRESHOLD", 6)
TRAILING_BREAKEVEN = _env_float("TRAILING_BREAKEVEN", 0.008)
TRAILING_LOCK = _env_float("TRAILING_LOCK", 0.015)
TRAILING_LOCK_PROFIT = _env_float("TRAILING_LOCK_PROFIT", 0.005)

# ============================================================
# BIAYA (dipakai untuk validasi ekspektasi profit)
# ============================================================
# Taker fee Hyperliquid ~0.045% per sisi. Round-trip = 2x.
TAKER_FEE = _env_float("TAKER_FEE", 0.00045)
# Nilai order minimum di Hyperliquid perps.
MIN_ORDER_VALUE_USD = _env_float("MIN_ORDER_VALUE_USD", 10.0)

# ============================================================
# RISK MANAGEMENT
# ============================================================
# Bot berhenti buka posisi baru kalau rugi hari ini melewati batas ini (USD).
DAILY_LOSS_LIMIT = _env_float("DAILY_LOSS_LIMIT", 5.0)
# Berhenti kalau ekuitas turun sekian persen dari puncak.
MAX_DRAWDOWN_PERCENT = _env_float("MAX_DRAWDOWN_PERCENT", 25.0)
# Berhenti sementara setelah sekian kali loss beruntun.
MAX_CONSECUTIVE_LOSSES = _env_int("MAX_CONSECUTIVE_LOSSES", 4)
COOLDOWN_HOURS = _env_float("COOLDOWN_HOURS", 6.0)
# Saldo minimum sebelum bot menolak entry baru.
MIN_ACCOUNT_BALANCE = _env_float("MIN_ACCOUNT_BALANCE", 15.0)

RISK_STATE_FILE = _env_str("RISK_STATE_FILE", "risk_state.json")

# ============================================================
# GRID BOT
# ============================================================
GRID_CANDIDATES = _env_list("GRID_CANDIDATES", ["ETH", "XRP", "SOL", "SUI", "BNB"])
MAX_GRID_PAIRS = _env_int("MAX_GRID_PAIRS", 3)
GRID_LEVELS = _env_int("GRID_LEVELS", 3)
GRID_LEVERAGE = _env_int("GRID_LEVERAGE", 5)
GRID_TOTAL_BUDGET = _env_float("GRID_TOTAL_BUDGET", 20.0)
GRID_RANGE_MULTIPLIER = _env_float("GRID_RANGE_MULTIPLIER", 1.5)

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID")

# ============================================================
# FILE OUTPUT
# ============================================================
TRADES_FILE = "trades.json"
PERFORMANCE_FILE = "performance.json"
MARKET_REGIME_FILE = "market_regime.json"
GRID_TRADES_FILE = "grid_trades.json"


def expected_value_per_trade(win_rate):
    """
    Ekspektasi profit per trade (dalam fraksi margin) pada win-rate tertentu,
    sudah termasuk fee round-trip.

    Dipakai untuk menjawab: 'dengan TP/SL sekarang, win-rate berapa yang
    dibutuhkan supaya bot tidak rugi?'
    """
    gross_win = TP_PERCENT * TARGET_LEVERAGE
    gross_loss = SL_PERCENT * TARGET_LEVERAGE
    fee_cost = 2 * TAKER_FEE * TARGET_LEVERAGE
    return win_rate * gross_win - (1 - win_rate) * gross_loss - fee_cost


def breakeven_win_rate():
    """Win-rate minimum agar strategi impas (sudah termasuk fee)."""
    gross_win = TP_PERCENT * TARGET_LEVERAGE
    gross_loss = SL_PERCENT * TARGET_LEVERAGE
    fee_cost = 2 * TAKER_FEE * TARGET_LEVERAGE
    denom = gross_win + gross_loss
    if denom <= 0:
        return 1.0
    return (gross_loss + fee_cost) / denom


def summary():
    """String ringkas konfigurasi aktif, dicetak di awal setiap run."""
    return (
        f"BOT_ENABLED={BOT_ENABLED} DRY_RUN={DRY_RUN} | "
        f"Watchlist={','.join(WATCHLIST) or '(kosong)'} | "
        f"Margin=${MARGIN_PER_TRADE} Lev={TARGET_LEVERAGE}x | "
        f"TP={TP_PERCENT*100:.2f}% SL={SL_PERCENT*100:.2f}% | "
        f"Threshold={ENTRY_THRESHOLD} MaxPos={MAX_OPEN_POSITIONS} | "
        f"Breakeven WR={breakeven_win_rate()*100:.1f}%"
    )
