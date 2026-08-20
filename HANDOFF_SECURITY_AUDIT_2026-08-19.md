# Audit Keamanan & Serah-Terima DeFi91 ke Hermes

**Tanggal audit:** 19 Agustus 2026  
**Wallet:** `0x03562722fE32Ff3BaFE214be3F1828A9157eC23D`  
**Repository:** [`astrorawak/defi91-trading-bot`](https://github.com/astrorawak/defi91-trading-bot)  
**Tujuan:** Mendokumentasikan insiden posisi pukul 14:40 WIB, menghentikan otomasi secara aman, serta menetapkan batas akses sebelum pengambilalihan Hermes.

> **Pernyataan transparansi:** Angka dan kesimpulan dokumen ini hanya memakai bukti yang dapat diverifikasi dari log GitHub Actions, source code repository, dan endpoint informasi publik Hyperliquid. Nilai private key maupun nilai secret GitHub tidak pernah dibaca atau dicantumkan.

---

## Ringkasan Eksekutif

Pada **19 Agustus 2026 pukul 14:40:31 WIB** (`07:40:31 UTC`), workflow GitHub Actions **DeFi91 Trading Bot** berjalan dengan event `schedule` pada commit `f8d8cf4`. Log eksekusi membuktikan bahwa **scalping bot DeFi91 membuka tiga posisi** dengan spesifikasi yang persis sama dengan posisi yang dipertanyakan. Posisi tersebut **bukan** berasal dari Grid Bot.

Ini bukan tindakan trading manual yang dilakukan di luar sistem. Penyebab langsungnya adalah konfigurasi scalping pada commit tersebut masih berisi watchlist aktif dan workflow menerima secret `HYPERLIQUID_PRIVATE_KEY`. Workflow jadwal dapat mengalami keterlambatan dari waktu cron yang dikonfigurasi; run ini adalah event `schedule`, bukan event dari Hermes.

Sebagai containment, commit [`5c5f4dc`](https://github.com/astrorawak/defi91-trading-bot/commit/5c5f4dc) memasang **Safety Circuit Breaker** pada scalping dan Grid Bot. Kedua bot kini berhenti sebelum memuat key, melakukan kueri posisi, memperbarui data, membuat, menutup, atau mengelola order. Tiga posisi yang sudah terbuka **tidak disentuh** oleh containment ini.

---

# A. Klarifikasi Posisi Pukul 14:40–14:41 WIB

## A.1. Jawaban langsung

**Ya. Ketiga posisi dibuka oleh kode scalping DeFi91 yang dijalankan melalui GitHub Actions, bukan Grid Bot dan bukan Hermes.** Secara operasional, ini adalah tanggung jawab sistem yang sebelumnya saya kelola karena konfigurasi yang saya commit pada `af2608d` mengaktifkan kembali watchlist; selanjutnya workflow terjadwal mengeksekusinya. Saya seharusnya tidak menyatakan bot aman/off sebelum memastikan commit aktif dan jadwal workflow tidak dapat membuka transaksi baru. Itu adalah kesalahan proses yang harus dicatat secara terbuka.

| Posisi | Bukti log GitHub Actions | Konfigurasi yang digunakan |
|---|---|---|
| BTC SHORT | Filled `0.00093` pada `$64,368.0` | Margin `$3`, leverage `20x`, TP `$63,081`, SL `$65,334` |
| XRP SHORT | Filled `60` pada `$1.0056` | Margin `$3`, leverage `20x`, TP `$0.9855`, SL `$1.021` |
| SUI LONG | Filled `45.7` pada `$0.65685` | Margin `$3`, leverage `10x`, TP `$0.670`, SL `$0.647` |

Bukti run dapat dibuka pada [GitHub Actions run `32228922037`](https://github.com/astrorawak/defi91-trading-bot/actions/runs/32228922037). Log mencatat `Trades executed: 3`. Grid Bot kemudian berjalan, tetapi ringkasannya menunjukkan **`Active orders: 0`** dan **`Total trades: 0`**. Karena itu, Grid Bot tidak membuka tiga posisi tersebut.

## A.2. Mengapa bot aktif saat masa handoff?

Commit `af2608d` pada 19 Agustus 2026 pukul 13:20:40 WIB memulihkan `WATCHLIST` dan mengaktifkan kembali kandidat Grid. Commit tersebut masih menjadi basis source code pada saat run terjadwal pukul 14:40 WIB. Klaim sebelumnya bahwa bot sudah off tidak cocok dengan source code efektif saat workflow berjalan. Audit ini memperbaiki ketidaksesuaian tersebut.

## A.3. Apakah Manus memegang atau mengetahui private key?

Saya **tidak mengetahui, tidak dapat melihat, dan tidak dapat mengekstrak nilai private key**. Pada log Actions, variabel `HYPERLIQUID_PRIVATE_KEY` ditampilkan sebagai nilai tersamarkan. Di lingkungan ini saya tidak memiliki salinan raw private key.

Namun, terdapat **jalur eksekusi tidak langsung**: workflow GitHub Actions memasukkan secret `HYPERLIQUID_PRIVATE_KEY` ke proses bot. Selama secret itu masih tersimpan di GitHub dan workflow masih dapat dijalankan/diubah oleh pihak yang memiliki akses repository, key tersebut tetap dapat dipakai oleh workflow untuk menandatangani order. Ini harus dianggap sebagai risiko akses sampai key lama dicabut atau diganti.

---

# B. Serah-Terima Akses Wallet

## B.1. Prinsip kepemilikan yang direkomendasikan

Setelah handoff, **Pak Karman harus menjadi satu-satunya pemegang material key**. Hermes tidak seharusnya menerima private key wallet utama secara langsung. Gunakan key trading/agent yang dibatasi kewenangannya jika Hyperliquid pada konfigurasi akun tersebut mendukungnya; wallet utama tetap hanya pada Pak Karman.

| Komponen | Kondisi saat audit | Tindakan yang direkomendasikan sebelum aktivasi Hermes |
|---|---|---|
| Private key lama | Tersimpan sebagai GitHub Actions secret menurut source workflow; nilainya tidak terlihat dari audit ini | **Rotasi/cabut**. Jangan meneruskan key lama melalui chat, dokumen, atau repository. |
| GitHub Actions | Masih memiliki workflow terjadwal | Circuit breaker sudah dipasang, tetapi secret lama harus dihapus dari GitHub setelah key baru siap. |
| Hermes | Belum diberi key untuk eksekusi | Masukkan key trading baru hanya sebagai environment secret Hermes setelah proposal disetujui. |
| Wallet utama | Tidak boleh dibagikan | Simpan offline pada Pak Karman; gunakan agent/API wallet dengan izin paling minimum bila tersedia. |
| Telegram | Dikonfigurasi lewat secret pada workflow lama | Rotasi token Telegram sebelum aktivasi Hermes; masukkan token baru hanya ke environment Hermes. |

## B.2. Status tindakan Manus

Saya telah memasang circuit breaker pada commit `5c5f4dc`. Ia memastikan scalping dan Grid Bot tidak melakukan tindakan apa pun, termasuk menutup posisi, ketika watchlist kosong. Saya **tidak akan membuka posisi baru, menutup posisi, mengubah order, atau mengaktifkan ulang bot** pada wallet ini.

Saya tidak dapat menghapus secret GitHub dari lingkungan ini karena akses API yang tersedia menolak operasi secrets dengan `HTTP 403: Resource not accessible by integration`. Karena itu, penghapusan/rotasi secret harus dilakukan oleh pemilik repository melalui GitHub, atau oleh Hermes setelah Pak Karman memberikan kredensial baru secara privat.

## B.3. Prosedur serah-terima yang aman

1. Jangan mengirim private key lama kepada Hermes melalui chat.
2. Buat key trading/agent baru yang hanya dapat digunakan untuk trading dan bukan untuk memindahkan aset, bila mekanisme akun Hyperliquid memungkinkan.
3. Simpan key baru langsung sebagai secret environment Hermes; jangan pernah commit ke repository.
4. Setelah Hermes siap, hapus/revoke `HYPERLIQUID_PRIVATE_KEY` lama dari GitHub Actions dan cabut akses agent lama pada akun Hyperliquid.
5. Rotasi token Telegram, lalu hapus token lama dari GitHub dan masukkan token baru hanya ke Hermes.
6. Jalankan dry-run tanpa key terlebih dahulu; aktivasi live membutuhkan persetujuan eksplisit Pak Karman setelah proposal Hermes diterima.

Hyperliquid mendokumentasikan perpindahan dana Spot–Perp sebagai operasi terpisah; jangan mengasumsikan dua angka saldo dari endpoint berbeda dapat dijumlahkan tanpa terlebih dahulu memeriksa mode akun dan lokasi collateral. [1] [2]

---

# C. Serah-Terima Logika Bot

## C.1. File utama dan fungsi

| File | Fungsi | Status setelah containment |
|---|---|---|
| `github_bot_v2.py` | Scalping: sinyal, eksekusi, TP/SL, smart exit, trailing stop | OFF total melalui `WATCHLIST = []` dan early return |
| `bot_final.py` | Salinan sinkron `github_bot_v2.py` | OFF total |
| `grid_bot.py` | Grid ATR-based | OFF total melalui `GRID_CANDIDATES = []` dan early exit |
| `market_regime_filter.py` | Klasifikasi TRENDING / NEUTRAL / CHOPSAW | Tidak digunakan selama bot OFF |
| `telegram_signals.py` | Sinyal buka/tutup posisi Telegram | Tidak digunakan selama bot OFF |
| `telegram_reporter.py` | Laporan harian Telegram | Perlu diaudit Hermes sebelum dipakai |
| `weekly_insights.py` | Laporan mingguan | Perlu diaudit Hermes sebelum dipakai |
| `optimize_params.py` | Eksperimen parameter | Tidak boleh mengubah live config tanpa proposal dan persetujuan |
| `.github/workflows/trading_workflow_v2.yml` | Jadwal/eksekusi GitHub Actions | Masih ada; source bot kini circuit-breaker |

## C.2. Strategi scalping historis yang aktif saat insiden

Strategi lama adalah skor gabungan **Order Flow/CVD** dan **technical momentum**. Ini bukan validasi bahwa strategi tersebut layak diteruskan; Hermes wajib menilai ulang dengan data yang benar.

| Lapisan | Input | Bobot skor | Logika ringkas |
|---|---|---:|---|
| CVD/order flow | Rasio volume buy/sell dari recent trades | ±3 | Rasio buy >65% memberi +3; <35% memberi -3 |
| L2 order book | Bid/ask dari 10 level teratas | ±2 | Bid-heavy memberi skor bullish; ask-heavy bearish |
| Funding rate | `metaAndAssetCtxs` Hyperliquid | ±2 | Dibaca kontrarian ketika funding ekstrem |
| RSI | 50 candle 15 menit | ±2 | Oversold bullish; overbought bearish |
| MACD | Candle 15 menit | ±2 | Konfirmasi momentum/cross |
| Support/resistance | Posisi harga dalam range 20 candle | ±1 | Dekat support bullish; resistance bearish |

Skor gabungan berada pada rentang teoritis **-12 hingga +12**. Konfigurasi historis membuka LONG jika skor ≥ `+4` dan SHORT jika skor ≤ `-4`. Parameter yang aktif ketika insiden adalah margin `$3` per posisi; leverage target `20x` (dibatasi maksimum aset: SUI `10x`); TP `2.0%`; SL `1.5%`; maksimum 4 posisi. Smart exit diatur pada skor berlawanan `7`, dengan trailing break-even pada profit `0.8%` dan profit lock pada `1.5%`.

> **Catatan kritis untuk Hermes:** source lama menghitung `available` dengan mengambil saldo dari `spotClearinghouseState`, lalu mengurangkan `totalMarginUsed` dari `clearinghouseState`. Kode ini mengasumsikan model “unified account” tanpa mendeteksi mode akun Hyperliquid. Hermes wajib memverifikasi model collateral sebenarnya dan menulis test sebelum memakai rumus sizing ini. Jangan menerima komentar source code sebagai fakta rekening.

## C.3. Grid Bot historis

Konfigurasi lama memakai kandidat `ETH`, `XRP`, `SOL`, `SUI`, `BNB`, dan `VVV`; maksimal 3 pair; 3 level buy dan 3 level sell per pair; leverage `5x`; budget nominal `$20`; dan range berdasarkan `1.5 × ATR`. Grid dimaksudkan aktif di NEUTRAL/CHOPSAW.

Pada run insiden, Grid Bot memang melihat CHOPSAW dan memindai kandidat, tetapi **tidak menaruh order dan tidak menghasilkan trade**. Karena modal kecil dan parameter minimum order, Grid Bot belum terbukti efektif. Hermes harus memperlakukan Grid sebagai kandidat yang perlu diuji ulang, bukan strategi yang sudah tervalidasi.

## C.4. Secret/integrasi yang harus diaudit dan dipindahkan

Source workflow mereferensikan empat environment secret: `HYPERLIQUID_ADDRESS`, `HYPERLIQUID_PRIVATE_KEY`, `TELEGRAM_BOT_TOKEN`, dan `TELEGRAM_CHAT_ID`. Tidak ditemukan RPC key atau webhook trading tambahan di source yang diaudit.

Semua secret lama harus dianggap perlu rotasi. Nilai secret tidak ada dalam dokumentasi ini dan tidak boleh dipindahkan lewat chat.

## C.5. Dokumen yang wajib dibaca Hermes

1. `HERMES_MASTER_HANDOFF.md` — konteks strategi dan fase eksplorasi.
2. `HERMES_HANDOFF_ID.md` — konteks historis; **gunakan sebagai bahan audit, bukan sumber angka final tanpa verifikasi**.
3. `HANDOFF_SECURITY_AUDIT_2026-08-19.md` — dokumen ini; menjadi catatan koreksi resmi atas insiden 14:40 WIB.
4. `trades.json`, `performance.json`, `grid_trades.json`, dan log Actions — perlu direkonsiliasi dengan fills Hyperliquid sebelum Hermes menyimpulkan performa.

---

# D. Status Dana dan Transfer

## D.1. Snapshot yang benar-benar terlihat saat audit

Audit pada **19 Agustus 2026 pukul 14:58:59 WIB** (`07:58:59 UTC`) menampilkan data berikut.

| Endpoint | Nilai yang dilaporkan | Arti terbatas |
|---|---:|---|
| `spotClearinghouseState` | USDC total `$19.1814811`; hold `$14.995832` | Saldo yang dilaporkan endpoint spot pada saat audit |
| `clearinghouseState.marginSummary` | Account value `$15.253507`; total margin used `$8.998155` | Nilai account/margin perps pada saat audit |
| Posisi terbuka | 3 posisi | BTC SHORT, XRP SHORT, SUI LONG sebagaimana pada Bagian A |
| Order terbuka | 6 order reduce-only | Pasangan TP dan SL untuk tiga posisi, bukan order Grid |

Saya **tidak menyatakan total dana sebagai penjumlahan `$19.1814811 + $15.253507`**, karena kedua nilai berasal dari endpoint/kelas akun berbeda dan source bot sendiri memiliki asumsi collateral yang belum diverifikasi. Pernyataan “total dana seharusnya ±$19” konsisten dengan transfer masuk terbaru sebesar `$19.017621`, tetapi menentukan total portofolio/ada-tidaknya dana keluar memerlukan rekonsiliasi mode akun dan seluruh ledger yang dilakukan Hermes sebelum deposit baru.

## D.2. Bukti transfer paling baru

Ledger Hyperliquid menunjukkan sebuah **transfer masuk** pada **19 Agustus 2026 pukul 14:33:27 WIB** (`07:33:27 UTC`) sebesar `$19.017621` USDC dari alamat `0x6b9e...0a24` menuju wallet DeFi91. Ini terjadi sekitar tujuh menit sebelum workflow membuka posisi. Transfer ini bukan penarikan dari wallet DeFi91.

## D.3. Penarikan dan tujuan

Endpoint `userNonFundingLedgerUpdates` mengembalikan 178 catatan ledger. Catatan penarikan terbaru yang muncul di respons tersebut adalah **6 Juni 2026: `$35.00` USDC dengan fee `$1.00`**. Respons endpoint menyertakan hash penarikan, tetapi **tidak menyertakan alamat tujuan withdrawal**. Karena itu, saya tidak akan mengarang alamat penerima.

File pendukung `defi91_transfer_audit.md` melampirkan hash dan nilai seluruh record penarikan/transfer yang dikembalikan endpoint. Untuk mengetahui tujuan setiap withdrawal, Hermes/Pak Karman harus menelusuri setiap hash di explorer chain yang sesuai dan mencocokkannya dengan riwayat wallet. Ini adalah batas verifikasi yang jujur dari data API yang tersedia. [3]

---

# E. Komitmen Operasional

> **Mulai 19 Agustus 2026, saya berhenti mengoperasikan dan membuka posisi apa pun pada wallet DeFi91, dan menyerahkan kendali penuh kepada Pak Karman via Hermes.**

Komitmen ini berlaku pada tindakan operasional saya dan kode yang saya kelola. Untuk menjadikan kontrol benar-benar eksklusif secara teknis, Pak Karman perlu mencabut/merotasi secret private key lama di GitHub dan memakai key trading baru yang hanya diletakkan pada environment Hermes setelah proposal Hermes disetujui.

---

## Checklist Wajib Sebelum Aktivasi Hermes

| Status | Langkah |
|---|---|
| ✅ | Containment sudah dipush: commit `5c5f4dc`; bot tidak membuka/menutup/mengelola posisi. |
| ⬜ | Pak Karman mengelola sendiri tiga posisi dan enam TP/SL reduce-only yang sudah ada. |
| ⬜ | Hermes mengaudit account mode, sizing, dan data fills sebelum menyarankan strategi. |
| ⬜ | Hermes mengajukan proposal tertulis; Pak Karman menyetujui. |
| ⬜ | Key trading baru dibuat dan dimasukkan privat ke environment Hermes. |
| ⬜ | Secret lama GitHub dan token Telegram lama dicabut/dirotasi. |
| ⬜ | Dry-run berhasil; baru live activation dengan persetujuan eksplisit Pak Karman. |

---

## Referensi

[1]: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes "Hyperliquid — Account abstraction modes"
[2]: https://docs.chainstack.com/reference/hyperliquid-exchange-spot-perp-transfer "Hyperliquid — Spot ↔ Perp transfer"
[3]: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals "Hyperliquid — Info endpoint: funding and non-funding ledger updates"

*Disusun oleh Manus AI sebagai catatan audit teknis. Bukan nasihat investasi berlisensi; keputusan mengelola/menutup posisi tetap berada pada Pak Karman.*
