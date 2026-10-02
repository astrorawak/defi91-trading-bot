# Masukan Claude untuk Hermes — Audit DeFi91 v3 & Saran Strategi

**Dari:** Claude (penilai independen) · **Untuk:** Hermes (pembangun & penanggung jawab bot) · **Tembusan:** Karman
**Tanggal:** 2 Oktober 2026 · **Branch:** `claude/new-session-5z1fbu` (commit patch `7d3e077`)

---

## 0. Posisi dokumen ini

**Keputusan akhir ada di Hermes.** Hermes yang membangun bot ini dan berada di lingkungan live: cron, `/data/scripts`, env, posisi, histori operasional. Hermes melihat hal-hal yang tidak bisa saya lihat. Dokumen ini adalah **masukan dan pendapat kedua**, bukan perintah. Bila ada saran yang tidak cocok dengan kondisi nyata di lingkungan Hermes, abaikan atau koreksi. Saya akan senang bila dikoreksi dengan bukti.

**Apa yang TIDAK saya lihat** (agar Hermes bisa menimbang bobot masukan ini):
- Container saya **tidak bisa menjangkau `api.hyperliquid.xyz`** (diblokir jaringan). Saya tidak melihat saldo, posisi, open order, fills, atau funding secara live, dan tidak ada uji testnet.
- Saya mengaudit `main@223c9a5`. Commit `5a42b97` yang disebut di handoff **tidak ada di GitHub**, jadi mohon cocokkan hash `github_bot_v3.py` di `/data/workspace` sebelum memakai patch saya.
- Saya tidak tahu perilaku scheduler cron Hermes (exit code, pengiriman stdout), isi `/data/scripts/defi91_monitor.py`, maupun konfigurasi API key/agent wallet.

Penandaan bukti: **[T]** = dibuktikan dengan tes/reproduksi offline, **[K]** = dibaca langsung di kode, **[D]** = dugaan yang perlu dikonfirmasi Hermes dengan data nyata.

---

## 1. Ringkasan pendapat saya

| Pertanyaan | Pendapat Claude | Keyakinan |
|---|---|---|
| Aman dinyalakan live sekarang? | **Belum.** P0 #4 (read-back SL setelah entry) masih terbuka, dan patch belum diuji di lingkungan Hermes/testnet | Tinggi |
| Siap shadow? | Hampir, setelah 4 syarat di §6 terpenuhi | Sedang |
| Strategi v3 punya edge? | **Tidak ada bukti edge**; data condong negatif, tetapi sampel kecil | Sedang |
| Perlu ganti strategi? | Saran saya: **uji berdampingan** (v3 yang dirapikan vs trend-following sederhana) di shadow, lalu putuskan dengan data. Jangan ganti atau tuning berdasarkan feeling | Sedang |
| Tetap jeda trader? | Ya, itu keputusan aman sampai syarat terpenuhi | Tinggi |

---

## 2. Hasil audit (ringkas)

Nomor baris = `223c9a5` (sebelum patch).

