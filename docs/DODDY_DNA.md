# DNA Trading alm. Doddy Ali Wijaya → Otak Bot DeFi91

> Disusun 24 November 2026 WIB untuk Bos Karman. Sumber gaya: dokumen
> *“DeFi91 — Analisis Menyeluruh Gaya Trading Futures”* (rekonstruksi 3.350 posting kanal
> DeFi 91, Nov 2021 – Jan 2023). Nomor `[xxxx]` = nomor posting kanal.
> Kode: `doddy_engine.py` (otak murni) + integrasi di `github_bot_v3.py`.
> Menggantikan bagian strategi di `DeFi91_KONSEP.html` / `HERMES_PROPOSAL_STRATEGIS.md`.
> **Ini rekonstruksi prinsip, bukan salinan sinyal, dan bukan jaminan profit.**

## 1. Siapa Doddy sebagai trader (yang benar-benar terbukti dari arsip)

Scalper futures **diskresioner, dua arah, berpusat pada BTC**. Ia tidak memakai satu rumus
tetap; yang konsisten adalah **proses**: bentuk dugaan arah dari gambaran besar → jajaki
dengan posisi kecil → baca respons pasar → tambah bila benar, lindungi profit, atau tutup.

Arsip juga jujur memperlihatkan sisi gelapnya: leverage sampai 125x, 40–95 posisi sekaligus,
DCA/average posisi rugi, menahan floating loss, greed ("profit 400 dikejar ke 500 tinggal
120"), dan re-entry tak lama setelah bilang mau istirahat. **Bot meniru prosesnya dan
membuang kebiasaan yang ia sendiri sesali.**

## 2. Sembilan gen DNA dan terjemahannya ke aturan bot

| # | Gen (bukti arsip) | Aturan di bot |
|---|---|---|
| 1 | Lihat daily dulu, BTC "tf4" sebagai acuan; prediksi di bawah 4h tak dipercaya [2489][3179][3204] | **Bias HTF**: tren 4h menentukan arah (EMA20 vs EMA50 + kemiringan), daily boleh netral tapi tidak boleh berlawanan. Berlawanan → WNS. |
| 2 | BTC kompas untuk semua alt [3179] | Alt hanya boleh searah **bias BTC**. Bila BTC berbalik → posisi alt searah ditutup (close basket). |
| 3 | "TA untuk open posisi, PA untuk langkah lanjutan" [3207] | TA hanya **pemicu** entry (ADX 1h ≥ 20, harga di sisi EMA20 yang benar, RSI di pita momentum yang belum mengejar pucuk). Manajemen setelah entry pakai flow & harga. |
| 4 | CVD spot & perp **dipisah**, spot lebih menentukan; spot kuat tapi perp kurang → *marking*, jangan haka; berlawanan imbang → WNS [3396][3475][3468] | **CVD spot sungguhan** dari volume taker Binance spot (bukan proxy). Perp = A/D candle Hyperliquid. Klasifikasi: `MARKING` (spot kuat, perp belum ikut), `CONFIRMED` (keduanya searah), `AGAINST`, `WNS`, `UNKNOWN`. |
| 5 | Marking BTC/ETH/BNB dulu; tidak jalan → cepat tutup; alt **setelah** posisi awal profit [3179][2370] | Posisi baru di core hanya saat `MARKING`. Alt dibuka hanya bila ada posisi core searah yang **sudah profit**. Marking yang 8 jam tidak jalan → ditutup. |
| 6 | "Tambah setelah konfirmasi + profit dari marking" [3477]; menyesal average down [2986][1641] | **ADD hanya untuk posisi yang menang**: tranche terbaru harus sudah +1 ATR. Tidak pernah menambah posisi rugi, tidak pernah membuka lawan posisi yang ada. |
| 7 | Ambil secukupnya; SL entry / SL+; tutup bila kelanjutan gagal (PA A-B-C) [3135][3382] | TP 2,5 ATR; **tangga stop**: +1 ATR → SL entry (BEP + fee), +1,5 ATR → SL+ (kunci 0,5 ATR), +2 ATR → trailing 1 ATR. Flow spot kuat melawan / bias berbalik → tutup. |
| 8 | Margin sama setiap entry, profit dipindah ke spot [3456][1613] | Margin tetap $2/tranche (tidak membesar setelah menang). Pemindahan profit ke spot **tidak diotomatiskan** (mutasi dana = keputusan pemilik). |
| 9 | "Belum sejam bilang istirahat dah OP lagi" [1646][2335] | **Disiplin**: rugi di koin X → cooldown 4 jam; 2 kekalahan dalam satu hari WIB → WNS sampai besok; plus kill-switch harian 4% yang sudah ada. |

### Yang sengaja TIDAK ditiru
- Leverage tinggi (20–125x) → bot tetap **5x cross**.
- 40–60 posisi basket → bot tetap **maks 3 simbol** (akun ±$41).
- Average down, hold loss, top-up setelah rugi → **dilarang oleh kode**.
- Entry karena berita/listing → tidak ada sumber berita terverifikasi; bot memilih WNS.

## 3. Satu temuan penting dari data (cocok dengan ucapan Doddy sendiri)

Versi pertama (v1) membolehkan posisi baru saat spot **dan** perp sama-sama searah
(`CONFIRMED`). Di data TRAIN, entry baru seperti itu **rata-rata rugi**, sedangkan entry
`MARKING` (spot memimpin, perp belum ikut) **untung**. Ini persis pesan Doddy 6 Jan 2023:
spot kuat tapi perp kurang → marking; **tambah setelah konfirmasi dan profit** [3475]–[3477].
Ketika spot dan perp sudah ramai bersamaan, gerakannya sudah telat dikejar.
v2 mengikuti itu: posisi baru **hanya** lewat marking; konfirmasi perp dipakai untuk ADD.

## 4. Bukti backtest (data nyata, bukan simulasi karangan)

Data: 5.000 candle 1h Hyperliquid (7 Mei – 23 Nov 2026) × 10 koin + candle spot Binance
dengan taker-buy volume. Fee taker 0,045%/sisi + slippage 0,02%/sisi, eksekusi di open
candle berikutnya, SL & TP di candle sama dianggap SL. Akun $58, margin $2 × 5x, cap 15%,
maks 3 simbol, kill-switch 4%. Ambang CVD dibekukan **0,06** (≈ median TRAIN) sebelum TEST.

| Strategi | TRAIN (Mei–Agu) | **TEST (Agu–Nov, out-of-sample)** | PF TEST | Max DD TEST |
|---|---|---|---|---|
| Legacy v3 (kode sebelum ini) | −3,7% | **−4,8%** | 0,73 | 6,5% |
| Tren saja (tanpa CVD) | −0,8% | +4,7% | 1,16 | 8,2% |
| **DNA Doddy v2** | **+0,9%** | **+3,8%** | **1,36** | **3,2%** |

Sensitivitas ambang CVD di TEST: 0,05 → +3,6% · 0,06 → +3,8% · 0,08 → +3,7% (semua positif).
Detail mentah: `research/backtest/RESULTS_2026-11-23.txt`; ulangi dengan
`research/backtest/fetch_data.py` lalu `backtest.py`.

### Batas kejujuran
- t-stat ≈ 1,3 → **menjanjikan, belum terbukti secara statistik.** ~100 hari TEST.
- Funding tidak dihitung; perp-flow masih proxy A/D (Hyperliquid tak memberi taker delta historis).
- Komponen orderbook/funding legacy tak ada historisnya (dianggap 0).
- Nominal kecil: +3,8% dari $58 ≈ +$2,2 dalam ~3 bulan. Tujuan tahap ini adalah
  **edge positif dengan drawdown kecil**, bukan kaya cepat.
- Wajib **shadow dry-run** di host Hermes sebelum live (lihat `HANDOFF-HERMES.md`).

## 5. Cara membaca log bot (mode doddy)

```
🧭 Kompas BTC: bias=+1 | CVD spot=0.081
  [BTC] bias=+1 spot=+0.081 perp=-1 flow=MARKING -> OPEN (core: marking (spot memimpin, perp belum ikut))
  [SOL] bias=+1 spot=+0.120 perp=+1 flow=CONFIRMED -> SKIP (flow sudah ramai ... jangan kejar)
  🧠 DNA OPEN LONG BTC: core: marking ...
  ⚡ DNA early close ETH: flow spot kuat melawan (kelanjutan gagal)
```

## 6. Saklar & parameter

- `DEFI91_STRATEGY=doddy` (default) | `legacy` (rollback ke skor v3 lama).
- `HYPERLIQUID_DRY_RUN=1` → hanya baca & cetak keputusan; tidak ada `Exchange`.
- Parameter DNA ada di `DnaConfig` (`doddy_engine.py`). Mengubahnya = strategi baru →
  wajib backtest ulang dengan pembagian TRAIN/TEST yang sama.
- Exit strategi DNA **hanya** untuk posisi yang dibuka bot (tercatat di
  `~/.defi91_dna_state.json`). Posisi manual/lama pemilik hanya dilindungi (perisai likuidasi,
  AUTO-SL, tangga stop) — tidak ditutup karena alasan strategi.
