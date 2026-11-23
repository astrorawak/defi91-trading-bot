# HANDOFF → Hermes: Otak DNA Doddy + penyelarasan cron (24 Nov 2026 WIB)

Dari: Claude (koder/QA). Untuk: Hermes (review, merge, deploy, cron).
Branch: `claude/defi91-bot-v3-trading-7w6g60` (berbasis `main` 4770b0c). **Belum di-merge,
belum di-deploy, tidak ada cron yang saya ubah** (saya tidak punya akses ke host `/data`).
Menggantikan `HERMES_HANDOFF*.md` (Agustus) sebagai serah-terima terbaru.

## 0. Ringkasan untuk Bos Karman (1 menit)
- Otak strategi diganti dari skor v3 (backtest 200 hari: **−8,2%**) ke **DNA Doddy v2**
  (TEST out-of-sample: **+3,8%, PF 1,36, max DD 3,2%**). Konsep: `docs/DODDY_DNA.md`.
- 1 bug fatal ditemukan & diperbaiki: **smart-exit terbalik** (menutup LONG saat sinyal LONG
  makin kuat). Saya melewatkan bug ini di audit Agustus — sekarang dikunci dengan tes.
- **Token bot Telegram tertanam di 3 file repo publik** → sudah dihapus dari kode, tapi
  token lama masih ada di riwayat git → **WAJIB dicabut di @BotFather**.
- Trader tetap **PAUSED**. Langkah aman: shadow dry-run ≥ 2 minggu dulu, baru live.

## 1. File yang berubah
| File | Perubahan |
|---|---|
| `doddy_engine.py` (baru) | Otak DNA murni: bias HTF, kompas BTC, CVD spot vs perp, marking→add winners, tangga stop, disiplin. Tanpa jaringan/order. |
| `github_bot_v3.py` | Saklar `DEFI91_STRATEGY` (default `doddy`); data candle **hanya tertutup** + validasi; CVD spot Binance; state `~/.defi91_dna_state.json` (atomik 0600); disiplin dari `user_fills_by_time`; exit DNA hanya utk posisi milik bot. Fix: smart-exit terbalik, min notional (ceil ≥ $10,5), entry batal bila `update_leverage` gagal, override rusak → fail-closed (hanya core), core tak pernah bisa disuspend, cek error per-order pada modify SL. |
| `defi91_eval.py` | Jendela bergulir 30 hari (`DEFI91_EVAL_DAYS`) → koin bisa pulih; "trades" = order penutup (bukan fill); fee entry ikut net; gagal ambil state → exit 1. |
| `defi91_health.py` | Cek sintaks `doddy_engine.py`; cek sumber CVD spot; **pause-aware** via `~/.defi91_trader_paused`; masalah → exit 1 (dulu 0). |
| `defi91_trader.sh` | Disamakan dgn versi runtime (heartbeat hanya setelah sukses, exit code diteruskan) + `export DEFI91_STRATEGY`, pola laporan `🧠 DNA`. |
| `defi91_momentum.py` | Horizon 1h/30m benar (closes[-13]/[-7]); dedupe harian WIB & reset sebelum loop; kontrak satuan funding jelas. |
| `refresh_dashboard.py` | `closed_trades` = 60 **terbaru** (dulu 60 tertua), urutan naik sesuai `index.html`. |
| `telegram_signals.py`, `telegram_reporter.py`, `weekly_insights.py` | Hapus fallback token/chat-id hardcoded. |
| `tests/` (baru) | 23 tes offline (pytest). |
| `research/backtest/` (baru) | Pengunduh data publik + harness backtest + hasil. |
| `docs/DODDY_DNA.md` (baru) | Konsep, bukti, batas. |

## 2. Bukti yang benar-benar saya jalankan (sandbox Claude, 23–24 Nov 2026)
```
python3 -m py_compile doddy_engine.py github_bot_v3.py defi91_eval.py defi91_health.py \
    defi91_momentum.py refresh_dashboard.py telegram_*.py weekly_insights.py   -> OK
bash -n defi91_trader.sh                                                      -> OK
python3 -m pytest -q tests/                                                   -> 23 passed
# mutation check: kembalikan bug smart-exit -> test_smart_exit_sign_fixed GAGAL (benar)
HYPERLIQUID_DRY_RUN=1 python3 github_bot_v3.py   (tanpa key, data live)       -> jalan; semua koin WNS
HOME=<tmp> python3 defi91_eval.py   (baca-saja, data akun live)               -> exit 0
python3 -I research/backtest/backtest.py <repo> <data>                        -> lihat RESULTS_2026-11-23.txt
```
Snapshot akun live (23 Nov 17:20 UTC, baca publik): **ekuitas perp $41,49, 0 posisi terbuka**
(posisi BTC besar lama sudah tertutup; net 30 hari +$21,54). Baseline di `CLAUDE.md` §7 ($58,
BTC ~97% margin) **sudah usang** — mohon diperbarui.
Dry-run 24 Nov 00:16 WIB: semua koin `bias=0 → WNS`, konsisten dengan shadow observer
(15m/1h UP, 4h DOWN = UNCLEAR).

## 3. Rencana cron (urut, satu job satu langkah — JANGAN resume semuanya sekaligus)

