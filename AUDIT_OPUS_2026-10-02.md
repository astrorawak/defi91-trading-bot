# Audit Independen DeFi91 v3 — Penilaian Kedua (2 Oktober 2026)

**Untuk:** Karman & Hermes · **Dasar:** handoff `DEFI91-HANDOFF-OPUS-5.5-2026-10-02.md` + pembacaan source langsung.
**Source yang diaudit:** branch `main` @ `223c9a5` (commit `5a42b97` yang dirujuk handoff **tidak ada** di GitHub, kemungkinan hanya ada di checkout lokal `/data/workspace`; hash file inti perlu dicocokkan Hermes sebelum merge).
**Batasan:** container audit **tidak bisa menjangkau** `api.hyperliquid.xyz` (diblokir kebijakan jaringan) → tidak ada pembacaan saldo/posisi/fills live, tidak ada uji testnet. Tidak ada order, tidak ada kunci yang dibaca. Semua klaim "terverifikasi" di bawah = dibuktikan dengan tes offline (mock `Info`/`Exchange`) yang bisa dijalankan ulang: `python3 -m unittest discover -s tests -v`.

---

## 1. Verdict

### **TIDAK SIAP LIVE.** Status setelah patch: **belum SIAP SHADOW, tinggal 4 syarat lagi** (lihat §6)

- 3 dari 4 P0 Hermes **terkonfirmasi**, dan saya menemukan versi P0 #1 yang **lebih parah** dari temuan Hermes (lihat T1). Ketiganya sudah dipatch + diuji di branch `claude/new-session-5z1fbu` (commit `7d3e077`), **tetapi belum di-deploy** ke `/data/scripts` dan `/data/.hermes/scripts`, dan belum diuji di testnet.
- P0 #4 (read-back proteksi setelah entry) **masih terbuka**.
- **Temuan baru (keamanan kredensial): token bot Telegram ter-hardcode** di `telegram_signals.py`, `telegram_reporter.py`, dan `weekly_insights.py` (baris 7) dan tercatat di riwayat git. Sudah dihapus dari kode, **tetapi token wajib dicabut (revoke) di @BotFather**, karena riwayat git tetap memuatnya. Item §5 "Keamanan kredensial" = **GAGAL** sampai token dirotasi.
- **Strategi: tidak ada bukti edge setelah biaya.** Data yang ada konsisten dengan ekspektasi negatif, tetapi sampelnya terlalu kecil untuk menyimpulkan apa pun dengan yakin (lihat §4).
- Membiarkan trader tetap **dijeda** adalah keputusan yang benar saat ini.

---

## 2. Tabel temuan

Nomor baris "lama" = `223c9a5`. Status: **T** = terverifikasi oleh tes/reproduksi, **K** = terverifikasi dengan membaca kode, **D** = dugaan yang perlu payload/testnet nyata.

