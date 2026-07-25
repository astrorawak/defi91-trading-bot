# Analisa Bot DeFi91 — Cara Kerja, Temuan, dan Saran

Dokumen ini menjelaskan bagaimana bot bekerja secara konsep, apa saja yang saya
temukan bermasalah, apa yang sudah saya perbaiki, dan apa saran saya ke depan.

---

## Bagian 1 — Konsep: Bagaimana Bot Ini Bekerja

### Gambaran besar

Bot ini bukan program yang jalan terus-menerus. Bot ini **dibangunkan oleh
GitHub Actions 11 kali sehari**, mengerjakan satu siklus penuh, lalu mati lagi.
Semua "ingatannya" disimpan di file JSON yang di-commit balik ke repo.

```
GitHub Actions (cron 11x/hari)
        │
        ├─► github_bot_v2.py   ← Scalping Bot: aktif saat pasar TRENDING
        │
        ├─► grid_bot.py        ← Grid Bot: aktif saat pasar SIDEWAYS
        │
        └─► commit trades.json / performance.json / market_regime.json
                    │
                    └─► GitHub Pages (index.html) = dashboard
```

Dua bot berbagi **satu akun Hyperliquid** yang sama, dan dirancang saling
melengkapi: kalau pasar bergerak searah, scalping yang bekerja; kalau pasar
mondar-mandir di satu rentang, grid yang panen.

### Siklus satu run scalping bot

**1. Cek saldo & posisi terbuka**
Bot menanyakan ke Hyperliquid: berapa ekuitas saya, berapa margin yang sedang
terpakai, posisi apa saja yang masih terbuka.

**2. Deteksi regime pasar** (`market_regime_filter.py`)
Untuk setiap koin, bot menghitung tiga hal dari candle 15 menit:
- **ADX** — seberapa kuat trennya (di atas 25 = tren jelas)
- **Bollinger Band Width** — seberapa lebar pergerakan harga (sempit = mampet)
- **ATR** — volatilitas absolut

Hasilnya satu label: `TRENDING`, `NEUTRAL`, atau `CHOPSAW`. Label ini disimpan
ke `market_regime.json` dan **dibaca juga oleh grid bot** — begitulah cara
kedua bot berkoordinasi tanpa saling bicara langsung.

**3. Kelola posisi yang sudah terbuka**
Untuk setiap posisi:
- **Smart Exit** — analisa ulang koinnya. Kalau sinyal sekarang berbalik sangat
  kuat melawan posisi, tutup lebih awal daripada menunggu kena SL.
- **Trailing Stop** — kalau sudah profit ≥0.8%, geser SL ke titik impas
  (breakeven). Kalau profit ≥1.5%, geser lagi untuk mengunci sebagian profit.

**4. Cari entry baru — sistem skor**
Ini inti strateginya. Setiap koin dinilai dari dua sudut pandang:

**A. Order Flow (strategi almarhum Doddy Ali Wijaya)** — skor −7 s/d +7
| Indikator | Bobot | Logika |
|---|---|---|
| **CVD** (Cumulative Volume Delta) | ±3 | Bandingkan volume beli agresif vs jual agresif. Beli >65% = tekanan beli nyata. Ini "indikator raja" di strategi ini. |
| **Order Book Ratio** | ±2 | Volume bid vs ask di 10 level teratas. Bid jauh lebih tebal = ada penopang. |
| **Funding Rate** | ±2 | **Kontrarian.** Funding sangat positif = terlalu ramai yang long = rawan dibersihkan, jadi bot condong SHORT. |

**B. Teknikal (KJo Academy)** — skor −5 s/d +5
RSI, MACD, dan posisi harga terhadap support/resistance.

**5. Keputusan**
Skor total = order flow + teknikal (rentang −12 s/d +12).
- Skor ≥ ambang → **LONG**
- Skor ≤ −ambang → **SHORT**
- Di antaranya → **WNS (Wait and See)**, tidak entry

**6. Eksekusi**
Bot mengirim **tiga order sekaligus** dalam satu grup (`normalTpsl`):
market order untuk masuk + take profit + stop loss. Ini penting — kalau TP/SL
dikirim terpisah, ada jendela waktu di mana posisi telanjang tanpa proteksi.

**7. Catat & laporkan**
Tulis ke `trades.json`, kirim sinyal ke Telegram, commit ke repo, dashboard
otomatis ter-update.