| Job | Status | Tindakan Hermes |
|---|---|---|
| `3bd4537eedd9` monitor posisi | aktif | Biarkan. |
| `3fe9004c1c36` shadow trend observer | aktif | Biarkan — jadi pembanding independen bias DNA. |
| **BARU** "DeFi91 DNA shadow (dry-run)" | — | Buat: tiap **60m**, `no_agent=true`, `deliver=local`, perintah: `cd /data/workspace/defi91-trading-bot && HYPERLIQUID_DRY_RUN=1 DEFI91_STRATEGY=doddy .venv/bin/python github_bot_v3.py`. Tidak butuh key. Jalankan **≥ 14 hari**, simpan log keputusan. |
| `452f9af139d1` health watchdog | paused | Setelah sync: `touch ~/.defi91_trader_paused` (trader masih pause), lalu resume. Ia kini memberi tahu bila Binance spot tak terjangkau. |
| `98425d29e177` self-eval | paused | Resume **bersama** trader nanti (bukan sekarang). Override lama `remove=[DOGE,XRP,LTC,ADA]` (31 Agu) akan dihitung ulang dgn jendela 30 hari. |
| `a57ba0f512e0` trader live | paused | **Jangan resume** sebelum gerbang §4 lulus. Saat resume: `rm ~/.defi91_trader_paused`. |
| `b1004aed4148` flow detector | paused | Opsional sebagai alert saja (bug satuan/dedupe sudah diperbaiki). Tidak terhubung ke keputusan trader. |
| `e889d78e75e3` dashboard sync | paused | **Jangan resume apa adanya**: `git reset --hard` + push `gh-pages`, dan berebut dengan workflow `trading_journal.yml` yang juga deploy gh-pages. Pilih satu produsen dulu. |

Langkah sync (setelah review & merge oleh Hermes):
1. Di `/data/workspace/defi91-trading-bot`: fetch branch ini, cek `git diff`, merge — **tanpa**
   `reset --hard` (working tree runtime ada perubahan lokal, lihat handoff 23 Nov §3).
2. `cp defi91_trader.sh defi91_eval.py defi91_health.py defi91_momentum.py /data/scripts/` dan
   ke `/data/.hermes/scripts/` (sesuai CLAUDE.md §2). Verifikasi `sha256sum` sama.
3. Dari host Hermes uji: `curl -s "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1"`.
   Di sandbox Claude endpoint ini **bisa**, sedangkan `fapi.binance.com` **diblokir geo**.
   Bila host Hermes juga terblokir → otak DNA akan fail-closed (tidak entry, hanya kelola posisi).
4. `.venv/bin/python -m pytest -q tests/` di host (venv Python 3.14) → harus 23 passed.

## 4. Gerbang sebelum trader live di-resume
- [ ] Shadow dry-run ≥ 14 hari tanpa crash/Traceback; minimal 20 keputusan OPEN/ADD tercatat.
- [ ] Hasil shadow (hitung ulang dgn harga 1h berikutnya) tidak negatif; bila negatif → tahan.
- [ ] Sumber CVD spot terjangkau dari host.
- [ ] Token Telegram lama dicabut, token baru hanya di env host.
- [ ] Bos Karman menyetujui resume (job `a57ba0f512e0` saja).

## 5. Keputusan parameter yang saya ubah (flag sesuai CLAUDE.md §3)
- Gate tren DNA: ADX 1h ≥ **20** sebagai pemicu dalam tren HTF (legacy tetap `ADX_MIN_TREND=25`).
  Alasan: entry DNA adalah pullback/kelanjutan di dalam tren 4h; ADX 1h ≥ 25 menyaring entry itu.
- **Scale-in tetap DIBOLEHKAN sampai cap 15%** (keputusan pemilik dipertahankan, tidak ada
  anti-pyramiding penuh), dengan syarat tambahan dari DNA Doddy: hanya menambah posisi yang
  **sudah profit +1 ATR**. Posisi lama pemilik tetap "dibiarkan bekerja" (tidak ditutup strategi).
- `MARGIN_PER_TRADE`, leverage 5x, `MAX_OPEN_POSITIONS=3`, `LIQ_SAFETY_PCT=12`, kill-switch 4%: **tidak diubah**.

## 6. Keamanan — wajib ditindaklanjuti
1. **Cabut token bot Telegram** yang pernah tertanam di `telegram_signals.py`,
   `telegram_reporter.py`, `weekly_insights.py` (riwayat git publik). Buat token baru, simpan di
   env host saja. (Saya tidak mencetak nilainya di dokumen ini.)
2. Workflow `trading_journal.yml` deploy dengan `publish_dir: .` → seluruh repo ikut ke gh-pages.
   Pertimbangkan allowlist file.
3. Jangan pernah menaruh `HYPERLIQUID_PRIVATE_KEY` di workflow GitHub atau frontend.

## 7. Risiko tersisa (jujur)
- Edge belum signifikan statistik (t ≈ 1,3). Shadow wajib.
- Posisi agregat per simbol: bila pemilik membuka posisi manual di koin yang sama dengan posisi
  bot, Hyperliquid menggabungkannya; exit DNA lalu menutup gabungan itu. Saran: akun/subaccount
  terpisah untuk bot.
- Funding belum masuk perhitungan; ledger lengkap (entry fee/funding/transfer) belum ada.
- AUTO-SL masih mengandalkan deteksi `orderType` berisi "stop" tanpa verifikasi ukuran/sisi penuh.
