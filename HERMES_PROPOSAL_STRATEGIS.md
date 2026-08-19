# 🤖 HERMES DeFi91 — PROPOSAL STRATEGIS (FASE 0)

**Disusun oleh:** Hermes Agent · **Tanggal:** 19 Agustus 2026
**Konteks:** Aksi keluar dari `HERMES_MASTER_HANDOFF.md` — audit forensik bot + proposal konsep strategi baru.
**Gerbang Keamanan:** Saldo **$0**. Tidak ada deposit / eksekusi trade sebelum proposal ini **disetujui Pak Karman**. Tidak satu pun kredit nyata dipakai; semua angka dari file repo + API Hyperliquid.

---

## 1️⃣ TEMUAN MASALAH (Akar Kegagalan Juli)

Audit kode `github_bot_v2.py`, `trades.json` (525 entri), `performance.json`, dan `journal.json` menemukan **6 akar masalah struktural** — bukan sekadar nasib buruk:

### 🔴 1. "CVD" yang dipakai BUKAN CVD almarhum (pukulan paling fatal)
`calculate_cvd()` hanya menghitung **rasio beli/total dari ±200 recentTrades terakhir** = jendela **beberapa menit** aktivitas. Itu *noise*, bukan *Cumulative Volume Delta* yang menangkap akumulasi/distribusi whale.
- Di BTC yang ramai, 1 menit = belasan ribu trade → rasio itu berubah bolak-balik tiap tick → **whipsaw terus-menerus**.
- DNA almarhum ("akumulasi whale") butuh jendela **1H/4H** kumulatif + divergence delta vs harga. Tidak pernah terimplementasi.

### 🔴 2. MACD salah implementasi (bug, bukan pilihan)
```python
macd_line = np.mean(closes[-12:]) - np.mean(closes[-26:])   # SMA, bukan EMA
signal    = np.mean(closes[-9:]) - np.mean(closes[-18:])    # tidak diturunkan dari MACD line!
```
- SMA ≠ EMA. Dan "signal line" itu **dua SMA yang tak berkaitan** dengan MACD line. Jadi "BULLISH/BEARISH CROSS" yang memicu entry hanyalah kebetulan statistik.
- MACD sejati: `EMA12 − EMA26` → lalu `signal = EMA9(macd_line)`.

### 🟠 3. Terlalu banyak trading + Watchlist melenceng dari DNA almarhum
- **525 entri** dalam ~5 minggu; **notional $27.465 dari modal $50** (≈550× modal dikocok).
- `trades.json` memuat **18 koin**, termasuk microcap: HYPE, WLD, NEAR, DOGE, FARTCOIN, ENA, LIT, ZEC, CRV, TON, ADA.
- Bertentangan total dengan filosofi almarhum: *"gw cuman BNB BTC dan ETH yang berani lev 50x, lain itu 20-25x… alts kadang random, tapi 3 itu pasti."* Microcap manipulatif (XPL, HYPE) = sumber jebakan.

### 🟠 4. Fee Attrition (biaya diam-diam terbesar)
- Entry IOC + 2 trigger-market (TP & SL) ≈ **3 sisi taker**. Di taker ~0.045%, ≈ **0.135%/trade**.
- $$\approx 0.135\% \times \$27.465 \approx \textbf{\$30–37 fee}$$ dari modal $50 → **hampir 60–70% modal habis di fee** sendirian.
- Win rate 37,8% + R:R ~1.33 → **expectancy negatif**: `0.378×1.33 − 0.622×1 ≈ −0.119/trade`. Setiap trade kecil = minus, sekalipun arah benar.

### 🟠 5. Risk-sizing jebol & tanpa "circuit breaker"
- SL **fixed 1.28%** (bukan berbasis volatilitas/ATR). Pada **20× leverage**, SL 1.28% = **25% margin** — kena noise harian terus.
- 4 posisi paralel × $3 margin = $12 margin dari akun ≤$50, tanpa **daily loss limit**. Bot terus re-entry (threshold 4) walau sedang babak-belur.
- Tragedi BTC −$14.43 & jebakan XPL −$22.80 = **loss tunggal tanpa pengaman**: slippage/gap pada 20× bikin rugi > 30% margin (5% harga = likuidasi penuh).

### 🟡 6. Timeframe 15 menit
Gate "akumulasi whale" (1H/4H) dan gate "jangan entry area jenuh" (KJo) **tidak mungkin** terpenuhi di 15m. Semua sinyal = intrabar noise.

---

## 2️⃣ KENAPA FUNDING-ARB / LIQUIDATION-HEATMAP TIDAK KAMI ANGKAT (jujur)

Ditanya di handoff; jawaban berdasarkan data pasar live hari ini:
| Opsi | Status 19/8 | Alasan |
|---|---|---|
| **Funding Rate Arbitrage** | ❌ Non-aktif | Funding BTC −0.0003%, ETH +0.0007%, BNB +0.0011% → **semua ~0** (pasar sideways). Tidak ada yield yang bisa ditangkap; plus butuh delta-neutral spot+perp per moda. |
| **Liquidation Heatmap** | ⚠️ Filter saja | Tabel likuiditas/liquidation clusters sebagai **konteks**, bukan sinyal utama. Dengan modal $50 tidak ada asumsi cukup modal untuk memanfaatkannya. |
| **Market-Making / Delta-Neutral** | ❌ Di luar skala | Butuh modal besar + infra maker + hedging. Bukan untuk $50–100. |