### Konsep grid bot

Grid bot bekerja dengan asumsi berbeda: **harga akan bolak-balik**. Bot memasang
tangga order — 3 beli di bawah harga sekarang, 3 jual di atasnya, dengan jarak
antar level dihitung dari ATR. Setiap kali satu order terisi, bot memasang order
lawannya di level berikutnya. Selisihnya jadi profit. Kalau harga kabur keluar
rentang, grid dibongkar dan dipasang ulang di posisi baru.

---

## Bagian 2 — Temuan: Apa yang Bermasalah

Saya urutkan dari yang paling parah.

### 🔴 1. Bot tidak bisa jalan sama sekali — SyntaxError

Ini temuan terbesar. Di commit `66bda09` (2 Juli 2026), bot dinonaktifkan
dengan cara mengomentari watchlist. Tapi yang dikomentari **hanya baris
pertamanya**:

```python
WATCHLIST = [] # BOT OFF
# OLD_WATCHLIST = [
    "ETH",   # ← baris ini TIDAK dikomentari
    "XRP",
    ...
]            # ← kurung tutup menggantung = IndentationError
```

Akibatnya `python github_bot_v2.py` langsung mati sebelum baris pertama
dieksekusi. **Sejak 2 Juli, setiap dari 11 run harian gagal** — dan karena
langkah berikutnya di workflow memakai `git push || true`, tidak ada satu pun
notifikasi kegagalan yang sampai ke Anda. File `bot_final.py` yang identik
punya bug yang sama persis.

### 🔴 2. Token Telegram bocor di repo publik

`telegram_signals.py`, `telegram_reporter.py`, dan `weekly_insights.py`
menyimpan token bot Telegram dan chat ID Anda sebagai nilai default:

```python
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8944256953:AAF_...")
```

Siapa pun yang membuka repo bisa mengambil token itu dan mengirim pesan
atas nama bot Anda. **Token ini harus dicabut, bukan sekadar dihapus dari
kode** — riwayat git masih menyimpannya.

### 🔴 3. Matematika strateginya memang rugi

Ini bukan bug, tapi justru yang paling penting. Data nyata dari
`performance.json`:

| | |
|---|---|
| Total trade | 611 |
| Menang / kalah | 231 / 380 |
| **Win rate** | **37.8%** |
| **Net PnL** | **−$2.78** |

Dengan parameter lama — TP 2%, SL 1.5%, leverage 20x, fee taker 0.045% per
sisi — win-rate minimum agar **impas** adalah:

```
(0.30 + 0.018) / (0.40 + 0.30) = 45.4%
```

Bot mencetak 37.8%. Selisih 7.6 poin persen itulah kenapa saldo terus terkikis.
Menambah agresivitas (menurunkan ambang entry dari 5 ke 4, seperti di kode lama)
justru mempercepat kerugian, bukan memperbaikinya — lebih banyak trade dengan
ekspektasi negatif tetap saja lebih banyak rugi.

### 🔴 4. Slippage entry 0.5% = 10% dari margin

```python
limit_px = format_price(current_price * 1.005)  # 0.5% slippage
```

Di leverage 20x, terisi 0.5% lebih buruk dari harga acuan berarti langsung
kehilangan **10% dari margin** sebelum trade sempat bergerak. Padahal TP-nya
cuma 2% (= 40% margin). Jadi seperempat target profit hangus di detik pertama.

### 🟠 5. Rumus MACD-nya salah

```python
def calculate_macd(prices):
    ema12 = np.mean(prices[-12:])            # ini SMA, bukan EMA
    ema26 = np.mean(prices[-26:])            # ini juga SMA
    signal = np.mean(prices[-9:]) - np.mean(prices[-18:])   # ini bukan apa-apa
```

Tiga masalah: variabelnya dinamai `ema` tapi isinya rata-rata sederhana, dan
signal line-nya sama sekali bukan EMA-9 dari MACD line — itu selisih dua
rata-rata acak. Jadi setiap sinyal "BULLISH CROSS" yang pernah dikirim ke
Telegram tidak punya arti teknikal apa pun.

RSI juga tidak memakai Wilder smoothing (nilainya beda dengan TradingView),
dan ADX di filter regime mengembalikan DX satu periode tanpa smoothing —
sangat berisik, jadi label TRENDING/CHOPSAW sering keliru.

