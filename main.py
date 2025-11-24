#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v20.0 (ULTIMATE)
- MERGED: v16 (Charts), v18 (Delta Feed), v19 (CSV History).
- LOGIC: Tracks ad liquidity changes to detect REAL trades.
- OUTPUT: Generates index.html, etb_neon_terminal.png, and etb_p2p_trades.csv.
"""

import requests
import statistics
import sys
import time
import csv
import os
import datetime
import random
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HISTORY_FILENAME = "etb_p2p_trades.csv"
GRAPH_FILENAME = "etb_neon_terminal.png"
HTML_FILENAME = "index.html"
REFRESH_RATE = 15 # Seconds between scans

# Global Caches
AD_CACHE = {}          # Stores previous state of ads to detect trades
PRICE_HISTORY = []     # Stores recent price stats for the chart
TRADES_HISTORY = []    # Stores recent trades for the feed

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

# --- 1. PERSISTENCE (CSV) ---
def init_history_file():
    """Creates the CSV file if missing."""
    if not os.path.isfile(HISTORY_FILENAME):
        with open(HISTORY_FILENAME, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "User", "Action", "Amount_USD", "Price_ETB", "Total_ETB", "Source"])

def save_trade_to_csv(trade):
    """Appends a new trade to history."""
    with open(HISTORY_FILENAME, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            trade['time'].strftime("%Y-%m-%d %H:%M:%S"),
            trade['user'],
            trade['action'],
            f"{trade['amount_usd']:.2f}",
            f"{trade['price']:.2f}",
            f"{trade['total_etb']:.2f}",
            trade['source']
        ])

def load_recent_history():
    """Loads last 50 trades on startup."""
    trades = []
    if os.path.isfile(HISTORY_FILENAME):
        try:
            with open(HISTORY_FILENAME, "r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
                for row in reader[-50:]:
                    trades.append({
                        "time": datetime.datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S"),
                        "user": row["User"],
                        "action": row["Action"],
                        "amount_usd": float(row["Amount_USD"]),
                        "price": float(row["Price_ETB"]),
                        "total_etb": float(row["Total_ETB"]),
                        "source": row.get("Source", "Bybit")
                    })
            trades.reverse()
        except Exception: pass
    return trades

# --- 2. FETCHERS ---
def fetch_usdt_peg():
    try: return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except: return 1.00

def fetch_official_rate():
    try: return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except: return None

def fetch_bybit_ads():
    """Fetches ALL active Bybit ads (Sell & Buy sides) for Delta tracking."""
    url = "https://api2.bybit.com/fiat/otc/item/online"
    ads = []
    # Side 1 = SELL (User buys from them), Side 0 = BUY (User sells to them)
    # We focus on Side 1 (Sellers) to see who is BUYING form them.
    try:
        for page in range(1, 5):
            payload = {
                "userId": "", "tokenId": "USDT", "currencyId": "ETB", "payment": [],
                "side": "1", "size": "20", "page": str(page), "authMaker": False
            }
            r = requests.post(url, headers=HEADERS, json=payload, timeout=5)
            items = r.json().get("result", {}).get("items", [])
            if not items: break
            
            for i in items:
                ads.append({
                    'id': i.get('id', i.get('itemNo')),
                    'price': float(i['price']),
                    'advertiser': i.get('nickName', 'Bybit User'),
                    # 'maxAmount' in Bybit is usually the limit in local currency (ETB)
                    # We convert to USDT inventory roughly
                    'available_usdt': float(i.get('maxAmount', 0)) / float(i['price']),
                    'source': 'Bybit'
                })
            time.sleep(0.1)
    except: pass
    return ads

def fetch_p2p_army_ads(market, side):
    """Fetches Binance/MEXC for pricing stats (not for delta tracking)."""
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    prices = []
    h = HEADERS.copy(); h["X-APIKEY"] = P2P_ARMY_KEY
    try:
        payload = {"market": market, "fiat": "ETB", "asset": "USDT", "side": side, "limit": 100}
        r = requests.post(url, headers=h, json=payload, timeout=10)
        data = r.json()
        candidates = data.get("result", data.get("data", data.get("ads", [])))
        if not candidates and isinstance(data, list): candidates = data
        if candidates:
            for ad in candidates:
                if isinstance(ad, dict) and 'price' in ad: prices.append(float(ad['price']))
    except: pass
    return prices

# --- 3. LOGIC & ANALYSIS ---
def analyze_stats(prices, peg):
    if not prices: return None
    valid = sorted([p for p in prices if 50 < p < 400])
    if len(valid) < 2: return None
    adj = [p / peg for p in valid]
    try:
        median = statistics.median(adj)
        p10 = adj[int(len(adj)*0.1)]
        p90 = adj[int(len(adj)*0.9)]
        return {"median": median, "p10": p10, "p90": p90, "raw_data": adj}
    except: return None

def detect_trades(current_ads):
    global AD_CACHE
    new_trades = []
    current_cache = {}
    
    for ad in current_ads:
        ad_id = ad['id']
        current_amt = ad['available_usdt']
        current_cache[ad_id] = current_amt
        
        if ad_id in AD_CACHE:
            prev_amt = AD_CACHE[ad_id]
            diff = prev_amt - current_amt
            
            # Threshold: > $10 USD change to filter noise/rebalancing
            if diff > 10: 
                new_trades.append({
                    "time": datetime.datetime.now(),
                    "user": ad['advertiser'],
                    "action": "bought",
                    "amount_usd": diff,
                    "price": ad['price'],
                    "total_etb": diff * ad['price'],
                    "source": ad['source']
                })
    
    AD_CACHE = current_cache
    return new_trades

# --- 4. VISUALIZATION (Matplotlib + HTML) ---
def generate_neon_chart(stats, official):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError: return

    # Add current point to history
    now = datetime.datetime.now()
    PRICE_HISTORY.append((now, stats['median']))
    # Keep last 24h points (approx 1440 mins / 15 sec loops... limit to last 100 points for speed)
    if len(PRICE_HISTORY) > 100: PRICE_HISTORY.pop(0)
    
    dates = [x[0] for x in PRICE_HISTORY]
    vals = [x[1] for x in PRICE_HISTORY]

    # Style
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 12))
    fig.patch.set_facecolor('#050505')
    
    # 1. Depth Chart (Scatter)
    data = stats['raw_data']
    y_jit = [1 + random.uniform(-0.1, 0.1) for _ in data]
    ax1.scatter(data, y_jit, color='#00ff9d', alpha=0.6, s=20, edgecolors='none')
    ax1.axvline(stats['median'], color='#ff0055', linewidth=2, label='Median')
    if official: ax1.axvline(official, color='#ffffff', linestyle=':', alpha=0.5)
    ax1.set_title(f"Live Order Depth ({len(data)} Ads)", color='white')
    ax1.set_yticks([])
    ax1.set_facecolor('#050505')
    
    # 2. Trend Chart (Line)
    if len(dates) > 1:
        ax2.plot(dates, vals, color='#00ff9d', linewidth=2)
        ax2.fill_between(dates, vals, alpha=0.1, color='#00ff9d')
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.set_title("Median Price Trend (Live)", color='white')
        ax2.grid(True, color='#222', linestyle='--')
        ax2.set_facecolor('#050505')

    plt.tight_layout()
    plt.savefig(GRAPH_FILENAME, facecolor='#050505')
    plt.close()

def update_html(stats, official, trades, timestamp):
    cache_buster = int(time.time())
    
    # Generate Feed HTML
    feed_html = ""
    if not trades:
        feed_html = "<div style='padding:20px;text-align:center;color:#666'>Scanning liquidity deltas... Waiting for trades...</div>"
    else:
        for t in trades[:15]: # Show last 15
            ts = t['time'].strftime("%I:%M:%S %p")
            icon = "🤑" if t['amount_usd'] > 500 else "🛒"
            bg = "#d29922" if t['amount_usd'] > 500 else "#2ea043"
            
            feed_html += f"""
            <div class="feed-item">
                <div class="feed-icon" style="background-color: {bg};">{icon}</div>
                <div class="feed-content">
                    <span class="feed-ts">{ts}</span> -> 
                    <span class="feed-user">{t['user']}</span> (SELLER) filled 
                    <span class="feed-vol">{t['amount_usd']:,.2f} USDT</span> @ 
                    <span class="feed-price">{t['price']:.2f} ETB</span>
                </div>
            </div>
            """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="15">
        <title>ETB Pro Terminal v20</title>
        <style>
            :root {{ --bg: #050505; --card: #111; --text: #00ff9d; --sub: #ccc; }}
            body {{ background: var(--bg); color: var(--text); font-family: monospace; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; display: grid; gap: 20px; }}
            .card {{ background: var(--card); border: 1px solid #333; border-radius: 10px; padding: 15px; overflow: hidden; }}
            .ticker {{ font-size: 2.5rem; text-align: center; margin: 10px 0; color: #fff; }}
            .subticker {{ font-size: 0.9rem; text-align: center; color: #666; letter-spacing: 2px; }}
            img {{ width: 100%; border-radius: 5px; border: 1px solid #333; }}
            
            .feed-item {{ display: flex; gap: 10px; padding: 10px; border-bottom: 1px solid #222; align-items: center; }}
            .feed-icon {{ width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: #fff; }}
            .feed-content {{ font-size: 0.9rem; color: #ccc; }}
            .feed-user {{ color: #fff; font-weight: bold; }}
            .feed-price {{ color: #ff0055; font-weight: bold; }}
            .feed-ts {{ color: #666; font-size: 0.8rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="subticker">REAL-TIME MARKET MEDIAN</div>
                <div class="ticker">{stats['median']:.2f} ETB</div>
                <div class="subticker">OFFICIAL: {official} | PREM: {((stats['median']-official)/official*100):.1f}%</div>
            </div>
            
            <div class="card">
                <img src="{GRAPH_FILENAME}?v={cache_buster}" alt="Market Chart">
            </div>
            
            <div class="card">
                <div style="border-bottom:1px solid #333; padding-bottom:10px; margin-bottom:10px; font-weight:bold; color:#fff;">
                    ⚡ LIVE LIQUIDITY FEED (DELTA TRACKER)
                </div>
                {feed_html}
            </div>
            
            <div style="text-align:center; color:#666; font-size:0.8rem;">
                Scanning Bybit/Binance/MEXC | Last Update: {timestamp}
            </div>
        </div>
    </body>
    </html>
    """
    with open(HTML_FILENAME, "w", encoding="utf-8") as f: f.write(html)

