# Katalog Ide Bot DeFi91 untuk Evaluasi Hermes

**Status dokumen:** Bahan eksplorasi dan proposal; **bukan instruksi aktivasi live**.  
**Kondisi operasi:** Scalping dan Grid Bot saat ini dipasang dalam mode *Safety Circuit Breaker*. Tidak ada bot yang boleh diaktifkan, posisi dikelola, atau key dipindahkan sebelum Hermes menyampaikan proposal dan Pak Karman memberi persetujuan tertulis.

> **Tujuan ekosistem bukan sekadar “lebih banyak bot”.** Sistem yang baik memisahkan mesin pencari peluang, mesin penyaring risiko, mesin eksekusi, dan mesin evaluasi. Bot strategi baru tidak boleh langsung live hanya karena idenya menarik.

---

## 1. Konteks: Apa yang Pernah Dibangun

Ekosistem awal DeFi91 mempunyai dua mesin eksekusi: **scalping berbasis CVD/order flow + RSI/MACD** dan **Grid berbasis ATR**. Scalping mencetak skor gabungan dari order flow, order book, funding, RSI, MACD, serta posisi harga dalam range. Grid ditempatkan untuk kondisi NEUTRAL/CHOPSAW. [1] [2]

Pengalaman sebelumnya menunjukkan masalah utama bukan kekurangan sinyal, melainkan **biaya transaksi yang menggerus trade kecil**, pengelolaan posisi yang terlalu reaktif, dan pengaktifan strategi tanpa pengaman operasional yang memadai. Grid juga belum terbukti menghasilkan trade yang berguna pada modal kecil. [1] [3]

Karena itu, Hermes harus memprioritaskan bot yang **mengurangi keputusan buruk** lebih dahulu, sebelum menambah bot yang membuka lebih banyak order.

---

## 2. Arsitektur yang Disarankan: Empat Lapisan

| Lapisan | Peran | Boleh mengirim order? | Contoh bot |
|---|---|---:|---|
| **Intelligence** | Mengumpulkan data market dan konteks | Tidak | News Sentinel, Whale Tracker, Liquidation/Funding Monitor |
| **Decision Gate** | Menilai kualitas sinyal dan mengizinkan/menolak entry | Tidak langsung | Trade Quality Gate, Regime Router, Risk Governor |
| **Execution** | Menempatkan dan mengelola order | Ya, setelah gate menyetujui | Scalping, Trend Breakout, Grid |
| **Learning & Audit** | Merekam hasil dan mengevaluasi hipotesis | Tidak | Evaluator, Parameter Lab, Telegram Audit Reporter |

> **Aturan desain:** Tidak ada strategi eksekusi yang boleh memiliki hak mutlak untuk trading. Semua entry harus melewati Decision Gate dan Risk Governor.

---

# 3. Katalog Jenis Bot

## 3.1. Bot 1 — Scalping Order-Flow / Momentum (Penyempurnaan Bot Lama)

**Status:** Sudah ada, tetapi harus dianggap sebagai prototipe yang perlu diaudit ulang.

Bot ini menggabungkan CVD dari recent trades, rasio bid/ask dari order book, funding rate, RSI, MACD, dan support/resistance. Konsep asalnya adalah menemukan akumulasi/tekanan beli-jual lalu meminta konfirmasi momentum sebelum entry. [1]

| Komponen | Rancangan historis | Masalah yang perlu diuji Hermes |
|---|---|---|
| Sinyal | Skor -12 hingga +12 | Apakah komponen independen atau sebenarnya menghitung informasi yang sama dua kali? |
| Entry | Ambang ±4 | Terlalu longgar untuk biaya dan noise 15 menit? |
| Exit | TP 2%, SL 1.5%, smart-exit | Validasi apakah order reduce-only TP/SL benar-benar terbentuk dan sesuai risiko akun |
| Sizing | Margin nominal $3 | Nominal tetap tidak cocok untuk semua equity dan volatilitas |

**Upgrade yang harus dipertimbangkan Hermes:** gunakan *multi-timeframe alignment*, volume filter, spread/slippage filter, dan *minimum expected value after fees*. Scalping hanya boleh entry ketika potensi target bersih sesudah taker/maker fee masih memadai.

---

## 3.2. Bot 2 — Market Regime Router

