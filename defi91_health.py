#!/usr/bin/env python3
"""DeFi91 HEALTH watchdog (mesin anti-bug). Jalan tiap ~10 menit via cron no_agent.
Tidak cek risiko dana (itu monitor_positions.py) — ini cek KESEHATAN MESIN:
  - sintaks semua file .py bot valid (anti-bug dari edit)
  - key HYPERLIQUID_PRIVATE_KEY tersedia di env
  - file runner kron ada di /data/scripts/
  - heartbeat trader masih SEGAR (mesin tidak mati)
  - kill-switch tidak keliru (state file valid)
stdout KOSONG kalau sehat (watchdog silent). stdout terisi bila ada yang rusak.
"""
import ast, json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

BOT_DIR = "/data/workspace/defi91-trading-bot"
SCRIPTS_DIR = "/data/scripts"
FILES = ["github_bot_v3.py", "defi91_eval.py", "monitor_positions.py"]
RUNNERS = ["defi91_trader.sh", "defi91_monitor.py", "defi91_eval.py"]
HEARTBEAT = os.path.expanduser("~/.defi91_heartbeat.json")
HEARTBEAT_MAX_AGE_MIN = 25   # trader 10 menit -> 25 menit aman (2x + margin)
WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"

def wibnow():
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

def main():
    problems = []

    # 1) Sintaks semua file .py
    for f in FILES:
        p = os.path.join(BOT_DIR, f)
        if not os.path.exists(p):
            problems.append(f"FILE HILANG: {f}")
            continue
        try:
            ast.parse(open(p).read())
        except SyntaxError as e:
            problems.append(f"BUG SINTAKS: {f} (L{e.lineno}): {e.msg}")

    # 2) Key tersedia
    if not os.environ.get("HYPERLIQUID_PRIVATE_KEY"):
        problems.append("KUNCI HYPERLIQUID_PRIVATE_KEY kosong (cek hPanel Environment)")

    # 3) Runner jar diganti jalur yang django pencari? -> pastikan file ada di /data/scripts
    for r in RUNNERS:
        if not os.path.exists(os.path.join(SCRIPTS_DIR, r)):
            problems.append(f"RUNNER HILANG: /data/scripts/{r}")

    # 4) Heartbeat masih segar -> mesin hidup
    try:
        hb = json.load(open(HEARTBEAT))
        hb_ts = datetime.fromisoformat(hb["ts"])
        age_min = (datetime.now(timezone.utc) - hb_ts).total_seconds() / 60
        if age_min > HEARTBEAT_MAX_AGE_MIN:
            problems.append(f"MESIN MATI: trader tak jalan {age_min:.0f} menit (heartbeat basi)")
    except FileNotFoundError:
        problems.append("MESIN BELUM PERNAH JALAN: tidak ada heartbeat")
    except Exception as e:
        problems.append(f"HEARTBEAT korup: {e}")

    # 5) Kill-switch state file valid (kalau ada)
    ks = os.path.join(BOT_DIR, "v3_daily_state.json")
    if os.path.exists(ks):
        try:
            st = json.load(open(ks))
            if not isinstance(st, dict):
                problems.append("STATE kill-switch korup (bukan objek)")
        except Exception:
            problems.append("STATE kill-switch korup (tak bisa dibaca)")

    # 6) Sansekata: pastikan API Hyperliquid bisa dijangkau (network OK)
    try:
        r = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                   data=b'{"type":"meta"}',
                                   headers={"Content-Type": "application/json"})
        urllib.request.urlopen(r, timeout=15)
    except Exception as e:
        problems.append(f"API Hyperliquid TAK TERJANGKAU: {e}")

    if problems:
        print("🩺 [DEFI91-HEALTH] masalah ditemukan:\n  - " + "\n  - ".join(problems))
        print(f"(cek: {wibnow()} WIB)")
        return 0
    # sehat -> diam
    return 0

if __name__ == "__main__":
    sys.exit(main())
