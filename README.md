# DeFi91 Trading Bot Ecosystem

Strategi Almarhum Doddy Ali Wijaya (CVD/Order Flow) + KJo Academy (RSI/MACD)
dengan dashboard web real-time, berjalan otomatis di GitHub Actions.

> 📄 **Baca dulu: [ANALISIS_DAN_SARAN.md](ANALISIS_DAN_SARAN.md)** — penjelasan
> lengkap cara kerja bot, daftar masalah yang ditemukan beserta perbaikannya,
> dan saran langkah berikutnya.

---

## ⚠️ Status: Bot dalam keadaan MATI

`BOT_ENABLED` default-nya `false`. Bot tidak akan mengirim order apa pun
sampai Anda menyalakannya sendiri (lihat [Menyalakan bot](#menyalakan-bot)).

Sebelum menyalakan, **cabut token Telegram lama** lewat `@BotFather` —
token itu sempat di-hardcode di repo ini dan masih tersimpan di riwayat git.

---

## Arsitektur

```
GitHub Actions (cron 11x/hari)
        │
        ├─► github_bot_v2.py   Scalping Bot  — aktif saat pasar TRENDING
        │     └─ config.py, indicators.py, risk_manager.py,
        │        market_regime_filter.py, telegram_signals.py
        │
        ├─► grid_bot.py        Grid Bot      — aktif saat pasar SIDEWAYS
        │
        └─► commit JSON ─► GitHub Pages (index.html) = dashboard
```

Kedua bot memakai **satu akun Hyperliquid** dan berkoordinasi lewat
`market_regime.json`: scalping bekerja saat ada tren, grid saat pasar
mondar-mandir.

### Peta file

| File | Peran |
|---|---|
| `config.py` | Semua parameter, dibaca dari environment variable |
| `indicators.py` | EMA, RSI, MACD, ATR, ADX, Bollinger (tanpa jaringan, bisa diuji) |
| `risk_manager.py` | Pengaman akun + rekonsiliasi `trades.json` |
| `github_bot_v2.py` | Scalping bot — file utama |
| `grid_bot.py` | Grid trading bot |
| `market_regime_filter.py` | Deteksi TRENDING / NEUTRAL / CHOPSAW |
| `optimize_params.py` | Analisa performa nyata dari fill exchange |
| `daily_report.py`, `journal_generator.py` | Laporan & jurnal harian (AI) |
| `telegram_*.py`, `weekly_insights.py` | Notifikasi Telegram |
| `index.html`, `journal/` | Dashboard (GitHub Pages) |
| `bot_final.py` | ⚠️ Deprecated — hanya meneruskan ke `github_bot_v2.py` |

---

## Konfigurasi

Semua parameter lewat environment variable. Di GitHub:
**Settings → Secrets and variables → Actions**.

### Secrets (rahasia — jangan pernah masuk ke kode)

| Nama | Keterangan |
|---|---|
| `HYPERLIQUID_PRIVATE_KEY` | Private key wallet trading |
| `TELEGRAM_BOT_TOKEN` | Token bot Telegram |
| `TELEGRAM_CHAT_ID` | Chat ID tujuan notifikasi |
| `OPENAI_API_KEY` | Untuk laporan & jurnal AI (opsional) |

### Variables (parameter — boleh terlihat)

| Nama | Default | Keterangan |
|---|---|---|
| `BOT_ENABLED` | `false` | **Kill switch.** Set `true` untuk trading nyata |
| `DRY_RUN` | `false` | Analisa jalan penuh, tapi order tidak dikirim |
| `GRID_ENABLED` | `false` | Kill switch grid bot |
| `WATCHLIST` | `ETH,XRP,SOL,SUI,BTC,BNB` | Koin yang dipantau |
| `MARGIN_PER_TRADE` | `3.00` | Margin per trade (USD) |
| `TARGET_LEVERAGE` | `10` | Leverage (dibatasi maksimum per coin) |
| `TP_PERCENT` | `0.024` | Take profit (2.4%) |
| `SL_PERCENT` | `0.012` | Stop loss (1.2%) — R:R 1:2 |
| `ENTRY_THRESHOLD` | `5` | Skor minimum untuk entry (dari ±12) |
| `MAX_OPEN_POSITIONS` | `3` | Batas posisi bersamaan |
| `ENTRY_SLIPPAGE` | `0.0015` | Slippage maksimum saat entry (0.15%) |
| `DAILY_LOSS_LIMIT` | `5.0` | Stop entry kalau rugi hari ini > $5 |
| `MAX_DRAWDOWN_PERCENT` | `25.0` | Stop kalau ekuitas −25% dari puncak |
| `MAX_CONSECUTIVE_LOSSES` | `4` | Jeda setelah 4 loss beruntun |
| `COOLDOWN_HOURS` | `6` | Lama jeda tersebut |
| `MIN_ACCOUNT_BALANCE` | `15.0` | Saldo minimum sebelum entry ditolak |

---

## Manajemen risiko

Sebelum entry baru, `risk_manager.check_all()` memeriksa berurutan:

1. Kill switch `BOT_ENABLED`
2. Cooldown aktif dari loss beruntun sebelumnya
3. Saldo di atas `MIN_ACCOUNT_BALANCE`
4. Rugi hari ini belum melewati `DAILY_LOSS_LIMIT`
5. Drawdown dari puncak belum melewati `MAX_DRAWDOWN_PERCENT`
6. Loss beruntun belum mencapai `MAX_CONSECUTIVE_LOSSES`

Kalau salah satu gagal, bot berhenti mencari entry. **Pengelolaan posisi yang
sudah terbuka tetap berjalan** — menutup posisi tidak pernah ikut terblokir.

Sebelum setiap order dikirim, `validate_order()` memastikan ukuran tidak nol
setelah pembulatan, notional ≥ $10 (minimum Hyperliquid), dan TP masih lebih
besar dari fee round-trip.

---

## Menjalankan secara lokal

```bash
pip install -r requirements.txt

# Jalankan tes (tidak perlu jaringan atau API key)
python tests/test_indicators.py

# Lihat matematika strategi saat ini
SKIP_NETWORK=1 python optimize_params.py

# Perbaiki riwayat trades.json dari fill nyata
python risk_manager.py

# Analisa performa per coin
python optimize_params.py

# Uji bot tanpa mengirim order
export HYPERLIQUID_PRIVATE_KEY=...
BOT_ENABLED=true DRY_RUN=true python github_bot_v2.py
```

## Menyalakan bot

1. Cabut token Telegram lama via `@BotFather`, buat baru, simpan sebagai secret
2. Pastikan semua secret sudah terisi
3. **Jalankan `DRY_RUN=true` minimal 1–2 minggu** dan periksa log
4. Baru setelah puas: set variable `BOT_ENABLED=true`, `DRY_RUN=false`

Workflow menjalankan `compileall` dan seluruh tes sebelum menyentuh exchange —
kalau ada yang gagal, bot tidak akan jalan.

---

## Otomatisasi

| Workflow | Jadwal | Isi |
|---|---|---|
| `trading_workflow_v2.yml` | 11x/hari | Scalping + grid bot, commit data, deploy Pages |
| `daily_report.yml` | 13:00 WIB | Laporan performa AI → `performance.json` |
| `trading_journal.yml` | 13:00 WIB | Jurnal trading harian → `journal/` |

Semua jadwal cron dalam UTC.