**Status:** Sebagian sudah ada dalam `market_regime_filter.py`; perlu dinaikkan menjadi “pengarah strategi”, bukan sekadar badge.

Bot ini tidak trading. Ia mengklasifikasikan market sebagai `TRENDING`, `NEUTRAL`, atau `CHOPSAW` dengan ATR, ADX, dan Bollinger Band Width. [1]

| Regime | Aksi yang layak diuji | Aksi yang sebaiknya dilarang |
|---|---|---|
| TRENDING | Trend-following atau breakout setelah pullback | Grid mean reversion tanpa batas risiko |
| NEUTRAL | Mean reversion ketat, range trading | Mengejar candle breakout tanpa volume |
| CHOPSAW | Hampir semua eksekusi dihentikan atau ukuran diperkecil | Scalping frekuensi tinggi dan Grid agresif |
| EVENT RISK | Mode aman penuh | Semua entry baru |

**Nilai tambah:** Regime Router menentukan strategi mana yang *eligible*. Ini menghilangkan kesalahan lama ketika bot dibuat tetap agresif pada CHOPSAW hanya agar tidak idle.

---

## 3.3. Bot 3 — News & Event-Risk Sentinel

**Status:** Ide prioritas tinggi, **monitoring-only terlebih dahulu**.

Bot ini memantau berita crypto makro dan aset tertentu, pengumuman exchange, data ekonomi berdampak tinggi, gangguan jaringan, exploit, listing/delisting, serta headline regulasi. Output awalnya harus berupa status risiko: `NORMAL`, `CAUTION`, atau `HALT`.

| Input | Keluaran | Aturan awal yang aman |
|---|---|---|
| Berita kredibel dan kalender event | Sentiment/event score | Tidak membuka trade baru saat status `HALT` |
| Volatilitas mendadak | Alert Telegram | Mewajibkan re-check sinyal setelah event |
| Berita aset spesifik | Larangan pair sementara | Hindari mengandalkan headline tunggal |

Bot ini **bukan mesin pembaca berita yang otomatis buy/sell**. Fungsi yang realistis adalah mencegah entry teknikal saat ada risiko event yang tidak tertangkap indikator historis. Ide News Sentiment memang menjadi bagian eksplorasi Hermes sebelumnya. [1] [2]

---

## 3.4. Bot 4 — Whale / Smart-Money Tracker

**Status:** Ide prioritas menengah; awalnya hanya alert dan feature, bukan copy-trade.

Tracker memantau perubahan posisi akun besar yang dapat diobservasi, aliran dana, perubahan open interest, perpindahan ke exchange, serta posisi vault/leader bila datanya tersedia dan dapat diverifikasi. Tujuannya bukan meniru whale secara membabi buta, tetapi memberi konteks untuk sinyal yang sudah ada.

| Sinyal tracker | Penggunaan yang benar | Risiko jika salah pakai |
|---|---|---|
| Akumulasi posisi besar | Tambahkan konfirmasi bila searah sinyal dan data konsisten | Whale bisa hedging; arah posisi saja dapat menyesatkan |
| Perubahan cepat OI/volume | Tandai kemungkinan squeeze atau breakout | Mengira OI naik selalu bullish |
| Transfer besar | Naikkan kewaspadaan | Transfer belum tentu bermakna trading |

> **Larangan awal:** Jangan membangun copy-trading otomatis dari top vault/whale. Data dapat terlambat, posisi bisa hedged, dan ukuran akun berbeda jauh dari modal DeFi91.

---

## 3.5. Bot 5 — Liquidation, Funding & Open-Interest Squeeze Monitor

**Status:** Ide prioritas tinggi sebagai lapisan pengaman derivatif.

Bot ini memantau funding rate, perubahan open interest, volatilitas, dan—bila sumber data yang andal tersedia—peta likuidasi. Ia mencari kondisi rawan *long squeeze*, *short squeeze*, atau crowded trade.

| Kondisi | Perlakuan yang perlu diuji | Tujuan |
|---|---|---|
| Funding ekstrem positif + OI naik tajam | Hindari LONG baru; tunggu konfirmasi | Mencegah masuk ke long crowded |
| Funding ekstrem negatif + OI naik tajam | Hindari SHORT baru; tunggu konfirmasi | Mencegah masuk ke short crowded |
| Harga bergerak tajam menuju area likuidasi | Alert / ukuran dikurangi | Mengurangi risiko stop tersapu |
| Funding netral dan OI sehat | Sinyal biasa boleh dievaluasi | Tidak memaksakan interpretasi |