| # | Temuan | Bukti | Risiko uang | Tindakan | Prioritas | Status |
|---|---|---|---|---|---|---|
| T1 | **TP berukuran penuh memblokir AUTO-SL.** `ensure_protective_sl` menjumlahkan *semua* order reduce-only sisi berlawanan (termasuk TP) sebagai "kapasitas terpakai". Bila TP = ukuran posisi, fungsi berhenti dengan pesan "TP-ladder penuh" → **posisi tanpa SL**. Ini terjadi bahkan dengan payload string asli API (`"Take Profit Market"`), bukan hanya bentuk dict. Asumsi "SL tak bisa ditumpuk" juga dibantah kode bot sendiri: `execute_trade` memasang TP *dan* SL masing-masing berukuran penuh. | lama `:575-600`; reproduksi pada kode lama: `TP-string ukuran penuh -> SL dipasang? False` | Tinggi: bila kaki SL batch ditolak/terhapus sementara TP masih resting, posisi berleverage tidak punya SL dan sistem melaporkannya sebagai "bukan error" | Dipatch: hanya order STOP yang dihitung; sisa ukuran yang tidak tertutup SL dipasangi SL | **P0** | T, diperbaiki |
| T2 | TP berbentuk dict `{"trigger":{"tpsl":"tp"}}` dianggap SL (temuan Hermes #1) | lama `:545-546,589-591` | Sama dengan T1 | Dipatch: dict hanya dihitung bila `tpsl=="sl"` | P0 | T, diperbaiki. *Koreksi:* menurut dokumentasi API, `frontendOpenOrders` mengembalikan `orderType` sebagai **string**, jadi cabang dict ini hampir pasti tidak pernah aktif di produksi. Dampak nyata ada di T1. |
| T3 | Stop di **sisi yang salah** (mis. stop BUY pada posisi LONG) dihitung sebagai SL | lama `:545,589` tanpa cek sisi | Sedang | Dipatch: SL wajib sisi berlawanan | P0 | T, diperbaiki |
| T4 | **Kill-switch fail-open** (temuan Hermes #2): JSON korup → `{}` → baseline dibuat ulang dari ekuitas sekarang | lama `:425-430,443-445`; reproduksi: `state korup -> halted? False, baseline baru: 90.0` | Tinggi: rugi sebelum file rusak terlupakan, batas 4% bisa terlewati | Dipatch: state korup/bukan objek, `start_equity` ≤0, API gagal, atau `accountValue`≤0 → **halted** (hanya memblokir entry; manajemen posisi tetap jalan). Penulisan state atomik (tmp+`os.replace`). | P0 | T, diperbaiki |
| T5 | **Exception tak tertangkap mematikan seluruh siklus, termasuk perlindungan.** `check_kill_switch` → `info.user_state` (lama `:439`) dan `manage_open_positions` → `user_state` (lama `:701`) tidak dibungkus try. Error pada satu koin di loop manajemen menghentikan perlindungan koin lain. Error di loop entry membuat manajemen posisi dilewati. | baca kode; tes `test_one_coin_error_does_not_stop_others`, `test_entry_crash_still_runs_management` | Tinggi: satu timeout API = perisai likuidasi, SL, dan trailing tidak jalan pada siklus itu | Dipatch: isolasi per posisi, entry dibungkus, manajemen **selalu** jalan, `main()` return 2 bila ada error proteksi | P0 (baru) | T, diperbaiki |
| T6 | Heartbeat sukses semu (temuan Hermes #3) | `defi91_trader.sh:15-33` | Sedang | Dipatch: penanda `~/.defi91_last_ok.json` hanya ditulis bila exit 0; output dilaporkan bila exit≠0 walau tak cocok regex; `defi91_health.py` memeriksa usia siklus sukses terakhir | P0 | K, diperbaiki. *Koreksi:* regex lama **sudah** memuat `Traceback` dan `❌`, jadi crash Python yang tidak tertangkap sebenarnya terlihat. Celahnya ada pada error yang ditelan (nilai netral), proses yang dibunuh tanpa output, dan semantik heartbeat. Wrapper tetap `exit 0` karena perilaku scheduler Hermes terhadap exit≠0 belum diketahui. |
| T7 | Validasi proteksi batch/fill (temuan Hermes #4): tidak ada read-back SL setelah entry. `tp_set`/`sl_set` hanya mengenali `{"resting":..}`, padahal status kaki anak `normalTpsl` kemungkinan string (`"waitingForTrigger"`), sehingga nilainya selalu False dan tidak pernah dipakai | `:534-547` | Tinggi | **Belum diperbaiki.** Rancangan: setelah `filled`, baca `frontendOpenOrders` dan pastikan ada SL reduce-only ≥ ukuran posisi. Bila tidak ada, panggil `ensure_protective_sl` saat itu juga; bila tetap gagal, `market_close` + alarm. Semantik `normalTpsl` (ukuran anak saat fill parsial, nasib anak bila IOC tidak terisi) **wajib diverifikasi di testnet**. | **P0** | D, terbuka |
| T8 | Harga fallback basi (temuan Hermes #5): bila harga live tidak ada, `mid = entry` dipakai untuk perisai likuidasi **dan** AUTO-SL (SL yang dihitung dari harga entry bisa langsung tersulut) | lama `:710` | Sedang | Dipatch: tanpa harga live, tidak ada keputusan hard-close/AUTO-SL; error dilaporkan | P1 | T, diperbaiki. *Koreksi kecil:* `universe[i].midPx` tidak ada di respons `metaAndAssetCtxs`, jadi harga yang efektif dipakai = `markPx` (ini wajar). |
| T9 | Hard-close gagal → `continue` → SL protektif tidak dipastikan | lama `:724-728` | Sedang | Dipatch: bila close gagal, lanjut memastikan SL | P1 | K, diperbaiki |
| T10 | Ukuran AUTO-SL tidak dibulatkan ke `szDecimals` | lama `:609` | Rendah–sedang (order ditolak) | Dipatch: `round_size` | P1 | K, diperbaiki |
| T11 | **Token bot Telegram ter-hardcode** sebagai default `os.getenv` | 3 file, baris 7; riwayat git | Tinggi untuk keamanan (bot bisa dibajak/dipakai spam; *chat ID* juga terekspos) | Dipatch di kode. **Wajib:** revoke token di @BotFather, buat token baru, simpan hanya di env/secret | **P0 keamanan** | K, diperbaiki sebagian (rotasi = tugas manusia) |
| T12 | **Smart-exit (skor ±7) dan AUTO-SL bertindak pada SEMUA posisi di wallet**, termasuk posisi manual/lama pemilik | `_manage_one_position` | Sedang: bertentangan dengan aturan CLAUDE.md #3 ("jangan paksa close posisi lama yang sehat") | **Butuh keputusan**: kelola hanya posisi yang dibuka bot (simpan `cloid`/registry), atau batasi posisi manual ke SL protektif + perisai likuidasi saja | P1 | K, terbuka |
| T13 | Minimum nilai order $10 di Hyperliquid: `round_size` bisa membulatkan notional $10 ke bawah (contoh BTC @120.000: 0,0000833 → 0,00008 = $9,6) → entry ditolak | `:503` | Rendah (entry gagal, bukan rugi) | Bulatkan ke atas sampai ≥ $10,5, atau tolak dengan log | P1 | D (aturan min $10 perlu dikonfirmasi pada payload error nyata) |
| T14 | Default **live** (`HYPERLIQUID_DRY_RUN` default `0`) | `:89`, runner `:24` | Sedang | Usul: wajibkan `HYPERLIQUID_LIVE=1` eksplisit di runner produksi; tanpa itu = dry-run | P1 | K, terbuka (belum diubah agar runner Hermes tidak rusak diam-diam) |
| T15 | Self-eval **tidak bisa memulihkan** koin yang ditangguhkan: koin off tidak menghasilkan fill baru, jadi net kumulatifnya negatif selamanya. Klaim CLAUDE.md §5 "pulih otomatis" **tidak benar**. Ditambah: `userFills` hanya mengembalikan 2.000 fill terbaru (parameter `startTime` diabaikan; seharusnya `userFillsByTime`), ambang "≥3 fill" menghitung fill parsial, override ditulis non-atomik, dan bila override gagal dibaca bot fail-open ke watchlist penuh | `defi91_eval.py:58,155-186`; `github_bot_v3.py:42-46` | Rendah–sedang | Jendela bergulir per round-trip (mis. 30 hari / ≥10 round-trip), masa tangguh berbatas (mis. 14 hari lalu masuk ulang dengan ukuran percobaan), tulis atomik | P2 | K, terbuka |
| T16 | Kill-switch dirancukan deposit/penarikan intraday (ada deposit 19,02 USDC pada 19 Agu 07:33 UTC, di dalam periode v3, menurut `defi91_transfer_audit.md`) | `check_kill_switch` | Rendah–sedang (rugi tertutupi deposit / halt palsu saat withdraw) | Koreksi baseline dengan `userNonFundingLedgerUpdates` hari itu | P2 | K, terbuka |
| T17 | Label "CVD sejati/whale" ≠ implementasi (A/D candle) | `:197-258` | — | Ganti label; validasi nilai sinyal | P2 | K (setuju dengan Hermes) |

Catatan lain: `has_protective_sl` di v3 lama adalah **kode mati** (tidak dipanggil), sudah diganti helper `find_sl_orders`. Konstruktor `Info()` yang gagal karena jaringan tetap menghentikan siklus. Ini tidak bisa dihindari (tanpa API, manajemen apa pun memang tidak mungkin), dan tetap dilaporkan lewat `Traceback`.

---

## 3. Koreksi eksplisit atas audit Hermes

1. **P0 #1 benar arahnya, tetapi lokasi dampaknya keliru.** Bug yang aktif di produksi adalah logika "kapasitas TP-ladder" dan tidak adanya cek sisi (T1, T3), bukan cabang dict (T2). Hermes tidak menyebut T1.
2. **P0 #3 sebagian benar.** `Traceback|❌` sudah ada di regex. Yang benar-benar hilang adalah sinyal "siklus selesai dengan sukses".
3. **Ada P0 yang terlewat oleh Hermes:** T5 (satu exception API mematikan seluruh perlindungan dalam siklus itu) dan T11 (token Telegram bocor).
4. **P1 #5:** soal `midPx`, live price sebenarnya diambil dari `markPx` (aman). Fallback ke entry memang benar bermasalah (T8).
5. Komentar kode "SL diam di harga entry selamanya" keliru (SL awal = entry ∓ 1,5×ATR). Sudah dikoreksi.

---

## 4. Kritik strategi & validitas PnL

**Angka yang ada tidak bisa membuktikan edge, dan condong negatif.**

- Dari `performance.json`: 77 fill penutupan, win rate 29,9%. Interval Wilson 95% ≈ **21%–41%**.
- R:R desain TP 2,5×ATR : SL 1,5×ATR = 1,67 → win rate impas kotor ≈ **37,5%**. Hasil observasi berada di bawah angka itu, tetapi batas atas interval masih mencakupnya. Selain itu, trailing dan early-close mengubah R:R yang terealisasi, sehingga "fill menang" ≠ "R yang direalisasi". Kesimpulan jujurnya: **tidak signifikan, condong negatif.**
- Fee hanya ~20% dari kerugian (1,10 dari 5,38 USDC). **Kerugian terutama berasal dari sinyal, bukan dari biaya.** Gerbang fee (TP ≥ 0,27%) praktis tidak pernah membatasi apa pun, karena 2,5×ATR 1 jam hampir selalu jauh di atas 0,27%.
- **Inkoherensi desain:** entry hanya diizinkan saat TRENDING (ADX>25), tetapi skor memberi poin untuk komponen *mean-reversion*: RSI oversold +2, dekat support +1, dan A/D "akumulasi saat harga datar" +3. Dalam tren turun yang kuat, RSI oversold dan harga dekat support bisa memicu **LONG melawan tren**. MACD (tren) dan RSI/SR (kontra-tren) saling meniadakan, sehingga skor ≥5 sering berarti "sinyal bertentangan yang kebetulan berjumlah 5". Bias ADX≥70 jarang aktif.
- **Atribusi:** fill wallet ≠ hasil algoritme v3 (ada perdagangan manual, transfer 19,02 USDC di periode itu, funding tidak dihitung). Selisih $58 → $138 adalah transfer, bukan profit.
- **Tidak ada dasar statistik untuk mengubah parameter apa pun** (ADX, threshold, multiplier ATR). Menyetel parameter dari 77 fill = overfitting. Rekomendasi saya: **jangan tuning**. Bangun pencatatan keputusan dulu, lalu bandingkan dengan baseline sederhana.

**Ukuran sampel minimum (dasar keputusan, bukan janji profit):** dengan deviasi standar hasil per trade ≈ 1,2R, membuktikan ekspektasi +0,2R/trade pada α=5% butuh ≈ (1,96×1,2/0,2)² ≈ **140 round-trip**, dan untuk +0,1R ≈ **550**. Dengan frekuensi v3 (~40 round-trip/2 minggu), butuh **≥7 minggu shadow** hanya untuk mendeteksi edge yang sudah cukup besar.

---

## 5. Perbaikan yang sudah dilakukan (commit `7d3e077`)

| File | Perubahan |
|---|---|
| `github_bot_v3.py` | `find_sl_orders`/`_is_sl_order` (STOP saja, sisi berlawanan, reduce-only); AUTO-SL menutup sisa ukuran yang tidak tercakup SL, dibulatkan, tidak dipasang buta bila open orders gagal dibaca; trailing memperketat setiap SL per tranche dan memeriksa error per order; kill-switch fail-closed + tulis atomik; isolasi error per posisi; entry dipisah ke `_run_entries`, manajemen selalu jalan; tanpa harga live tidak ada hard-close/AUTO-SL; return code 2 bila ada error proteksi |
| `defi91_trader.sh` | Penanda sukses `~/.defi91_last_ok.json`; laporan saat exit≠0; tetap `exit 0` |
| `defi91_health.py` | Cek usia siklus sukses terakhir |
| `telegram_*.py`, `weekly_insights.py` | Token default dihapus (set `TELEGRAM_BOT_TOKEN` via env) |
| `tests/test_safety_v3.py` | 27 tes offline: TP-only (string/dict), SL string/dict, sisi salah, SL parsial, posisi short, gagal baca order, SL ditolak, trailing tidak pernah melonggarkan, kill-switch (baru/rugi/korup/bukan objek/equity 0/API gagal/hari baru), perisai likuidasi, harga basi, isolasi error, smoke test `main()` dry-run (Exchange tidak pernah dibuat) dan live dengan exchange palsu |

**Bukti:** `py_compile` lulus untuk semua file yang diubah; `bash -n defi91_trader.sh` lulus; `python3 -m unittest discover -s tests` → **27 OK**; skenario T1–T4 ter-reproduksi gagal pada kode lama. **Tidak terbukti:** perilaku pada API nyata/testnet.

**Tugas Hermes saat merge:** (1) cocokkan hash `github_bot_v3.py` lokal `/data/workspace` dengan `223c9a5`, karena commit `5a42b97` tidak ada di GitHub; (2) setelah merge, `cp` ke `/data/scripts/` **dan** `/data/.hermes/scripts/`; (3) `.venv` produksi memerlukan `requests numpy hyperliquid-python-sdk eth-account` (tidak berubah); (4) set `TELEGRAM_BOT_TOKEN` di env cron yang mengirim Telegram; (5) jalankan watchdog dan cek bahwa `last_ok` terbentuk setelah siklus dry-run.

---

## 6. Gerbang keputusan & rencana

**Syarat SIAP SHADOW** (semua wajib):
1. Patch ini direview dan di-merge Hermes, lalu disinkron ke kedua folder live.
2. Token Telegram lama dicabut dan diganti.
3. T7 diimplementasikan (read-back SL setelah entry + kebijakan fail-safe), dengan tes mock.
4. **Log keputusan per siklus** (JSONL): waktu, bid/ask/mark, regime, ADX, skor tiap komponen, alasan skip/entry, harga entry teoretis, SL/TP, versi parameter. Shadow = simulasi fill dari log ini (entry pada ask/bid + slippage, exit saat high/low candle menyentuh SL/TP, fee taker 0,045% per sisi, funding). `DRY_RUN=1` yang hanya mencetak **bukan** shadow.

**Syarat LIVE TERBATAS** (ditetapkan *sebelum* melihat hasil shadow):
- Uji testnet: entry IOC filled / partial / tidak terisi, SL ditolak, modify trailing, `market_close`, dengan payload yang disimpan sebagai fixture.
- ≥140 round-trip shadow (≈7+ minggu), ekspektasi per trade setelah fee+funding+slippage > 0 dengan batas bawah interval kepercayaan 95% > 0, drawdown maksimum shadow < 10% ekuitas, dan mengungguli baseline "tidak trading" dan trend-following sederhana (mis. EMA20/50 4 jam tanpa skor).
- Keputusan T12 (posisi manual) dan T14 (gate live eksplisit) diambil.
- Prosedur stop: pause cron trader + monitor protektif tetap jalan; rollback = `git revert` + `cp`.
- Mulai dengan ukuran minimum, hanya 1–2 koin, dan evaluasi ulang tiap 50 round-trip. **Profit konsisten tidak bisa dijamin.**

**Urutan perbaikan berikutnya:** T7 → T12 → T14 → log keputusan/shadow → T15/T16 → T13 → perbarui README & label CVD.

---

## 7. Pertanyaan yang masih perlu dijawab

1. Apakah hash `github_bot_v3.py` di `/data/workspace` sama dengan `main@223c9a5`? (commit `5a42b97` tidak ada di remote)
2. Contoh payload nyata yang sudah disanitasi: `frontendOpenOrders` (TP & SL), respons `bulk_orders` normalTpsl saat filled / partial / IOC tidak terisi, respons `modify_order`.
3. Apakah pemilik masih membuka posisi manual di wallet yang sama? (menentukan T12)
4. Bagaimana scheduler cron Hermes memperlakukan exit≠0 dan stdout? (menentukan apakah wrapper boleh `exit $EXIT`)
5. Apakah agent wallet/API key Hyperliquid terpisah dari wallet utama (izin trade-only, tanpa withdraw)?
6. Ledger funding + transfer 19 Agu–1 Sep, untuk atribusi PnL v3 yang bersih.