### 🟠 6. Indikatornya saling meniadakan

RSI dipakai secara **mean-reversion** (oversold = beli), sedangkan MACD dipakai
secara **trend-following** (bullish = beli). Di pasar yang sedang naik kuat,
RSI tinggi memberi −2 sementara MACD memberi +2. Keduanya batal.

Efeknya halus tapi merusak: skor total cenderung mengambang di sekitar nol,
dan skor besar justru muncul saat kedua indikator kebetulan sejajar — yang
sering terjadi tepat di titik kelelahan tren. Bot jadi cenderung masuk di
puncak dan dasar.

### 🟠 7. Skor dijumlahkan tanpa syarat kesepakatan

```python
total_score = onchain_score + tech_score
if total_score >= ENTRY_THRESHOLD: direction = "LONG"
```

Order flow +7 dengan teknikal −3 menghasilkan +4 → bot LONG, padahal kedua
sisi analisa sedang **bertentangan keras**. Trade seperti ini yang paling
sering jadi loss besar.

### 🟠 8. `trades.json` tidak pernah diperbarui

Semua **525 entri berstatus `"OPEN"` dengan `pnl: 0`** — termasuk trade dari
Juni yang jelas sudah lama tertutup. Bot hanya menulis saat membuka posisi,
tidak pernah menutup catatannya.

Konsekuensinya berantai:
- Dashboard menampilkan 525 "posisi terbuka" yang tidak nyata
- `optimize_params.py` memfilter `status == "CLOSED"` → selalu kosong → script
  itu **tidak pernah sekali pun menghasilkan output berguna**
- Anda tidak punya cara mengetahui sinyal seperti apa yang benar-benar menang

### 🟠 9. Tidak ada satu pun pengaman di level akun

Bot lama tidak punya batas rugi harian, tidak ada batas drawdown, tidak ada
jeda setelah loss beruntun. Satu-satunya yang menghentikannya adalah saldo
habis — dan itu terlalu terlambat. `github_bot_live.py` sebenarnya punya
`DAILY_LOSS_LIMIT`, tapi file itu tidak dipakai workflow mana pun.

### 🟠 10. Saldo spot dipakai sebagai margin perps

```python
account_value = usdc_balance          # dari spotClearinghouseState
available = account_value - margin_used   # margin_used dari perps
```

Spot dan perps adalah **dua dompet terpisah** di Hyperliquid. Kalau USDC
menumpuk di spot, bot mengira punya margin bebas yang sebenarnya tidak bisa
dipakai untuk membuka posisi — ordernya ditolak exchange, dan run terbuang.

### 🟡 11. Grid bot mencatat profit yang tidak ada

Di `manage_grid()`, setiap kali order SELL terisi, bot membukukan profit
sebesar satu interval grid. Tapi order grid dipasang dengan `reduce_only=False`
di **kedua sisi**. Kalau posisi sedang flat lalu harga naik menembus level
sell, order itu **membuka short baru** — bukan menutup long dengan untung.
Jadi `summary.total_profit_usd` bisa terus naik sementara akun sebenarnya rugi.

### 🟡 12. Kegagalan jaringan menyamar jadi sinyal netral

```python
except:
    return 1.0      # get_orderbook: gagal → "seimbang"
except:
    return 0        # get_funding_rate: gagal → "netral"
```

Bot tidak bisa membedakan "pasar sedang seimbang" dari "saya tidak berhasil
mengambil datanya". Satu gangguan jaringan bisa membuat bot entry berdasarkan
data yang sebagian besar tidak ada.

### 🟡 13. Masalah lain-lain

- `bot_final.py` dan `github_bot_v2.py` **identik byte-per-byte** — perbaikan
  di satu file tidak ikut ke yang lain
- `MAX_LEVERAGE_MAP` dan `SZ_DECIMALS` di-hardcode; kalau Hyperliquid ubah
  batas leverage, order ditolak dan errornya cuma muncul di log
- Tidak ada cek **nilai order minimum $10** Hyperliquid. VVV maksimal 3x
  leverage × margin $3 = notional $9 → **selalu ditolak**
- Tidak ada `requirements.txt`, tidak ada tes, tidak ada `concurrency` di
  workflow (dua run bisa bertabrakan dan sama-sama buka posisi)
- API dipanggil dua kali untuk koin yang sama dalam satu run (sekali saat
  kelola posisi, sekali saat cari entry) — boros dan rawan rate limit