Funding sudah dipakai dalam skor lama, tetapi hanya sebagai komponen kecil. Hermes dapat mengevaluasi apakah ia lebih efektif sebagai **hard veto** ketimbang sekadar penambah skor. [1]

---

## 3.6. Bot 6 — Trend-Following / Breakout Bot

**Status:** Kandidat strategi eksekusi baru, hanya untuk market TRENDING.

Bot ini tidak mencoba menangkap semua ayunan kecil. Ia menunggu struktur tren, breakout valid, volume relatif yang mendukung, lalu entry pada pullback atau retest. Exit memakai ATR dan struktur pasar, bukan TP/SL persen tetap.

| Elemen | Usulan investigasi Hermes |
|---|---|
| Filter tren | ADX, higher-high/higher-low, moving average slope, atau Donchian channel |
| Konfirmasi breakout | Close candle, volume relatif, perubahan OI, dan spread wajar |
| Entry | Retest/pullback untuk menekan slippage |
| Exit | Stop berdasarkan ATR/struktur; trailing stop setelah R-multiple tertentu |

Jenis ini lebih cocok daripada grid ketika Regime Router menyatakan `TRENDING`. Namun ia tetap membutuhkan validasi out-of-sample dan penghitungan fee.

---

## 3.7. Bot 7 — Mean-Reversion / Range Bot

**Status:** Kandidat alternatif Grid, bukan pengganti langsung.

Alih-alih memasang enam limit order sekaligus seperti Grid lama, bot ini hanya mengambil satu entry ketika harga menyimpang secara ekstrem dari VWAP atau Bollinger Band dalam pasar yang benar-benar range-bound. Ia wajib memiliki *time stop* dan event-risk veto.

| Perbedaan dari Grid lama | Manfaat potensial |
|---|---|
| Satu posisi selektif, bukan banyak order berlapis | Margin dan risiko lebih mudah diawasi |
| Tidak memaksa order pada semua kandidat | Mengurangi order tidak efektif pada modal kecil |
| Kondisi range harus dikonfirmasi | Mengurangi bahaya saat range berubah menjadi tren |

Untuk modal kecil, Hermes sebaiknya membuktikan model ini melalui *paper/shadow mode* dahulu. Grid historis belum menunjukkan kontribusi profit yang bisa dijadikan dasar aktivasi. [1] [3]

---

## 3.8. Bot 8 — Grid Bot Versi Baru (Jika dan Hanya Jika Lolos Uji)

**Status:** **Tidak prioritas untuk live kecil**.

Grid lama menggunakan kandidat otomatis, 3 buy + 3 sell, budget nominal $20, dan leverage 5x. Ia pernah tidak menghasilkan order/trade yang berarti karena batas ukuran minimum dan modal yang terlalu kecil. [1] [3]

Jika Hermes tetap mengusulkan Grid, proposal wajib menjawab:

1. Apa minimum equity yang benar-benar membuat six-level grid layak setelah fee?
2. Bagaimana bot membatalkan seluruh order saat regime berubah menjadi TRENDING atau news risk muncul?
3. Bagaimana membatasi inventory satu arah ketika harga menembus range?
4. Berapa kerugian maksimum per grid dan kapan grid *hard-stop*?

Tanpa jawaban kuantitatif dan backtest/paper test, Grid tidak boleh diaktifkan.

---

## 3.9. Bot 9 — Funding / Basis Arbitrage Monitor

**Status:** Riset, bukan live execution awal.

Ide ini mencari perbedaan funding atau basis spot-perpetual yang cukup besar untuk menutup fee dan risiko. Secara konsep, posisi long/short yang saling mengimbangi dapat mengejar pembayaran funding daripada arah harga.

| Syarat minimum | Alasan |
|---|---|
| Akses spot dan perps yang benar | Tidak boleh salah menganggap saldo/collateral sudah terpadu |
| Penghitungan fee, funding, basis, dan slippage | Spread nominal sering habis oleh biaya |
| Hedge ratio dan rebalancing | Hedging yang tidak sinkron menciptakan directional risk |
| Modal cukup | Ukuran terlalu kecil mungkin tidak menutup biaya |