# --- 5. MAIN LOOP ---
def main():
    print("🚀 ETB Pro Terminal v20 (Ultimate) Running...", file=sys.stderr)
    init_history_file()
    
    # Load history into memory for the feed
    global TRADES_HISTORY
    TRADES_HISTORY = load_recent_history()
    
    while True:
        try:
            # 1. Fetch Data (Threaded)
            with ThreadPoolExecutor(max_workers=5) as ex:
                f_bybit = ex.submit(fetch_bybit_ads)
                f_bin = ex.submit(lambda: fetch_p2p_army_ads("binance", "SELL"))
                f_mexc = ex.submit(lambda: fetch_p2p_army_ads("mexc", "SELL"))
                f_off = ex.submit(fetch_official_rate)
                f_peg = ex.submit(fetch_usdt_peg)
                
                bybit_ads = f_bybit.result()
                bin_prices = f_bin.result()
                mexc_prices = f_mexc.result()
                official = f_off.result() or 0.0
                peg = f_peg.result() or 1.0

            # 2. Analyze Prices (Combine all sources for the chart)
            all_prices = [ad['price'] for ad in bybit_ads] + bin_prices + mexc_prices
            stats = analyze_stats(all_prices, peg)
            
            # 3. Detect Trades (Using only Bybit Ads which have IDs)
            new_trades = detect_trades(bybit_ads)
            
            # 4. Save & Update
            if new_trades:
                print(f"💰 {len(new_trades)} Trade(s) Detected!")
                for t in new_trades:
                    save_trade_to_csv(t)
                    TRADES_HISTORY.insert(0, t) # Add to top of feed
                TRADES_HISTORY = TRADES_HISTORY[:50] # Keep max 50 in RAM
            
            if stats:
                generate_neon_chart(stats, official)
                update_html(stats, official, TRADES_HISTORY, datetime.datetime.now().strftime("%H:%M:%S"))
            
            time.sleep(REFRESH_RATE)
            
        except KeyboardInterrupt:
            print("🛑 Stopping...")
            break
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