- `update_performance_mini()` menambah titik equity curve setiap run walau
  nilainya sama, jadi grafiknya penuh titik identik

---

## Bagian 3 — Apa yang Sudah Saya Perbaiki

### File baru

| File | Fungsi |
|---|---|
| **`config.py`** | Semua parameter terpusat, dibaca dari environment variable. Ada kill switch `BOT_ENABLED` dan mode `DRY_RUN`. Termasuk fungsi `breakeven_win_rate()` yang menghitung win-rate impas dari parameter yang sedang aktif. |
| **`indicators.py`** | EMA, RSI (Wilder), MACD, ATR, ADX (Wilder), Bollinger — semua dengan rumus yang benar dan bisa diuji tanpa jaringan. |
| **`risk_manager.py`** | Batas rugi harian, batas drawdown, cooldown setelah loss beruntun, validasi order minimum, dan **rekonsiliasi `trades.json`** dari fill nyata. |
| **`tests/test_indicators.py`** | 28 tes. Semua lolos. |
| **`requirements.txt`** | Dependensi dengan versi di-pin. |

### Perbaikan per masalah

| # | Masalah | Perbaikan |
|---|---|---|
| 1 | SyntaxError | Diperbaiki. `bot_final.py` jadi shim yang meneruskan ke `github_bot_v2.py`, tidak lagi menduplikasi kode. Workflow sekarang menjalankan `compileall` + tes **sebelum** menyentuh exchange. |
| 2 | Token bocor | Semua hardcode dihapus, wajib dari environment. |
| 3 | Matematika rugi | Default berubah: **TP 2.4% / SL 1.2% / leverage 10x**. Win-rate impas turun dari **45.4% → 35.8%**, di bawah win-rate historis 37.8%. |
| 4 | Slippage 0.5% | Turun ke **0.15%** (`ENTRY_SLIPPAGE`). |
| 5 | Rumus salah | MACD pakai EMA sungguhan + signal EMA-9. RSI pakai Wilder. ADX pakai smoothing penuh. |
| 6 | Indikator bentrok | `analyze_technical()` sekarang **sadar regime**: mode TREND saat pasar trending (MACD & ADX sebagai konfirmasi), mode REVERSION saat sideways (RSI ekstrem & support/resistance). |
| 7 | Skor tanpa kesepakatan | `decide_direction()` mewajibkan **konfluensi** — order flow dan teknikal harus searah. |
| 8 | trades.json mati | `reconcile_trades()` mencocokkan entri OPEN dengan posisi & fill nyata, mengisi PnL bersih (sudah dikurangi fee), dan menandai CLOSED. Jalan otomatis tiap run. |
| 9 | Tak ada pengaman | `check_all()` sebagai gerbang sebelum entry. Menutup posisi **tidak pernah** ikut terblokir. |
| 10 | Spot vs perps | `get_balances()` memisahkan keduanya; margin bebas diambil dari `withdrawable` perps. |
| 11 | Profit grid palsu | Ada pelacakan persediaan (`inventory`) per pair. Profit hanya dibukukan kalau ada lot beli yang benar-benar terisi lebih dulu. |
| 12 | Error jadi netral | Fungsi data mengembalikan `None` saat gagal. Bot **melewati** koin dengan data tidak lengkap, tidak menebak. |
| 13 | Lain-lain | Metadata coin diambil dari API; validasi notional minimum $10; cache per run; `concurrency` di workflow; push dengan rebase + retry (bukan `\|\| true`); equity curve tidak lagi menambah titik duplikat. |

### ⚠️ Penting: bot dalam keadaan MATI

`BOT_ENABLED` **default-nya `false`**. Saya sengaja tidak menyalakan bot yang
memegang uang sungguhan tanpa Anda memutuskannya sendiri. Cara menyalakan ada
di README.

---

## Bagian 4 — Saran Saya

### Yang harus dilakukan hari ini

**1. Cabut token Telegram.** Buka `@BotFather` → `/revoke` → buat token baru →
simpan sebagai GitHub Secret. Token lama masih ada di riwayat git dan tidak
bisa dihapus hanya dengan mengedit file.

**2. Cek posisi nyata di Hyperliquid.** Bot mati sejak 2 Juli. Kalau ada posisi
yang terbuka sejak sebelum itu, TP/SL-nya mungkin masih menggantung tanpa ada
yang mengelola. Periksa manual.

