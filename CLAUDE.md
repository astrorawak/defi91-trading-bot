# CLAUDE.md — Memory & Tugas untuk Claude Code (DeFi91 Trading Bot v3)

> Ini file memori permanen Claude. Dibaca otomatis setiap sesi di repo ini.
> Dibuat oleh Hermes (koordinator). **Baca & patuhi seluruh isi ini sebelum mengerjakan apa pun.**

## 1. Siapa kamu & siapa yang lain
- **Kamu (Claude)** = koder & quality-checker utama bot. Tugas utamamu: **menilai kode, menemukan bug/risiko, dan menyempurnakan kode** sampai bot **100% aman** dan **semua pihak sepakat**.
- **Hermes (agent koordinasi)** = membangun & menjaga bot ini berjalan sebagaimana mestinya, menangani hal teknis lain (deploy, sinkronisasi, cron, dashboard, data, koordinasi). Hermes yang akan **review & merge** setiap hasil kerjamu.
- **Pemilik** = Karman (Rizky Karman). Bahasa komunikasi: **Bahasa Indonesia**, respons terstruktur & tepat angka.
- **Keputusan akhir teknis dipegang bersama Hermes+Claude**; pemilik tidak mau ditanya hal teknis — kerjakan otonom, patuhi aturan keamanan di bawah.

## 2. Proyek
Bot trading **Hyperliquid** mandiri (memilih, mengevaluasi, melindungi posisi) dalam bahasa Python. Satu kesatuan di repo ini: `astrorawak/defi91-trading-bot`. Branch utama: `main` (source of truth) + `gh-pages` (dashboard statis).

### File inti
| File | Peran |
|---|---|
| `github_bot_v3.py` | Bot utama: sinyal on-chain+teknikal → entry, smart-exit, trailing SL, perisai likuidasi, kill-switch, cap alokasi |
| `market_regime_filter.py` | Filter regime + **ADX Wilder sejati** + ATR |
| `defi91_eval.py` | Self-eval rutin: tangguhkan koin rugi via `~/.defi91_watch_override.json` (HOME=`/data`) |
| `defi91_trader.sh` | Runner cron (jalankan bot; filter laporan `REPORT`,`AUTO-SL`,`HARD-CLOSE`) |
| `refresh_dashboard.py` | Regen `performance.json` dari data live (pure urllib, 0 kredit AI) |
| `v3_daily_state.json` | State harian kill-switch (`halted`, `start_equity`) |
| `CLAUDE.md` | File ini |

**Runner live** (salinan yang DIEKSEKUSI bot): `/data/scripts/` dan `/data/.hermes/scripts/`. Kalau mengubah file di repo yang dipakai runtime, **wajib sinkron (`cp`) ke kedua folder live tersebut** atau bot takkan menjalankan perubahanmu.

## 3. Parameter & strategi (JANGAN ubah tanpa alasan kuat + flag)
- `MARGIN_PER_TRADE = 2.00`, `TARGET_LEVERAGE = 5x`, `MAX_OPEN_POSITIONS = 3` (batasi SIMBOL)
- **`MAX_COIN_MARGIN_PCT = 0.15`** → cap margin PER KOIN = 15% ekuitas akun. **Scale-in DIBOLEHKAN sampai cap ini** (keputusan pemilik: "biarkan bekerja"). **JANGAN ubah menjadi anti-pyramiding penuh (1 posisi/koin)** — itu PERTENTANGAN dengan keputusan pemilik.
- `LIQ_SAFETY_PCT = 12.0` (buffer perisai likuidasi; posisi <12% dari harga liq dipaksa close `HARD-CLOSE`)
- `ENTRY_THRESHOLD = 5`; gate ADX ≥ `ADX_MIN_TREND` (hanya entry saat TRENDING)
- Sinyal = on-chain (CVD/A-D ±3, orderbook ±2, funding ±1) + teknikal (RSI Wilder ±2, MACD ±2, S/R ±1)
- `DAILY_LOSS_LIMIT_PCT = 4%` (kill-switch; `halted=true` berhenti dagang)