Ini menjanjikan stabilitas teori, tetapi kompleksitas operasionalnya tinggi. Hermes sebaiknya hanya membuat **dashboard peluang** terlebih dahulu.

---

## 3.10. Bot 10 — Trade Quality Gate / Meta-Labeling

**Status:** **Prioritas tertinggi** untuk dibangun sebelum strategi baru live.

Ini bukan strategi arah pasar. Ia menerima kandidat trade dari Scalping/Breakout/Mean Reversion lalu mengeluarkan keputusan `ALLOW`, `REDUCE`, atau `REJECT` berdasarkan kondisi biaya, volatilitas, news risk, funding/OI, kualitas likuiditas, korelasi posisi, dan riwayat setup serupa.

| Pertanyaan gate | Contoh keputusan |
|---|---|
| Apakah target netto sesudah fee realistis? | Reject jika TP terlalu dekat terhadap fee/slippage |
| Apakah ada berita/event besar? | Halt entry baru |
| Apakah dua posisi yang ingin dibuka sangat berkorelasi? | Reduce atau pilih satu saja |
| Apakah setup ini punya sampel historis memadai? | Paper mode atau ukuran minimum |
| Apakah stop loss melebihi batas risiko account? | Reject |

Bot ini menjawab masalah inti DeFi91: **lebih banyak entry bukan berarti recovery lebih cepat**.

---

## 3.11. Bot 11 — Risk Governor & Portfolio Exposure Manager

**Status:** **Wajib sebelum bot eksekusi diaktifkan.**

Risk Governor mengawasi seluruh strategi, posisi, order, margin, korelasi, kerugian harian, dan status sistem. Ia satu-satunya komponen yang dapat memberi izin eksekusi.

| Guardrail yang harus menjadi proposal Hermes | Contoh bukan angka final |
|---|---|
| Risiko per trade | Ditetapkan dalam % equity dan diverifikasi dari jarak stop aktual |
| Batas kerugian harian | Mode `HALT` setelah batas tercapai |
| Batas eksposur korelatif | Jangan LONG BTC + ETH + SOL bersamaan seolah tiga risiko independen |
| Batas jumlah posisi/order | Memperhitungkan order TP/SL dan order grid |
| Cooldown setelah loss beruntun | Menghindari revenge-trading algoritmik |
| Kill switch | Pak Karman dapat mematikan eksekusi tanpa mengubah strategi |

Ini harus menggantikan pendekatan lama yang berfokus pada margin nominal $3 dan `MAX_OPEN_POSITIONS` saja. [1] [3]

---

## 3.12. Bot 12 — Evaluator & Parameter Laboratory (Self-Evaluation)

**Status:** **Wajib, tetapi tidak boleh langsung memutasi live strategy.**

Evaluator melakukan analisis per setup: arah, regime, skor, fitur, fee, slippage, holding time, MFE/MAE, alasan exit, dan hasil bersih. Ia mencari apakah trade menguntungkan setelah fee dan apakah performa konsisten di luar sampel.

| Output | Fungsi |
|---|---|
| Trade journal terstruktur | Membuat kegagalan dapat diaudit |
| Laporan harian/mingguan | Menjelaskan PnL bersih, fee, dan penyebab loss |
| Parameter candidates | Mengusulkan, bukan langsung menerapkan, threshold/TP/SL baru |
| Shadow test | Membandingkan strategi lama dan kandidat baru tanpa uang riil |
| Change log | Semua mutasi formula memiliki alasan, data, dan persetujuan |

**Aturan fundamental:** Hermes boleh mengusulkan formula baru, tetapi perubahan parameter live memerlukan: hipotesis → backtest/forward shadow → laporan → persetujuan Pak Karman → rollout kecil → evaluasi.

---

## 3.13. Bot 13 — Telegram Command & Audit Reporter

**Status:** Prioritas tinggi untuk kontrol operasional, tetapi bukan bot trading.

