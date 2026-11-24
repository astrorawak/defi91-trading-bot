#!/bin/bash
# DeFi91 trader wrapper - jalankan bot v3 LIVE, senyap kecuali ada aksi nyata.
# stdout kosong => cron no_agent diam (TIDAK spam). stdout terisi => pesan dikirim.
# Heartbeat hanya sesudah siklus sukses; kegagalan harus tampak di status cron.
# (Disamakan dgn salinan runtime Hermes /data/scripts per handoff 23 Nov 2026,
#  + pola laporan aksi otak DNA Doddy.)
cd /data/workspace/defi91-trading-bot || exit 1
# Otak strategi: doddy (default) | legacy (rollback). Lihat docs/DODDY_DNA.md.
export DEFI91_STRATEGY="${DEFI91_STRATEGY:-doddy}"
# Profil risiko (opsional): file kecil ~/.defi91_risk.env, isi dua baris, mis.
#   DEFI91_MARGIN_PER_TRADE=4
#   DEFI91_MAX_COIN_MARGIN_PCT=0.30
# Hanya 2 nama itu yang dibaca (tidak ada eksekusi kode); kode bot memagari nilainya
# ($2..$8 dan 0.15..0.50). Tanpa file -> STANDAR ($2 / 15%).
RISK_FILE="$HOME/.defi91_risk.env"
if [ -f "$RISK_FILE" ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      DEFI91_MARGIN_PER_TRADE|DEFI91_MAX_COIN_MARGIN_PCT)
        export "$k=$(printf '%s' "$v" | tr -cd '0-9.')" ;;
    esac
  done < "$RISK_FILE"
fi
# Kunci-jalan: cegah dua invokasi tumpang tindih (mis. bila kedua salinan live
# trader.sh di /data/scripts & /data/.hermes/scripts terjadwal cron bersamaan).
# Non-blocking: kalau siklus sebelumnya masih jalan, lewati diam-diam.
LOCKFILE="/data/workspace/defi91-trading-bot/.defi91_trader.lock"
exec 9>"$LOCKFILE"
flock -n 9 || exit 0
HEARTBEAT="$HOME/.defi91_heartbeat.json"
OUT=$(.venv/bin/python github_bot_v3.py 2>&1)
EXIT=$?
if [ "$EXIT" -eq 0 ]; then
  python3 - "$HEARTBEAT" <<'PY'
import json,sys,os,tempfile
from datetime import datetime,timezone,timedelta
hb=sys.argv[1]
os.makedirs(os.path.dirname(hb),exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.defi91_hb_',dir=os.path.dirname(hb))
try:
    with os.fdopen(fd,'w') as f:
        json.dump({"ts":datetime.now(timezone.utc).isoformat(),
                   "wib":datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S"),
                   "result":"ok"},f)
        f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600)
    os.replace(tmp,hb)
finally:
    if os.path.exists(tmp):os.unlink(tmp)
PY
  HB_EXIT=$?
  if [ "$HB_EXIT" -ne 0 ]; then EXIT="$HB_EXIT"; fi
fi

# Hanya baris AKSI NYATA / ERROR yang layak dilaporkan. Saldo & skip-entry TIDAK (anti-spam).
REPORT=$(printf '%s\n' "$OUT" | grep -E '^\s*EXEC |🧠 DNA|early close|AUTO-SL|HARD-CLOSE|HARD CLOSE|Trailing SL|⚠ trailing|close err|⛔|Execution error|❌|Traceback|KILL|HALTED|Self-eval:')
if [ -n "$REPORT" ]; then
  printf '%s\n' "$REPORT"
  printf '\n(exit=%s • %s WIB)\n' "$EXIT" "$(.venv/bin/python -c "from datetime import datetime,timezone,timedelta;print(datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M'))" 2>/dev/null || date +%H:%M)"
fi
if [ "$EXIT" -ne 0 ] && [ -z "$REPORT" ]; then
  printf '❌ [DEFI91-TRADER] siklus gagal (exit=%s); heartbeat sukses tidak diperbarui.\n' "$EXIT"
fi
exit "$EXIT"
