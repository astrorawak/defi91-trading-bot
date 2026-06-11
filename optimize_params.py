import json
import os

def load_json(filename):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except:
        return None

def analyze_performance():
    trades_data = load_json("trades.json")
    if not trades_data:
        return
        
    trades = trades_data.get("trades", []) if isinstance(trades_data, dict) else trades_data
    closed_trades = [t for t in trades if isinstance(t, dict) and t.get("status") == "CLOSED"]
    
    if not closed_trades:
        print("Not enough closed trades for analysis.")
        return
        
    # Analyze by coin
    coin_stats = {}
    for t in closed_trades:
        coin = t.get("coin")
        pnl = float(t.get("pnl", 0))
        if coin not in coin_stats:
            coin_stats[coin] = {"trades": 0, "wins": 0, "pnl": 0}
        
        coin_stats[coin]["trades"] += 1
        coin_stats[coin]["pnl"] += pnl
        if pnl > 0:
            coin_stats[coin]["wins"] += 1
            
    print("--- Coin Performance ---")
    for coin, stats in sorted(coin_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        win_rate = (stats["wins"] / stats["trades"]) * 100 if stats["trades"] > 0 else 0
        print(f"{coin}: {stats['trades']} trades | Win Rate: {win_rate:.1f}% | PnL: ${stats['pnl']:.2f}")

if __name__ == "__main__":
    analyze_performance()
