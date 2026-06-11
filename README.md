# DeFi91 Trading Bot Ecosystem
Strategi Almarhum Doddy Ali Wijaya + KJo Academy dengan Dashboard Web Real-time

## Fitur Utama
Ekosistem ini sekarang memiliki **2 Bot Strategi** yang berjalan pada 1 akun Hyperliquid yang sama, saling melengkapi berdasarkan kondisi pasar:

1. **Scalping Bot (`github_bot_v2.py`)**
   - Aktif saat pasar **TRENDING**
   - Menggunakan indikator CVD (Order Flow), RSI, dan MACD
   - Margin $5 per trade, agresif mencari profit cepat

2. **Grid Trading Bot (`grid_bot.py`)**
   - Aktif saat pasar **SIDEWAYS / CHOPSAW**
   - Memanfaatkan volatilitas harga dalam rentang tertentu
   - Budget terpisah ($25), otomatis rebalance jika harga keluar jalur

## Manajemen Saldo (1 Akun)
- **Scalping Bot**: Menggunakan margin per trade
- **Grid Bot**: Menggunakan alokasi budget khusus
- **Safety Buffer**: Bot akan berhenti membuka posisi baru jika saldo turun di bawah batas aman ($20)

## Otomatisasi
- Berjalan otomatis via GitHub Actions (11 sesi per hari)
- Laporan harian dan sinyal real-time via Telegram
- Dashboard web update otomatis
