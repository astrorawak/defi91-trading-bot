#!/bin/bash
# DeFi91 trader wrapper - jalankan bot v3 LIVE, senyap kecuali ada aksi nyata.
# stdout kosong => cron no_agent diam (TIDAK spam). stdout terisi => pesan dikirim.
cd /data/workspace/defi91-trading-bot || exit 1
OUT=$(.venv/bin/python github_bot_v3.py 2>&1)
EXIT=$?

# Hanya baris AKSI NYATA / ERROR yang layak dilaporkan. Saldo & skip-entry TIDAK dilaporkan (anti-spam).
REPORT=$(printf '%s\n' "$OUT" | grep -E '^\s*EXEC |early close|⛔|Execution error|❌|Traceback|KILL')
if [ -n "$REPORT" ]; then
  printf '%s\n' "$REPORT"
  printf '\n(exit=%s • %s WIB)\n' "$EXIT" "$(.venv/bin/python -c "from datetime import datetime,timezone,timedelta;print(datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M'))" 2>/dev/null || date +%H:%M)"
fi
exit 0