**3. Jalankan rekonsiliasi** untuk memperbaiki riwayat:
```bash
python risk_manager.py       # bereskan trades.json
python optimize_params.py    # lihat performa nyata per coin
```

### Sebelum menyalakan lagi

**4. Jalankan `DRY_RUN=true` minimal 1–2 minggu.** Semua analisa tetap berjalan
dan tercatat, tapi tidak ada order yang dikirim. Ini satu-satunya cara mengukur
apakah perubahan logika benar-benar memperbaiki kualitas sinyal, tanpa membayar
untuk mengetahuinya.

**5. Sadari keterbatasan data Anda.** 611 trade terdengar banyak, tapi tersebar
di 18 koin dan beberapa set parameter berbeda. Per koin, jumlahnya terlalu
sedikit untuk menyimpulkan "ETH profitable, SOL tidak" — itu bisa murni
kebetulan. Watchlist "proven profitable" di kode lama kemungkinan besar hasil
**overfitting** ke kebisingan.

### Yang perlu dipikirkan lebih dalam

**6. Frekuensi cron tidak cocok dengan strategi.** Bot memakai candle 15 menit
tapi hanya bangun 11 kali sehari — jeda 1–3 jam antar run. Trailing stop yang
bereaksi pada profit 0.8% praktis tidak berguna kalau harga sudah bolak-balik
berkali-kali sejak run terakhir. Pilih salah satu:
- **Naikkan timeframe** ke 1H atau 4H supaya sinyalnya seumur dengan jadwal run
- **atau** pindahkan bot ke VPS kecil yang jalan terus-menerus

Menurut saya opsi pertama lebih masuk akal untuk sekarang — lebih murah, dan
sinyal timeframe tinggi lebih jarang tapi lebih bersih.

**7. Leverage 20x adalah masalah struktural, bukan sekadar parameter.**
Di 20x, gerakan harga 5% saja sudah likuidasi. Digabung dengan margin $3 dan
saldo ~$10–25, tidak ada ruang untuk salah. Saya sudah turunkan default ke 10x.
Kalau ingin lebih agresif, naikkan **ukuran posisi**, bukan leverage — risikonya
lebih mudah dihitung.

**8. Order book 10 level teratas adalah sinyal yang lemah.** Di perpetual DEX,
level teratas penuh order palsu (spoofing) yang ditarik sebelum tersentuh.
Bobot ±2 untuk sinyal ini terlalu besar. Kalau `optimize_params.py` nanti
menunjukkan skor tinggi tidak berkorelasi dengan kemenangan, komponen ini
kandidat pertama untuk dibuang.

**9. Yang paling penting: bangun backtest.** Semua perbaikan yang saya lakukan
memperbaiki hal-hal yang **jelas salah** — rumus keliru, tidak ada pengaman,
matematika yang tidak menguntungkan. Tapi tidak satu pun dari itu membuktikan
strategi dasarnya punya keunggulan (*edge*).

Selama belum ada backtest, setiap penyetelan parameter hanyalah tebakan
berbiaya uang sungguhan. Yang dibutuhkan: ambil data candle historis,
jalankan logika skor terhadapnya, lihat distribusi hasilnya. Ini pekerjaan
seharian, dan nilainya jauh lebih besar daripada semua penyetelan parameter
digabungkan.

### Yang jujur harus saya sampaikan

Bot ini rapi secara rekayasa — dashboard, jurnal AI, laporan Telegram,
otomatisasi penuh. Tapi selama 611 trade, hasilnya **negatif**, dan angka itu
sudah cukup untuk mengatakan strategi dalam bentuknya sekarang belum punya
keunggulan yang bisa dibuktikan.

Perbaikan saya membuat bot **berhenti kalah karena alasan yang salah** —
rumus keliru, biaya tersembunyi, tidak ada rem. Itu memindahkan titik impas
dari 45.4% ke 35.8%, yang secara teknis membuat win-rate historis Anda cukup
untuk sedikit profit. Tapi itu bergantung pada asumsi win-rate tetap sama
dengan parameter baru — dan asumsi itu belum teruji.

Saran paling berharga yang bisa saya berikan: **jalankan `DRY_RUN` dulu, dan
kumpulkan bukti sebelum mempertaruhkan modal lagi.** Bot ini sudah punya semua
perkakas untuk melakukannya.
