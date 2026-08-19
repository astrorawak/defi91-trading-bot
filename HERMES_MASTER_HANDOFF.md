# 🏦 DeFi91 Master Strategy & Handoff (Panduan Strategis Hermes Agent)

Dokumen ini adalah cetak biru (blueprint) teknis dan strategis untuk **Hermes Agent** guna mengelola dan merevolusi bot trading DeFi91 milik Pak Karman.

---

## 📍 Data Lokasi & Akses
*   **Repository GitHub**: [astrorawak/defi91-trading-bot](https://github.com/astrorawak/defi91-trading-bot)
*   **Wallet Hyperliquid**: `0x03562722fE32Ff3BaFE214be3F1828A9157eC23D`
*   **Status Terakhir**: Bot sedang dalam mode **IDLE** (Watchlist dikosongkan) menunggu reaktivasi oleh Hermes dengan modal baru.

---

## 📜 Sejarah & Filosofi Strategi
Bot ini tidak dibangun secara sembarangan. Kita menggabungkan dua mazhab besar trading crypto:

1.  **CVD/Order Flow (Mazhab Almarhum Doddy Ali Wijaya)**:
    *   **Alasan**: Volume Delta tidak bisa berbohong. Jika harga turun tapi CVD naik tajam, itu artinya ada akumulasi besar-besaran oleh Market Maker (Whale).
    *   **Implementasi**: Bot memantau selisih volume beli dan jual secara real-time untuk mendapatkan skor -7 hingga +7.

2.  **Momentum/Technical (Mazhab KJo Academy)**:
    *   **Alasan**: CVD saja tidak cukup. Kita butuh RSI dan MACD untuk memastikan kita tidak "entry di pucuk" (overbought) atau melawan tren yang terlalu kuat.
    *   **Implementasi**: RSI (±2 poin) dan MACD (±2 poin) bertindak sebagai filter konfirmasi.

---

## 🔍 Audit Teknis: Mengapa Terjadi Drawdown? (Juli 2026)

Hermes, Anda harus mempelajari kegagalan Manus di bulan Juli agar tidak terulang:

1.  **Tragedi BTC (3 Juli)**: Terjadi loss **-$14.43** dalam satu trade.
    *   **Masalah**: Stop Loss (SL) mungkin tidak tereksekusi tepat waktu atau slippage terlalu besar saat pasar drop liar.
    *   **Saran**: Anda harus mengevaluasi apakah SL 1.5% cukup aman untuk leverage 20x.

2.  **Jebakan Microcap XPL (4-5 Juli)**: Loss total **-$22.80**.
    *   **Masalah**: Sinyal CVD pada koin kecil (XPL) seringkali manipulatif. Whale bisa dengan mudah "mempermainkan" volume delta di koin microcap.
    *   **Saran**: **Haramkan** koin microcap kecuali volumenya masuk Top 10 di Hyperliquid.

3.  **Fee Attrition**:
    *   **Masalah**: Trading terlalu sering dengan profit kecil seringkali habis dimakan biaya fee Hyperliquid.
    *   **Saran**: Hitung potensi profit vs estimasi fee sebelum membuka posisi.

---

## 🛠 Struktur Kode (Internal Logic)

*   **Scoring System**: Bot memberikan skor total antara -12 (Sangat Bearish) hingga +12 (Sangat Bullish).
    *   **Entry Threshold**: Saat ini di-set ke **±4**.
    *   **Smart Exit**: Saat ini di-set ke **±7**. (Jika kita sedang LONG, dan skor tiba-tiba menjadi -7, bot akan langsung tutup posisi).
*   **Dynamic Watchlist**: Bot sekarang sudah memiliki fitur untuk mengurutkan koin berdasarkan volatilitas (ATR%) agar selalu trading di koin yang "bernyawa".

---

## 🚀 Misi Masa Depan: Apa yang Harus Hermes Lakukan?

Pak Karman ingin Anda melampaui kemampuan agen AI standar. Berikut adalah area eksplorasi Anda:

1.  **Evaluasi Formula (Re-Engineering)**:
    *   Cek apakah RSI 14 dan MACD (12, 26, 9) masih relevan. Gunakan data `trades.json` untuk melakukan *backtest* mandiri dan temukan settingan indikator yang lebih akurat.
    *   Buat formula baru jika perlu. Misalnya: Tambahkan VWAP atau EMA Cross sebagai filter tambahan.

2.  **Kecerdasan Berita (News Sentiment)**:
    *   Sebelum eksekusi, lakukan pencarian web: *"Sentimen pasar crypto 1 jam terakhir"*. Jika ada berita negatif besar (misal: SEC gugat koin tertentu), batalkan entry meskipun teknikal bilang BUY.

3.  **Whale Tracker**:
    *   Pantau perpindahan dana besar. Jika ada Whale memindahkan ribuan BTC ke bursa, itu sinyal bahaya. Berikan peringatan ke Telegram Pak Karman.

4.  **Auto-Optimization**:
    *   Jika dalam 24 jam bot mengalami loss > 5%, Anda harus otomatis "mengunci" bot dan meminta evaluasi ulang strategi sebelum lanjut.

---

## 🤖 MASTER PROMPT UNTUK HERMES

> "Anda adalah **Hermes DeFi91 Strategist**, pengelola dana AI tingkat tinggi.
>
> **Langkah 1**: Audit repository `astrorawak/defi91-trading-bot`. Pahami file `github_bot_v2.py` dan `market_regime_filter.py`.
> **Langkah 2**: Analisis 'Borok' Juli di `HERMES_MASTER_HANDOFF.md`. Mengapa BTC dan XPL bisa menghancurkan saldo?
> **Langkah 3**: Lakukan pencarian web tentang kondisi pasar saat ini. Apakah aman untuk mulai trading dengan modal $50?
> **Langkah 4**: Berikan konsep strategi baru Anda kepada Pak Karman. Apakah Anda akan tetap menggunakan CVD+RSI+MACD atau Anda punya formula yang lebih cerdas?
> **Langkah 5**: Setelah disetujui, aktifkan kembali bot dengan mengupdate `WATCHLIST` di kode."

---

**Status: SIAP UNTUK EVOLUSI**
*Dibuat oleh Manus AI (19 Agustus 2026)*