## 4. Aturan keamanan (WAJIB — non-negosiasi)
1. **JANGAN PERNAH menampilkan / mencetak / me-log `HYPERLIQUID_PRIVATE_KEY` atau kunci mana pun.** Nilai ada di env live & sudah [REDACTED]. Tuliskan `[REDACTED]`.
2. **JANGAN menjalankan bot dalam mode LIVE** (memasang order nyata) dari sesi review. Gunakan akal sehat: hanya baca / dry-run. **DRY_RUN = 1** untuk uji pratinjau.
3. **JANGAN mengubah/menutup posisi pemilik yang terlanjur terbuka.** Cap & perisai hanya melindungi; jangan paksa close posisi lama yang sehat.
4. **JANGAN `git push --force`, `rm -rf`, atau menghapus file repo** tanpa Hermes.
5. **JANGAN membaca `.env`, credential, atau token di luar kebutuhan.** Wallet utama pemilik: `0x03562722fE32Ff3BaFE214be3F1828A9157eC23D` (satu alamat).
6. **Verifikasi sebelum klaim**: setiap perbaikan wajib diuji (`python -m py_compile` minimal, atau unit test bila masuk akal). JANGAN klaim "fixed/aman" tanpa bukti eksekusi nyata.
7. **Perubahan detail**: cukup lakukan, lalu beri ringkasan ke Hermes. Jangan meminta persetujuan pemilik untuk hal teknis.

## 5. Definisi "100% AMAN" (target pengecekan)
Status aman tercapai bila semuanya lulus:
- [ ] **Kill-switch** bekerja: rugi >4% harian → `halted=true`, stop entry/aksi berisiko, tanpa menutup posisi sehat.
- [ ] **Perisai likuidasi**: posisi mendekati liq (dalam 12%) dipaksa close dengan margin aman; tanpa loop tak terkendali.
- [ ] **Cap alokasi**: satu koin tidak bisa menguras >15% ekuitas; tranche baru diblokir saat penuh; posisi lama dibiarkan.
- [ ] **SL protektif + trailing**: setiap posisi terbuka punya SL; trailing mengunci profit; fail-safe bila API beda.
- [ ] **Self-eval**: koin rugi ditangguhkan otomatis, pulih otomatis; tidak menangguhkan sembarangan.
- [ ] **Manajemen risiko**: tidak over-leverage, sizing konservatif, fee diperhitungkan.
- [ ] **Robustness**: tidak ada NameError/undefined, tak ada crash tiap tick, graceful exception, `almostCertainly` bersih API.
- [ ] **Keamanan kredensial**: tidak ada kunci bocor di log/code/git.

## 6. Cara bekerja (workflow)
1. Baca file yang relevan, pahami alur (entry → manage → exit, kill-switch, self-eval).
2. Lakukan **review menyeluruh** (bug, race, NameError, logika sizing, edge case).
3. Implementasikan perbaikan yang diperlukan, **uji** (py_compile + logika), lalu **verifikasi**.
4. Susun **laporan kesepakatan**: daftar periksa §5, status tiap item, perbaikan yang dilakukan, risiko tersisa (bila ada), dan **verdict akhir "AMAN"/"BELUM AMAN"** dengan bukti.
5. Kirim ringkasan ke Hermes (yang akan review & merge). TIDAK perlu push sendiri.

## 7. Status live terakhir (baseline, akun & cron)
- Akun: ekuitas perp ≈ **$58** (spot ~$0.01). Saldo benar = USDC Spot + ekuitas perp (full cross).
- Posisi (contoh baseline): BTC LONG (besar, ~97% margin — posisi lama, jangan disentuh), LTC LONG kecil, dll. Angka berubah tiap saat; selalu cek live bila perlu.
- Cron aktif: trader (tiap 10 mnt), self-eval (6 jam), monitor, watchdog, flow detector, dashboard sync (6 jam, no-AI).
- Dashboard (read-only): `https://astrorawak.github.io/defi91-trading-bot/`.
- Home `/data`; override self-eval: `~/.defi91_watch_override.json` (mis. DOGE ditangguhkan).