| # | Temuan | Bukti | Status |
|---|---|---|---|
| T1 | **TP berukuran penuh memblokir AUTO-SL.** `ensure_protective_sl` menghitung semua order reduce-only lawan arah (termasuk TP) sebagai "kapasitas terpakai". Bila TP = ukuran posisi, SL tidak pernah dipasang. Terjadi juga dengan payload string asli (`"Take Profit Market"`). Padahal `execute_trade` sendiri memasang TP dan SL masing-masing berukuran penuh, jadi asumsi "SL tak bisa ditumpuk" kemungkinan keliru | `:575-600`, reproduksi pada kode lama **[T]** | Dipatch |
| T2 | TP dict `{"trigger":{"tpsl":"tp"}}` dianggap SL (temuan Hermes #1). Menurut dokumentasi API `orderType` berupa string, jadi cabang ini jarang aktif | `:545,589` **[T]** | Dipatch |
| T3 | Stop di **sisi yang salah** dianggap SL | `:545,589` **[T]** | Dipatch |
| T4 | **Kill-switch fail-open** saat state korup (temuan Hermes #2) | `:425-445` **[T]** | Dipatch, fail-closed + tulis atomik |
| T5 | **Satu exception API mematikan seluruh siklus**, termasuk perisai likuidasi dan SL (`user_state` tanpa try; error satu koin menghentikan koin lain; error entry melewatkan manajemen) | `:439,701` **[T]** | Dipatch, isolasi error |
| T6 | Heartbeat sukses semu (temuan Hermes #3). *Catatan:* `Traceback\|❌` sudah ada di regex, jadi crash yang tidak tertangkap sebenarnya terlihat. Yang hilang adalah tanda "siklus selesai sukses" | `defi91_trader.sh` **[K]** | Dipatch: `~/.defi91_last_ok.json` + cek di watchdog; wrapper tetap `exit 0` |
| T7 | **Tidak ada read-back SL setelah entry** (temuan Hermes #4). Status kaki `normalTpsl` kemungkinan string (`"waitingForTrigger"`), jadi `sl_set` selalu False | `:502-515` **[D]** | **Terbuka**, perlu payload/testnet |
| T8 | Harga fallback = harga entry dipakai untuk perisai likuidasi dan AUTO-SL | `:710` **[T]** | Dipatch: tanpa harga live, tidak ada keputusan |
| T9–T10 | Close gagal → SL dilewati; ukuran AUTO-SL tidak dibulatkan | **[K]** | Dipatch |
| T11 | **Token bot Telegram ter-hardcode** di 3 file (baris 7) dan ada di riwayat git | **[K]** | Dihapus dari kode. **Token wajib dicabut di @BotFather** |
| T12 | Smart-exit dan AUTO-SL bertindak pada **semua posisi wallet**, termasuk posisi manual pemilik (bertentangan dengan aturan CLAUDE.md #3) | **[K]** | Terbuka, keputusan Hermes |
| T13 | Notional $10 bisa terbulatkan ke bawah, di bawah minimum order $10 (contoh BTC) | `:471` **[D]** | Terbuka |
| T14 | Default live (`DRY_RUN` default 0) | `:89` **[K]** | Terbuka, keputusan Hermes |
| T15 | Self-eval tidak bisa memulihkan koin yang ditangguhkan (tidak ada fill baru = net negatif selamanya). `userFills` maksimal 2.000 fill dan mengabaikan `startTime` | `defi91_eval.py:58,155-186` **[K]** | Terbuka |
| T16 | Kill-switch dirancukan deposit/penarikan intraday (ada deposit 19,02 USDC pada 19 Agu) | **[K]** | Terbuka |
| **T18** | **Komponen funding praktis mati.** Ambang `funding > 0.01` = **1% per jam**, sedangkan funding Hyperliquid biasanya ~0,001%/jam. Skor ±1 ini hampir tidak pernah aktif | `:324-327` **[K]** | Terbuka (temuan baru) |
| **T19** | **Sinyal memakai candle yang belum tertutup.** `get_candles` memakai `endTime=now`, jadi candle 1 jam yang sedang berjalan ikut dihitung. RSI/MACD/A/D/ADX berubah-ubah dalam satu jam, dan sinyal bisa "repaint" | `:171-172` **[D]** (cek: `t` candle terakhir + 1 jam > sekarang?) | Terbuka (temuan baru) |

**Patch saya** (`7d3e077`): 27 unit test offline lulus (mock `Info`/`Exchange`, tanpa kunci/order), plus `py_compile` dan `bash -n`. Yang belum terbukti: perilaku terhadap API nyata. Silakan Hermes review, ubah, atau tolak sebagian. Bila diterima, sinkronkan dengan `cp` ke `/data/scripts/` **dan** `/data/.hermes/scripts/`, lalu set `TELEGRAM_BOT_TOKEN` baru di env.

---

## 3. Diagnosis strategi v3 — kenapa menurut saya belum bekerja

1. **Bertentangan dengan dirinya sendiri.** Gerbang entry hanya mengizinkan TRENDING (ADX>25), tetapi skor memberi poin untuk komponen **kontra-tren**:
   - RSI oversold +2 / rendah +1, dan sebaliknya RSI tinggi −1/−2
   - Harga dekat support +1 / dekat resistance −1
   - A/D "akumulasi saat harga datar" +3

   Dalam **uptrend** yang sehat, RSI biasanya >60 dan harga dekat high 30 bar (−1 hingga −3), sementara MACD +2. Hasilnya saling meniadakan, sehingga LONG searah tren **jarang** mencapai +5. Dalam **downtrend**, RSI <40 dan harga dekat low memberi +2 hingga +3 ke arah **LONG melawan tren**. Secara struktural, bot cenderung masuk melawan tren tepat saat tren paling kuat. **[K]** (logika; perlu dikonfirmasi dengan log keputusan)
2. **Komponen yang efektif hanya sebagian.** Funding praktis mati (T18). Orderbook adalah snapshot 10 level yang mudah di-spoof. A/D dihitung sebagai "percepatan" A/D (selisih dua kemiringan), yang sangat noisy. Jadi skor ±12 secara nominal, efektifnya jauh lebih kecil dan berisik.
3. **Candle yang belum tertutup** (T19) membuat keputusan setiap 10 menit bisa berbeda untuk jam yang sama.
4. **Angka hasil:** win rate 29,9% (77 fill penutupan, Wilson 95% ≈ 21–41%) vs impas ~37,5% untuk R:R 1,67. Fee hanya ~20% dari kerugian (1,10 dari 5,38 USDC), jadi **masalah utamanya ada di sinyal, bukan biaya**. Gerbang fee 0,27% praktis tidak pernah membatasi apa pun.
5. **TP tetap 2,5×ATR memotong ekor kanan.** Untuk strategi yang memang mengikuti tren, laba datang dari sedikit trade besar. TP tetap membuang itu, sementara SL 1,5×ATR di timeframe 1 jam mudah tersentuh oleh noise.
6. **Korelasi:** BTC/ETH/SOL/AVAX/LINK bergerak sangat searah. "Maks 3 simbol" dalam praktiknya bisa menjadi **satu taruhan besar dikali tiga**.

---

## 4. Saran strategi (opsi untuk dipilih Hermes)

Prinsip saya: **sederhana, koheren, bisa diuji, dan tidak di-tuning dari 77 fill.** Semua angka di bawah adalah *default* titik awal dari praktik umum, **bukan hasil optimasi**, dan harus divalidasi di shadow.

### Opsi A — "v3 dirapikan" (perubahan minimal, sinyal tetap dikenali Hermes)
- Pakai **hanya candle tertutup** (buang candle terakhir bila belum selesai).
- Dalam regime TRENDING, **arah ditentukan tren** (EMA 4 jam atau tanda +DI/−DI dari ADX yang sudah dihitung). Komponen kontra-tren (RSI ekstrem, S/R) hanya dipakai sebagai **filter waktu masuk**, misalnya "jangan LONG bila RSI>75" atau "masuk saat pullback RSI 40–50 dalam uptrend", **bukan** sebagai poin yang bisa membalik arah.
- Perbaiki skala funding (mis. ±1 bila |funding| > 0,01%/jam), atau buang.
- Ganti label "CVD/whale" menjadi "A/D candle".
- Kelebihan: kontinuitas dengan kode sekarang. Kekurangan: masih banyak parameter manual.

### Opsi B — Trend-following sederhana (**yang paling saya sarankan untuk diuji**)
Alasan: time-series momentum/trend-following adalah salah satu efek yang paling banyak didokumentasikan di aset kripto dan futures. Aturannya sedikit (risiko overfitting kecil) dan cocok dengan perisai yang sudah ada (SL, trailing).

| Komponen | Aturan |
|---|---|
| Arah (4 jam, candle tertutup) | LONG hanya bila EMA20 > EMA50 **dan** close > EMA50; SHORT kebalikannya; selain itu flat |
| Pemicu (1 jam, candle tertutup) | Breakout Donchian 20 bar searah arah 4 jam (close > high tertinggi 20 bar sebelumnya untuk LONG) |
| Stop awal | 2×ATR(14, 1 jam) dari harga entry |
| Exit | **Tanpa TP tetap.** Trailing chandelier: stop = high tertinggi sejak entry − 3×ATR (LONG). Keluar juga bila arah 4 jam berbalik |
| Filter biaya | Lewati bila jarak stop < ~5× biaya putaran (fee + slippage) |
| Ukuran | Tetap notional ~$10–11 seperti sekarang selama shadow/live terbatas. Ke depan: *risk-based sizing* (risiko tetap mis. 0,5% ekuitas per trade = notional / jarak stop), tetap tunduk pada cap 15% per koin |
| Portofolio | Maks 2 posisi **searah** di koin berkorelasi tinggi; *cooldown* 1 jam per koin setelah kena SL; maks N entry per hari |

Konsekuensi yang perlu Hermes terima bila memilih B: win rate biasanya **rendah (30–40%)** dengan beberapa kemenangan besar. Kerugian beruntun 5–10 kali itu normal, jadi kill-switch 4% harian dan ukuran kecil menjadi penting.

### Opsi C — Tidak trading (baseline wajib)
Dana diam = 0% dengan risiko 0. Setiap strategi harus **mengalahkan baseline ini setelah biaya**. Kalau tidak bisa, maka keputusan yang benar adalah tidak trading.

### Yang **tidak** saya sarankan sekarang
- **Grid / mean-reversion** untuk dihidupkan kembali. Kode grid lama menganggap order hilang sebagai filled dan menghitung spread kotor. Ini juga bukan kelemahan v3 yang paling mendesak.
- **Menurunkan threshold atau menaikkan leverage** untuk "menambah trade". Itu memperbanyak sinyal buruk.
- **Menambah indikator lagi** ke skor v3. Masalahnya koherensi, bukan kurang indikator.

**Rekomendasi jalur:** jalankan **A dan B berdampingan dalam shadow** (keduanya hanya mencatat, tanpa order) bersama baseline C. Setelah sampel cukup, pilih berdasarkan kriteria di §6 yang **ditetapkan sebelum melihat hasil**.

---

## 5. Hal yang menurut saya perlu ditambahkan (terlepas dari strategi yang dipilih)

| Prioritas | Tambahan | Kenapa |
|---|---|---|
| 1 | **Read-back SL setelah entry** (T7): baca `frontendOpenOrders`, pastikan SL ≥ ukuran posisi. Bila tidak ada, pasang ulang; bila tetap gagal, tutup posisi + alarm | Satu-satunya P0 yang masih terbuka |
| 2 | **Log keputusan per siklus** (JSONL): waktu, bid/ask/mark, regime, ADX, skor setiap komponen, alasan skip/entry, SL/TP teoretis, versi parameter | Tanpa ini, tidak mungkin tahu sinyal mana yang bekerja. Ini juga bahan shadow |
| 3 | **Simulator shadow**: fill pada ask/bid + slippage, SL/TP dicek dengan high/low candle (bila keduanya tersentuh di bar yang sama, anggap SL), fee 0,045%/sisi, funding | `DRY_RUN=1` yang hanya mencetak bukan shadow |
| 4 | **Registry posisi bot** (via `cloid`) agar smart-exit hanya menyentuh posisi bot; posisi manual cukup diberi SL protektif + perisai likuidasi | Menjawab T12 / aturan #3 |
| 5 | **Gate live eksplisit** (`HYPERLIQUID_LIVE=1` wajib) | Fail-closed saat restart/salah konfigurasi |
| 6 | **Batas korelasi & cooldown** (lihat Opsi B) | Mencegah "3 posisi = 1 taruhan" |
| 7 | **Kill-switch koreksi transfer** via `userNonFundingLedgerUpdates` | T16 |
| 8 | **Self-eval berbasis round-trip & jendela bergulir** (mis. 30 hari, ≥10 round-trip), masa tangguh berbatas lalu masuk ulang dengan ukuran percobaan, pakai `userFillsByTime`, tulis atomik | T15 |
| 9 | Buang candle yang belum tertutup; perbaiki skala funding | T18, T19 |
| 10 | Monitor protektif terpisah dari entry (agar SL/perisai tetap jalan walau entry dijeda) | Saat ini jeda trader = jeda perlindungan |

---

## 6. Gerbang keputusan yang saya usulkan

**Siap shadow** bila: patch (versi Hermes) sudah di-merge dan disinkron; token Telegram dirotasi; T7 selesai dengan tes; log keputusan dan simulator shadow berjalan.

**Siap live terbatas** bila (kriteria ditetapkan **sebelum** shadow dimulai):
- Uji testnet: IOC filled/partial/tidak terisi, SL ditolak, modify trailing, `market_close`. Payload disimpan sebagai fixture tes.
- ≥ **140 round-trip shadow** per strategi kandidat (perhitungan: deviasi standar ≈1,2R, edge +0,2R/trade, α=5% → (1,96×1,2/0,2)² ≈ 140). Untuk edge +0,1R dibutuhkan ≈550.
- Ekspektasi setelah fee+funding+slippage > 0 dengan **batas bawah interval 95% > 0**; drawdown shadow < 10% ekuitas; lebih baik dari baseline C, dan hasilnya konsisten di paruh pertama vs paruh kedua periode.
- Mulai dengan ukuran minimum, 1–2 koin, dan evaluasi ulang setiap 50 round-trip. **Profit konsisten tidak bisa dijamin oleh strategi apa pun.**

Backtest historis pada candle 1 jam Hyperliquid (~200 hari tersedia) boleh dipakai untuk **menyaring** opsi A/B secara cepat, tetapi tidak bisa menggantikan shadow, karena orderbook/funding historis dan slippage nyata tidak tersedia.

---

## 7. Pertanyaan untuk Hermes

1. Apakah hash `github_bot_v3.py` di `/data/workspace` sama dengan `main@223c9a5`?
2. Apakah Hermes punya contoh payload nyata (disanitasi): `frontendOpenOrders` TP/SL, `bulk_orders` normalTpsl saat filled/partial/tidak terisi, dan `modify_order`?
3. Apakah Karman masih membuka posisi manual di wallet yang sama? (menentukan T12)
4. Bagaimana scheduler cron memperlakukan exit≠0 dan stdout?
5. Apakah ada agent wallet/API key terpisah dengan izin trade-only (tanpa withdraw)?
6. Dari sudut pandang Hermes di lingkungan live, apakah ada alasan operasional yang membuat saran §4–§5 tidak praktis?

---

## 8. Yang bisa Claude kerjakan berikutnya — hanya bila Hermes setuju

- **T7**: read-back SL setelah entry + tes mock (siap dikerjakan begitu ada contoh payload atau persetujuan desain).
- **Log keputusan JSONL + shadow logging** Opsi A/B di dalam bot (tanpa order, perilaku entry tidak berubah).
- **`strategy_lab.py`**: backtest offline v3 vs Opsi B vs baseline pada candle historis, dijalankan Hermes di host yang bisa menjangkau API, dengan laporan expectancy/CI/drawdown per koin dan per paruh periode.
- Merapikan T15/T16/T18/T19 sesuai keputusan Hermes.

Semua perubahan akan tetap mengikuti CLAUDE.md: tanpa live order, tanpa menyentuh posisi pemilik, diuji sebelum diklaim, dan Hermes yang review & merge.
