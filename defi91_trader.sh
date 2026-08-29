#!/bin/bash
# DeFi91 trader wrapper - jalankan bot v3 LIVE, senyap kecuali ada aksi nyata.
# stdout kosong => cron no_agent diam (TIDAK spam). stdout terisi => pesan dikirim.
# Menulis heartbeat (jejak) tiap jalan => defi91_health.py tahu mesin masih hidup.
cd /data/workspace/defi91-trading-bot || exit 1
# Kunci-jalan: cegah dua invokasi tumpang tindih (mis. bila kedua salinan live
# trader.sh di /data/scripts & /data/.hermes/scripts terjadwal cron bersamaan -
# keduanya cd ke repo yang sama & jalankan skrip+state yang sama). Non-blocking:
# kalau siklus sebelumnya masih jalan, lewati diam-diam (bukan error) drpd
# menumpuk order/perhitungan ganda pada akun nyata yang sama.
LOCKFILE="/data/workspace/defi91-trading-bot/.defi91_trader.lock"
exec 9>"$LOCKFILE"
flock -n 9 || exit 0
HEARTBEAT="$HOME/.defi91_heartbeat.json"
python3 - "$HEARTBEAT" <<'PY'
import json,sys,os
from datetime import datetime,timezone,timedelta
hb=sys.argv[1]
os.makedirs(os.path.dirname(hb),exist_ok=True)
json.dump({"ts":datetime.now(timezone.utc).isoformat(),
           "wib":datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")},
          open(hb,"w"))
PY
OUT=$(.venv/bin/python github_bot_v3.py 2>&1)
EXIT=$?

# Hanya baris AKSI NYATA / ERROR yang layak dilaporkan. Saldo & skip-entry TIDAK (anti-spam).
REPORT=$(printf '%s\n' "$OUT" | grep -E '^\s*EXEC |early close|AUTO-SL|HARD-CLOSE|HARD CLOSE|Trailing SL|⚠ trailing|close err|⛔|Execution error|❌|Traceback|KILL|HALTED|Self-eval:')
if [ -n "$REPORT" ]; then
  printf '%s\n' "$REPORT"
  printf '\n(exit=%s • %s WIB)\n' "$EXIT" "$(.venv/bin/python -c "from datetime import datetime,timezone,timedelta;print(datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M'))" 2>/dev/null || date +%H:%M)"
fi
exit 0
