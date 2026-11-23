"""Unduh data publik baca-saja untuk backtest DeFi91 (tanpa key, tanpa order).
- Hyperliquid perp candles 1h/4h/1d (candleSnapshot, maks ~5000 bar terakhir)
- Binance spot klines 1h (data-api.binance.vision) termasuk taker-buy volume -> CVD spot
Output: JSON per koin ke folder data (argumen 1).
"""
import json, os, sys, time, urllib.request

OUT = sys.argv[1]
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "LTC"]
HL = "https://api.hyperliquid.xyz/info"
BN = "https://data-api.binance.vision/api/v3/klines"
MS = {"1h": 3600_000, "4h": 4 * 3600_000, "1d": 86400_000}


def post(payload):
    req = urllib.request.Request(HL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())


def hl_candles(coin, tf, n):
    end = int(time.time() * 1000)
    start = end - n * MS[tf]
    rows = post({"type": "candleSnapshot",
                 "req": {"coin": coin, "interval": tf, "startTime": start, "endTime": end}})
    return [{"t": int(r["t"]), "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]),
             "c": float(r["c"]), "v": float(r["v"])} for r in rows]


def bn_spot_1h(sym, start_ms):
    out, cur = [], start_ms
    while True:
        rows = get(f"{BN}?symbol={sym}&interval=1h&startTime={cur}&limit=1000")
        if not rows:
            break
        for r in rows:
            out.append({"t": int(r[0]), "c": float(r[4]), "v": float(r[5]), "tb": float(r[9])})
        if len(rows) < 1000:
            break
        cur = int(rows[-1][0]) + MS["1h"]
        time.sleep(0.2)
    return out


os.makedirs(OUT, exist_ok=True)
for coin in COINS:
    d = {"coin": coin}
    for tf, n in (("1h", 5000), ("4h", 1500), ("1d", 400)):
        d[tf] = hl_candles(coin, tf, n)
        time.sleep(0.3)
    start = d["1h"][0]["t"] if d["1h"] else int(time.time() * 1000) - 200 * 86400_000
    d["spot1h"] = bn_spot_1h(coin + "USDT", start)
    with open(os.path.join(OUT, f"{coin}.json"), "w") as f:
        json.dump(d, f)
    print(coin, {k: len(v) for k, v in d.items() if isinstance(v, list)})
