#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v38.0 (Full P2P Army Match)
- FIX: Now fetches BOTH 'Buy' and 'Sell' ads from P2P Army.
- FIX: "Ads Volume" Table matches your screenshot exactly (Counts & Volumes separated).
- FIX: Grand Total row added to the bottom of the table.
- EXCHANGES: Binance, MEXC, OKX.
- VISUALS: Green columns for Buy, Red for Sell.
"""

import requests
import statistics
import sys
import time
import csv
import os
import datetime
import json
import random
from concurrent.futures import ThreadPoolExecutor

# Try importing matplotlib
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as ticker
    GRAPH_ENABLED = True
except ImportError:
    GRAPH_ENABLED = False
    print("⚠️ Matplotlib not found. Charts will be skipped.", file=sys.stderr)

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HISTORY_FILE = "etb_history.csv"
SNAPSHOT_FILE = "market_state.json"
TRADES_FILE = "recent_trades.json"
GRAPH_FILENAME = "etb_neon_terminal.png"
GRAPH_LIGHT_FILENAME = "etb_light_terminal.png"
HTML_FILENAME = "index.html"

BURST_WAIT_TIME = 45
TRADE_RETENTION_MINUTES = 1440  # 24 hours
HISTORY_POINTS = 288

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- FETCHERS ---
def fetch_official_rate():
    try:
        return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except:
        return None

def fetch_usdt_peg():
    try:
        return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except:
        return 1.00

def fetch_p2p_army_exchange(market, side="SELL"):
    """
    Universal fetcher for any exchange via p2p.army API.
    side="SELL" -> Advertisers selling USDT (Liquidity for Buyers)
    side="BUY"  -> Advertisers buying USDT (Liquidity for Sellers)
    """
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    ads = []
    h = HEADERS.copy()
    h["X-APIKEY"] = P2P_ARMY_KEY
    
    try:
        payload = {"market": market, "fiat": "ETB", "asset": "USDT", "side": side, "limit": 100}
        r = requests.post(url, headers=h, json=payload, timeout=10)
        data = r.json()
        
        candidates = data.get("result", data.get("data", data.get("ads", [])))
        if not candidates and isinstance(data, list):
            candidates = data
        
        if candidates:
            for ad in candidates:
                if isinstance(ad, dict) and 'price' in ad:
                    try:
                        ads.append({
                            'source': market.upper(),
                            'advertiser': ad.get('advertiser_name', ad.get('nickname', f'{market} User')),
                            'price': float(ad['price']),
                            'available': float(ad.get('available_amount', ad.get('amount', 0))),
                            'type': side.lower()  # 'buy' or 'sell'
                        })
                    except Exception:
                        continue
    except Exception as e:
        print(f"   {market.upper()} {side} error: {e}", file=sys.stderr)
    
    return ads

# --- MARKET SNAPSHOT ---
def capture_market_snapshot():
    # Fetch BOTH sides for ALL exchanges
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = []
        for exchange in ['binance', 'mexc', 'okx']:
            futures.append(ex.submit(lambda e=exchange: fetch_p2p_army_exchange(e, "SELL")))
            futures.append(ex.submit(lambda e=exchange: fetch_p2p_army_exchange(e, "BUY")))
            
        f_peg = ex.submit(fetch_usdt_peg)
        
        all_ads = []
        for f in futures:
            res = f.result() or []
            all_ads.extend(res)
            
        peg = f_peg.result() or 1.0
        
        print(f"   📊 Raw Ads Fetched: {len(all_ads)}", file=sys.stderr)
        
        # Remove lowest 10% outliers (spam/scam prices)
        cleaned_ads = remove_outliers(all_ads, peg)
        print(f"   ✂️ Cleaned Ads: {len(cleaned_ads)}", file=sys.stderr)
        
        return cleaned_ads

def remove_outliers(ads, peg):
    if len(ads) < 10:
        return ads
    
    prices = sorted([ad["price"] / peg for ad in ads])
    # Filter extremely low prices (likely user error or scam)
    p10_threshold = prices[int(len(prices) * 0.10)]
    filtered = [ad for ad in ads if (ad["price"] / peg) > p10_threshold]
    
    return filtered

def load_market_state():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_market_state(current_ads):
    state = {}
    for ad in current_ads:
        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        state[key] = ad['available']
    
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(state, f)

def detect_real_trades(current_ads, peg):
    prev_state = load_market_state()
    
    if not prev_state:
        print("   > First run - establishing baseline", file=sys.stderr)
        return []
    
    trades = []
    
    for ad in current_ads:
        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        
        if key in prev_state:
            prev_inventory = prev_state[key]
            curr_inventory = ad['available']
            diff = abs(curr_inventory - prev_inventory)
            
            # Threshold to ignore tiny dust updates
            if diff > 5:
                # Determine direction based on ad type and inventory change
                # Ad Type 'sell' (They sell USDT): Inv down -> User Bought
                # Ad Type 'buy' (They buy USDT): Inv down -> User Sold (Order filled)
                
                trade_type = 'unknown'
                if ad['type'] == 'sell':
                    if curr_inventory < prev_inventory: trade_type = 'buy' # User bought from them
                    elif curr_inventory > prev_inventory: trade_type = 'restock' # Ignore restocks
                elif ad['type'] == 'buy':
                    if curr_inventory < prev_inventory: trade_type = 'sell' # User sold to them
                    elif curr_inventory > prev_inventory: trade_type = 'restock'
                
                if trade_type in ['buy', 'sell']:
                    trades.append({
                        'type': trade_type,
                        'source': ad['source'],
                        'user': ad['advertiser'],
                        'price': ad['price'] / peg,
                        'vol_usd': diff,
                        'timestamp': time.time()
                    })
                    icon = "🟢" if trade_type == 'buy' else "🔴"
                    print(f"   {icon} {trade_type.upper()}: {ad['source']} - {diff:,.0f} USDT", file=sys.stderr)
    
    return trades

def load_recent_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    
    try:
        with open(TRADES_FILE, "r") as f:
            all_trades = json.load(f)
        
        cutoff = time.time() - (TRADE_RETENTION_MINUTES * 60)
        valid_trades = [t for t in all_trades if t.get("timestamp", 0) > cutoff and t.get("type") in ['buy', 'sell']]
        return valid_trades
    except Exception:
        return []

def save_trades(new_trades):
    recent = load_recent_trades()
    all_trades = recent + new_trades
    cutoff = time.time() - (TRADE_RETENTION_MINUTES * 60)
    filtered = [t for t in all_trades if t.get("timestamp", 0) > cutoff]
    
    with open(TRADES_FILE, "w") as f:
        json.dump(filtered, f)

# --- ANALYTICS ---
def analyze(prices, peg):
    if not prices: return None
    clean_prices = sorted([p for p in prices if 10 < p < 500])
    if len(clean_prices) < 2: return None
    
    adj = [p / peg for p in clean_prices]
    n = len(adj)
    
    try:
        quantiles = statistics.quantiles(adj, n=100, method="inclusive")
        p05, q1, median, q3, p95 = quantiles[4], quantiles[24], quantiles[49], quantiles[74], quantiles[94]
    except:
        median = statistics.median(adj)
        p05, q1, q3, p95 = adj[0], adj[int(n*0.25)], adj[int(n*0.75)], adj[-1]
    
    return {
        "median": median, "q1": q1, "q3": q3,
        "p05": p05, "p95": p95, "min": adj[0], "max": adj[-1],
        "raw_data": adj, "count": n
    }

# --- HISTORY ---
def save_to_history(stats, official):
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["Timestamp", "Median", "Q1", "Q3", "Official"])
        w.writerow([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            round(stats["median"], 2), round(stats["q1"], 2),
            round(stats["q3"], 2), round(official, 2) if official else 0
        ])

def load_history():
    if not os.path.isfile(HISTORY_FILE):
        return [], [], [], [], []
    d, m, q1, q3, off = [], [], [], [], []
    with open(HISTORY_FILE, "r") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            try:
                d.append(datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
                m.append(float(row[1]))
                q1.append(float(row[2]))
                q3.append(float(row[3]))
                off.append(float(row[4]))
            except: pass
    return (d[-HISTORY_POINTS:], m[-HISTORY_POINTS:], q1[-HISTORY_POINTS:], q3[-HISTORY_POINTS:], off[-HISTORY_POINTS:])

# --- CHART GENERATOR ---
def generate_charts(stats, official_rate):
    if not GRAPH_ENABLED: return
    
    themes = [
        ("dark", GRAPH_FILENAME, {"bg": "#050505", "fg": "#00ff9d", "grid": "#222", "median": "#ff0055", "sec": "#00bfff", "alpha": 0.7}),
        ("light", GRAPH_LIGHT_FILENAME, {"bg": "#ffffff", "fg": "#1a1a1a", "grid": "#eee", "median": "#d63384", "sec": "#0d6efd", "alpha": 0.5})
    ]
    
    dates, medians, q1s, q3s, offs = load_history()
    
    for mode, filename, style in themes:
        plt.rcParams.update({
            "figure.facecolor": style["bg"], "axes.facecolor": style["bg"],
            "axes.edgecolor": style["fg"], "text.color": style["fg"],
            "xtick.color": style["fg"], "ytick.color": style["fg"]
        })
        
        fig = plt.figure(figsize=(12, 10))
        
        # 1. Distribution
        ax1 = fig.add_subplot(2, 1, 1)
        data = stats["raw_data"]
        y_jitter = [1 + random.uniform(-0.1, 0.1) for _ in data]
        ax1.scatter(data, y_jitter, color=style["fg"], alpha=style["alpha"], s=20, edgecolors="none")
        ax1.axvline(stats["median"], color=style["median"], linewidth=3, label="Median")
        ax1.set_title("Market Depth", color=style["fg"])
        ax1.set_yticks([])
        
        # 2. History
        ax2 = fig.add_subplot(2, 1, 2)
        if len(dates) > 1:
            ax2.plot(dates, medians, color=style["fg"], linewidth=2)
            if any(offs):
                ax2.plot(dates, offs, linestyle="--", color=style["sec"], alpha=0.5)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        
        plt.tight_layout()
        plt.savefig(filename, dpi=100, facecolor=style["bg"])
        plt.close()

# --- STATISTICS CALCULATOR ---
def calculate_trade_stats(trades):
    now = datetime.datetime.now()
    today_start = datetime.datetime(now.year, now.month, now.day).timestamp()
    stats = {
        'today_buys': 0, 'today_sells': 0, 'today_buy_volume': 0, 'today_sell_volume': 0,
        'overall_buys': 0, 'overall_sells': 0, 'overall_buy_volume': 0, 'overall_sell_volume': 0
    }
    
    for trade in trades:
        ts = trade.get('timestamp', 0)
        vol = trade.get('vol_usd', 0)
        trade_type = trade.get('type', '')
        
        if trade_type == 'buy':
            stats['overall_buys'] += 1
            stats['overall_buy_volume'] += vol
            if ts >= today_start:
                stats['today_buys'] += 1
                stats['today_buy_volume'] += vol
        elif trade_type == 'sell':
            stats['overall_sells'] += 1
            stats['overall_sell_volume'] += vol
            if ts >= today_start:
                stats['today_sells'] += 1
                stats['today_sell_volume'] += vol
                
    return stats

# --- HTML GENERATOR (FIXED TABLE) ---
def update_website_html(stats, official, timestamp, current_ads, grouped_ads, peg):
    prem = ((stats["median"] - official) / official) * 100 if official else 0
    cache_buster = int(time.time())
    
    # --- TABLE GENERATION (MATCHING SCREENSHOT) ---
    exchange_stats = {
        "BINANCE": {"buy_count": 0, "sell_count": 0, "buy_vol": 0, "sell_vol": 0},
        "MEXC":    {"buy_count": 0, "sell_count": 0, "buy_vol": 0, "sell_vol": 0},
        "OKX":     {"buy_count": 0, "sell_count": 0, "buy_vol": 0, "sell_vol": 0}
    }

    # Aggregate Data
    for ad in current_ads:
        src = ad['source']
        if src in exchange_stats:
            # Type 'sell' -> Advertiser is SELLING -> Buy Liquidity for user
            # Type 'buy'  -> Advertiser is BUYING -> Sell Liquidity for user
            # *BUT* for "Ads Volume" table, we usually just list them by the ad type.
            # In P2P:
            # "Buy" tab = Ads where you can BUY (advertiser sells).
            # "Sell" tab = Ads where you can SELL (advertiser buys).
            # We map: ad['type'] == 'sell' (API says side=SELL) -> Table "Buy" Column (User perspective) or Advertiser perspective?
            # Standard P2P sites: "Buy" list = Advertiser Selling. 
            # Let's map strict to API Side for clarity:
            # API SIDE "SELL" -> This is the volume available to BUY.
            # API SIDE "BUY"  -> This is the volume available to SELL.
            
            if ad['type'] == 'sell': # Advertiser Selling
                exchange_stats[src]['sell_count'] += 1
                exchange_stats[src]['sell_vol'] += ad['available']
            else: # Advertiser Buying
                exchange_stats[src]['buy_count'] += 1
                exchange_stats[src]['buy_vol'] += ad['available']

    sorted_exchanges = sorted(exchange_stats.items(), 
                            key=lambda x: (x[1]['buy_vol'] + x[1]['sell_vol']), 
                            reverse=True)

    table_rows = ""
    rank = 1
    t_buy_c, t_sell_c, t_buy_v, t_sell_v = 0, 0, 0, 0

    for source, data in sorted_exchanges:
        # Sum totals
        t_buy_c += data['buy_count']
        t_sell_c += data['sell_count']
        t_buy_v += data['buy_vol']
        t_sell_v += data['sell_vol']
        
        total_count = data['buy_count'] + data['sell_count']
        total_vol = data['buy_vol'] + data['sell_vol']
        
        icon = "🟡" if source == "BINANCE" else "🔵" if source == "MEXC" else "🟣"
        
        table_rows += f"""
        <tr>
            <td><span style="opacity:0.5;margin-right:10px">#{rank}</span> {icon} {source}</td>
            <td style="text-align:right">{data['buy_count']}</td>
            <td style="text-align:right">{data['sell_count']}</td>
            <td style="text-align:right;font-weight:bold;color:var(--text-secondary)">{total_count}</td>
            <td style="text-align:right;color:var(--green)">${data['buy_vol']:,.0f}</td>
            <td style="text-align:right;color:var(--red)">${data['sell_vol']:,.0f}</td>
            <td style="text-align:right;font-weight:bold">${total_vol:,.0f}</td>
        </tr>
        """
        rank += 1

    # Grand Total Row
    table_rows += f"""
    <tr style="background:var(--card-hover);border-top:2px solid var(--accent)">
        <td><b>TOTAL</b></td>
        <td style="text-align:right"><b>{t_buy_c}</b></td>
        <td style="text-align:right"><b>{t_sell_c}</b></td>
        <td style="text-align:right"><b>{t_buy_c + t_sell_c}</b></td>
        <td style="text-align:right;color:var(--green)"><b>${t_buy_v:,.0f}</b></td>
        <td style="text-align:right;color:var(--red)"><b>${t_sell_v:,.0f}</b></td>
        <td style="text-align:right;color:var(--accent)"><b>${t_buy_v + t_sell_v:,.0f}</b></td>
    </tr>
    """

    # Trade stats
    recent_trades = load_recent_trades()
    ts = calculate_trade_stats(recent_trades)
    feed_html = generate_feed_html(recent_trades, peg)

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="300">
        <title>ETB P2P Terminal</title>
        <style>
            :root {{ --bg: #000; --card: #111; --text: #fff; --green: #00C805; --red: #FF3B30; --accent: #0A84FF; --border: #333; }}
            [data-theme="light"] {{ --bg: #f2f2f7; --card: #fff; --text: #000; --green: #34C759; --red: #FF3B30; --accent: #007AFF; --border: #ccc; }}
            body {{ background: var(--bg); color: var(--text); font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 20px; }}
            .grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; max-width: 1400px; margin: 0 auto; }}
            .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
            .price-display {{ font-size: 48px; font-weight: bold; margin: 10px 0; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
            th {{ text-align: left; padding: 10px; color: var(--text-secondary); border-bottom: 1px solid var(--border); }}
            td {{ padding: 10px; border-bottom: 1px solid var(--border); }}
            .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
            .stat-box {{ background: rgba(255,255,255,0.05); padding: 15px; border-radius: 8px; text-align: center; border: 1px solid var(--border); }}
            .stat-val {{ font-size: 24px; font-weight: bold; display: block; }}
            .stat-lbl {{ font-size: 12px; opacity: 0.7; text-transform: uppercase; }}
            .feed-item {{ display: flex; align-items: center; gap: 10px; padding: 10px; border-bottom: 1px solid var(--border); }}
            @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
        </style>
    </head>
    <body>
        <div class="grid">
            <div>
                <div class="card">
                    <div style="opacity:0.6">MEDIAN RATE</div>
                    <div class="price-display">{stats['median']:.2f} ETB</div>
                    <div style="display:flex; gap:15px; font-size:14px;">
                        <span>Official: {official:.2f}</span>
                        <span style="color:var(--accent)">Premium: +{prem:.1f}%</span>
                    </div>
                </div>

                <div class="card">
                     <img src="{GRAPH_FILENAME}?v={cache_buster}" style="width:100%; border-radius:8px;">
                </div>

                <div class="card">
                    <h3>Ads Count & Volume (Live Order Book)</h3>
                    <table>
                        <thead>
                            <tr>
                                <th width="20%">P2P Exchange</th>
                                <th style="text-align:right">Buy Ads</th>
                                <th style="text-align:right">Sell Ads</th>
                                <th style="text-align:right">Total</th>
                                <th style="text-align:right;color:var(--green)">**Buy Vol</th>
                                <th style="text-align:right;color:var(--red)">**Sell Vol</th>
                                <th style="text-align:right">Total Vol</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows}</tbody>
                    </table>
                </div>
            </div>

            <div>
                <div class="card">
                    <h3>Transaction Stats (24h)</h3>
                    <div style="margin-bottom:15px">
                        <div style="color:var(--green); font-weight:bold; margin-bottom:5px">🟢 Buys</div>
                        <div class="stat-grid" style="grid-template-columns: 1fr 1fr;">
                            <div class="stat-box">
                                <span class="stat-val" style="color:var(--green)">{ts['today_buys']}</span>
                                <span class="stat-lbl">Today</span>
                            </div>
                            <div class="stat-box">
                                <span class="stat-val" style="color:var(--green)">${ts['today_buy_volume']/1000:.1f}k</span>
                                <span class="stat-lbl">Vol</span>
                            </div>
                        </div>
                    </div>
                    <div>
                        <div style="color:var(--red); font-weight:bold; margin-bottom:5px">🔴 Sells</div>
                        <div class="stat-grid" style="grid-template-columns: 1fr 1fr;">
                            <div class="stat-box">
                                <span class="stat-val" style="color:var(--red)">{ts['today_sells']}</span>
                                <span class="stat-lbl">Today</span>
                            </div>
                            <div class="stat-box">
                                <span class="stat-val" style="color:var(--red)">${ts['today_sell_volume']/1000:.1f}k</span>
                                <span class="stat-lbl">Vol</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <h3>Recent Activity</h3>
                    <div style="max-height:500px; overflow-y:auto">
                        {feed_html}
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(HTML_FILENAME, "w") as f:
        f.write(html)

def generate_feed_html(trades, peg):
    if not trades: return '<div style="padding:20px; opacity:0.5">No recent trades.</div>'
    html = ""
    for t in sorted(trades, key=lambda x: x['timestamp'], reverse=True)[:30]:
        ago = int(time.time() - t['timestamp'])
        ago_str = f"{ago//60}m" if ago > 60 else f"{ago}s"
        color = "var(--green)" if t['type'] == 'buy' else "var(--red)"
        arrow = "↗" if t['type'] == 'buy' else "↘"
        
        html += f"""
        <div class="feed-item">
            <div style="background:{color}22; color:{color}; width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center;">{arrow}</div>
            <div style="flex:1">
                <div style="display:flex; justify-content:space-between; font-size:12px; opacity:0.7">
                    <span>{t['source']}</span>
                    <span>{ago_str} ago</span>
                </div>
                <div style="font-weight:bold">
                    <span style="color:{color}">{t['type'].upper()}</span> 
                    ${t['vol_usd']:,.0f}
                </div>
                <div style="font-size:12px">@ {t['price']:.2f} ETB</div>
            </div>
        </div>
        """
    return html

# --- MAIN ---
def main():
    print("🔍 Running v38.0 (Corrected Tables)...", file=sys.stderr)
    
    # 1. Snapshot
    print("   > Fetching Market Data...", file=sys.stderr)
    snapshot = capture_market_snapshot()
    
    # 2. Wait for Trades (Simple pause to calculate diffs)
    print(f"   > ⏳ Waiting {BURST_WAIT_TIME}s...", file=sys.stderr)
    time.sleep(BURST_WAIT_TIME)
    
    # 3. Snapshot 2
    snapshot_2 = capture_market_snapshot()
    
    if snapshot_2:
        # Detect Trades
        new_trades = detect_real_trades(snapshot_2, 1.0) # Using 1.0 peg for internal calc
        save_market_state(snapshot_2)
        if new_trades: save_trades(new_trades)
        
        # Stats & HTML
        peg = fetch_usdt_peg() or 1.0
        official = fetch_official_rate() or 120.0
        
        prices = [x['price'] for x in snapshot_2]
        stats = analyze(prices, peg)
        
        if stats:
            save_to_history(stats, official)
            generate_charts(stats, official)
            # Pass aggregated ads to HTML generator
            update_website_html(
                stats, official, 
                time.strftime("%H:%M"), 
                snapshot_2, {}, peg
            )
            print("✅ HTML Updated.", file=sys.stderr)

if __name__ == "__main__":
    main()