Kesimpulan: untuk modal $50–100, **edge bukan pada indikator baru yang glamor, tapi pada (a) memperbaiki bug indikator, (b) mematuhi DNA almarhum, (c) redam leverage & risk, (d) kurangi drastis jumlah trading (fee).**

---

## 3️⃣ SOLUSI STRATEGIS BARU — "Smart Money Regime Bot v2"

Empat pilar perubahan, semuanya dapat dieksekusi di repo yang ada:

### 3A. ⚙️ Fix indikator (bug dulu, baru strategi)
1. **CVD sejati** → kumulasi delta 1H/4H + sinyal **divergence delta vs harga** (delta naik tapi harga sideways = akumulasi = sinyal longs; delta turun tapi harga datar = distribusi).
2. **MACD sejati** → `EMA12−EMA26` + `signal=EMA9(macd)`.
3. **RSI Wilder smoothing** (bukan simple-mean).

### 3B. 🛡️ Leverage & risk redam
| Parameter | Lama | **Baru** |
|---|---|---|
| Leverage | 10–20× | **3–5×** |
| Posisi paralel | 4 | **maks 1–2** |
| SL | fixed 1.3% | **2×ATR** (naik turun mengikuti pasar) |
| Risk per trade | $3 | **≤2% akun** (dengan margin $2, only 2 posisi = ≤4–8% akun) |
| Stop harian | **tidak ada** | **Kill-switch: rugi ≥4% hari ini → stop trading sampai besok** |

### 3C. 📌 Watchlist disiplin — kembali ke DNA almarhum
- **Hanya BTC, ETH, BNB.** Semua alt & microcap **dihapus total** (HYPE, WLD, NEAR, DOGE, FARTCOIN, ENA, LIT, ZEC, CRV, TON, XPL — larangan keras).
- Contoh: best trade historis +$13.105 datang dari BTC; konsistensi tertinggi justru di 3 koin utama.

### 3D. 📈 Timeframe 1H/4H + filter tren (ADX)
- Naik dari 15m → **1H untuk entry, 4H untuk arah**.
- Entry **hanya jika ADX ≥ 25** (tren kuat) & candle menuju arah sinyal → menyelesaikan kecemasan KJo soal "entry di area jenuh".
- Gunakan modul `market_regime_filter.py` yang sudah ada; global CHOPSAW = **mode standby** (nol-trade), bukan mode agresif.

---

## 4️⃣ TARGET RECOVERY (Konservatif & Matematis)

> Prinsip: **proses & perlindungan modal dulu; profit adalah hasil samping.** Tidak ada janji "double dalam seminggu".

- **Deposit awal disarankan $50** (bukan $100) — cukup untuk 1–2 posisi aman tanpa tekanan.
- Realistis pasca-perbaikan:
  - Target **win rate 45–50%** pada **R:R ≈ 2:1** (ATR-based) → **expectancy positif** ≈ `0.475×2 − 0.525×1 ≈ +0.425/trade`.
  - Bulan 1: target **0–+5%** (uji proses). Bulan 2+: **+3–8%/bln** bila prosesnya menang.
- **Escalation rule (pelindung):** ukuran/target naik **hanya** jika dalam 30 hari akun sehat, drawdown < 15%, dan win rate ≥ 45%. Jika rugi ≥ 20%, turunkan ukuran, bukan menaikkannya.

### Roadmap bertingkat
- **Tahap 1 (minggu 1–2):** bot hidup mode aman — 1 posisi, 3×, majors-only. Fokus membuktikan proses, minimalkan fee (kurangi jumlah trade).
- **Tahap 2 (minggu 3–4):** naik ke 2 posisi, taxable level lebih besar, hanya bila Tahap 1 hijau.
- **Tahap 3:** evaluasi mingguan + laporan; deposit tambahan hanya berdasarkan bukti, bukan harapan.

---

## 5️⃣ PERTANYAAN KEPUTUSAN UNTUK PAK KARMAN (GATE)

Sebelum saya sentuh kode apa pun di repo & sebelum deposit:
1. **Setujui** prinsip inti: leverage 3–5×, maks 1–2 posisi, BTC/ETH/BNB saja, SL ATR, kill-switch harian, timeframe 1H/4H?
2. **Deposit:** $50 (saran saya) atau $100?
3. **Setuju** menghapus semua alt/microcap dari watchlist demi mengembalikan DNA almarhum?

> Setiap jawaban **konfirmasi** dari Bapak = lampu hijau untuk saya kerjakan `github_bot_v2.py` ke versi v3 (fix CVD/MACD/RSI, ATR-SL, leverage rendah, kill-switch, watchlist 3-koin) dan mulai depot sesuai kesepakatan. Tanpa persetujuan, **tidak ada aksi** — saldo tetap $0.

---

*Dokumen ini sengaja datar & JIGA — angka bisa diverifikasi dari repo. Disusun untuk dibaca & diputuskan oleh manusia.*
