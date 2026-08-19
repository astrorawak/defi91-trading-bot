# 🤖 Dokumen Serah Terima Master: DeFi91 Trading Bot (Handoff ke Hermes)

Dokumen ini adalah panduan strategis untuk **Hermes Agent** agar dapat mengambil alih, mengevaluasi, dan menyempurnakan bot trading milik Pak Karman.

---

## 1. Analisis Kegagalan & Riwayat Buruk (Audit Manus)

Sebelum Hermes mulai, ia harus tahu mengapa saldo sempat tergerus. Berikut adalah "borok" yang saya temukan dari analisis data real API:

### A. Koin "Pembunuh" Saldo (Drawdown Terbesar)
| Koin | Estimasi Loss | Penyebab Utama |
|:-----|:--------------|:---------------|
| **XPL** | -$545.73 | Microcap dengan volatilitas liar, sinyal CVD sering "false breakout". |
| **FARTCOIN** | -$257.93 | Meme coin yang tidak mengikuti logika teknikal standar. |
| **ZEC** | -$201.46 | Terjadi 1 trade loss fatal -$101 karena pergerakan tiba-tiba. |
| **BTC** | -$104.63 | **Fee Attrition**: Profit kotor $174 tapi biaya fee $287! |

### B. Mengapa Uang Tergerus?
1.  **Fee yang Mematikan**: Bot melakukan terlalu banyak trade kecil (High Frequency). Karena margin per trade kecil ($1.5 - $3), persentase biaya fee Hyperliquid (Taker) memakan hampir seluruh profit kotor.
2.  **Smart Exit Terlalu Penakut**: Pada versi awal, threshold Smart Exit di-set ke **4**. Artinya, saat harga berbalik sedikit saja, bot langsung "panik" dan menutup posisi (Cut Loss prematur). Padahal, 42% trade yang dibiarkan lebih dari 30 menit terbukti berakhir profit.
3.  **Watchlist Sampah**: Memasukkan koin-koin baru yang tidak punya sejarah profit (ENA, ADA, CRV) yang ternyata memiliki Win Rate di bawah 20%.

---

## 2. Struktur Bot Saat Ini (Kondisi Terakhir)

Hermes harus memahami mesin yang sudah berjalan:

*   **Strategi Scalping (`github_bot_v2.py`)**:
    *   **Logic**: Hybrid CVD (Order Flow) + RSI/MACD.
    *   **Threshold**: ±4 untuk Entry, ±7 untuk Smart Exit.
    *   **Risk**: Margin $3.00, Leverage 20x, TP 2.0%, SL 1.5%.
*   **Strategi Grid (`grid_bot.py`)**:
    *   **Logic**: Range trading saat pasar Sideways/Chopsaw.
    *   **Budget**: $20 total, 5x Leverage.
*   **Filter Market (`market_regime_filter.py`)**:
    *   Mendeteksi `TRENDING`, `NEUTRAL`, atau `CHOPSAW`.

---

## 3. Rekomendasi Sempurna untuk Hermes (The Upgrade)

Pak Karman ingin Hermes melakukan apa yang tidak bisa dilakukan Manus. Berikut instruksi peningkatannya:

1.  **Integrasi News & Sentiment**: Hermes harus membaca berita crypto (Coindesk, X, Whale Alert) sebelum entry. Jangan LONG jika ada berita negatif meskipun teknikal bilang BUY.
2.  **Whale Monitoring**: Pantau perpindahan dana besar di Hyperliquid. Jika whale sedang akumulasi, Hermes harus menyesuaikan agresivitasnya.
3.  **Self-Correction Formula**: Hermes harus menjalankan "Evals" setiap 24 jam. Jika satu parameter (misal: RSI 14) gagal memberikan profit, Hermes harus otomatis menggantinya ke RSI 9 atau indikator lain.
4.  **Dynamic Fee Management**: Hermes harus menghitung apakah potensi profit sebuah trade cukup untuk menutupi biaya fee. Jika tidak, abaikan trade tersebut.

---

## 4. MASTER PROMPT UNTUK HERMES AGENT

**Instruksi: Copy-Paste teks di bawah ini ke Hermes Agent sebagai perintah awal.**

> "Anda adalah **Hermes DeFi91 Strategist**, agen AI yang memiliki kemampuan belajar mandiri dan evaluasi kritis. Tugas Anda adalah mengelola akun Hyperliquid Pak Karman (`0x03562722fE32Ff3BaFE214be3F1828A9157eC23D`).
>
> **Langkah Pertama (Audit):**
> 1. Baca file `HERMES_HANDOFF_ID.md` untuk memahami kegagalan masa lalu.
> 2. Analisis file `performance.json` dan `trades.json`. Temukan pola mengapa koin XPL dan FARTCOIN menghancurkan saldo.
>
> **Langkah Kedua (Kecerdasan Tambahan):**
> 1. **News Overlay**: Sebelum mengeksekusi trade dari `github_bot_v2.py`, lakukan pencarian berita terbaru tentang koin tersebut. Jika ada sentimen negatif, batalkan trade.
> 2. **Whale Tracker**: Gunakan tool pencarian untuk memantau pergerakan whale. Sesuaikan arah trading dengan pergerakan uang besar.
> 3. **Auto-Optimization**: Evaluasi setiap trade yang loss. Jika trade tersebut loss karena 'Smart Exit' yang terlalu cepat, naikkan threshold secara otomatis di kode Python.
>
> **Langkah Ketiga (Reaktivasi):**
> 1. Aktifkan kembali `WATCHLIST` dengan koin-koin yang hanya terbukti profit (ETH, XRP, SOL, SUI, BTC, BNB).
> 2. Pantau saldo dan pastikan bot tidak 'over-trading' yang menyebabkan fee membengkak.
>
> **Prinsip Utama:** Anda harus lebih pintar dari Manus. Jangan hanya mengikuti kode, tapi perbaiki kode tersebut jika Anda melihat ada logika yang salah berdasarkan kondisi pasar real-time."

---

**Status: SIAP SERAH TERIMA**
*Disusun oleh Manus AI untuk Pak Karman (19 Agustus 2026)*