Bot ini menjadikan Telegram pusat monitoring. Ia dapat mengirim ringkasan saldo, posisi, exposure, trade proposal, alasan entry, kualitas sinyal, event-risk status, dan laporan evaluasi. Ia juga menerima perintah yang aman, misalnya `/status`, `/pause`, dan `/resume` dengan otorisasi terbatas.

Perintah yang mengubah order atau mengaktifkan live trading harus meminta konfirmasi eksplisit dan mencatat audit trail.

---

# 4. Prioritas Rekomendasi untuk Hermes

| Urutan | Komponen | Alasan | Mode awal |
|---:|---|---|---|
| 0 | Audit akses, saldo, posisi, dan data | Dasar keamanan dan angka yang benar | Read-only |
| 1 | Risk Governor + Kill Switch | Mencegah pengulangan insiden eksekusi tidak diinginkan | Enforcement |
| 2 | Trade Quality Gate | Menekan fee attrition dan entry noise | Shadow → veto |
| 3 | Evaluator + jurnal terstruktur | Memisahkan opini dari bukti | Read-only |
| 4 | News/Event Sentinel + Derivatives Monitor | Menambahkan konteks yang tidak ada di indikator harga | Alert → veto |
| 5 | Penyempurnaan Scalping | Memperbaiki strategi yang sudah dikenal setelah gate ada | Shadow → kecil |
| 6 | Trend Breakout atau Mean Reversion | Hanya satu kandidat dieksekusi sesuai regime | Shadow → kecil |
| 7 | Whale tracker | Feature tambahan, bukan sumber keputusan tunggal | Alert-only |
| 8 | Grid atau arbitrage | Kompleks/kurang terbukti pada modal kecil | Riset/dashboard |

---

# 5. Fase Eksplorasi yang Wajib Dilakukan Hermes

Hermes harus mengirim **Proposal Strategis** sebelum Pak Karman mendepositkan modal baru. Proposal tidak boleh berhenti pada daftar indikator. Ia harus menjawab hal berikut.

1. **Data:** Data apa yang tersedia, mana yang real-time, mana yang terlambat, dan mana yang tidak cukup untuk klaim whale/news?
2. **Hipotesis:** Mengapa setup tertentu diperkirakan memiliki expected value positif setelah fee dan slippage?
3. **Validasi:** Berapa jumlah sampel, periode test, metode out-of-sample, dan hasil shadow test yang diperlukan?
4. **Risiko:** Berapa risiko maksimum per trade/hari dan skenario terburuk yang masih dapat diterima?
5. **Eksekusi:** Bagaimana TP/SL, order reduce-only, cancel-on-regime-change, dan kegagalan API diverifikasi?
6. **Governance:** Perubahan apa yang bisa dilakukan Hermes sendiri, dan perubahan apa yang selalu memerlukan persetujuan Pak Karman?
7. **Keamanan:** Bagaimana key baru dibatasi, disimpan, dan dicabut tanpa memberikan akses ke wallet utama?

---

# 6. Prompt Tambahan untuk Hermes

> Anda menerima katalog ide bot DeFi91 ini sebagai **peta eksplorasi**, bukan perintah membangun semua bot. Lakukan audit terhadap repository dan data Hyperliquid terlebih dahulu. Nilai setiap ide berdasarkan data yang dapat diperoleh, biaya, kebutuhan modal, risiko eksekusi, dan kemampuan divalidasi. 
>
> Susun proposal dalam urutan: (1) safety/risk governor, (2) monitoring dan evaluator, (3) satu strategi eksekusi yang paling layak untuk diuji dalam shadow mode. Jelaskan ide yang Anda tolak beserta alasannya. Jangan membuat, mengubah, atau mengaktifkan transaksi sampai Pak Karman menyetujui proposal tertulis dan memasukkan saldo baru.

---

## Referensi Internal

[1]: ./HERMES_HANDOFF.md "DeFi91 Trading Bot — Master Handoff"
[2]: ./HERMES_MASTER_HANDOFF.md "DeFi91 Master Strategy & Strategic Handoff"
[3]: ./HANDOFF_SECURITY_AUDIT_2026-08-19.md "Audit Keamanan & Serah-Terima DeFi91 ke Hermes"

*Disusun ulang dari catatan sesi DeFi91. Tidak ada bot dalam dokumen ini yang menjanjikan profit atau layak langsung diaktifkan tanpa validasi.*
