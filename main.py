#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v17.0 (REAL DATA ONLY)
- FEED: Now shows REAL Live Ad Orders from Binance/Bybit/MEXC.
- REMOVED: All fake "User bought..." transaction generation.
- LOGIC: Sorts actual active ads by best price to show market depth.
"""

import requests
import statistics
import sys
import time
import csv
import os
import datetime
import random # Only used for graph jitter, NOT for data
from concurrent.futures import ThreadPoolExecutor

# Try importing matplotlib
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.ticker as ticker
    GRAPH_ENABLED = True
except ImportError:
    GRAPH_ENABLED = False
    print("⚠️ Matplotlib not found.", file=sys.stderr)

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HISTORY_FILE = "etb_history.csv"
GRAPH_FILENAME = "etb_neon_terminal.png"
HTML_FILENAME = "index.html"

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

# --- 1. ANALYTICS ---
def analyze(prices, peg):
    if not prices: return None
    # Filter only unrealistic outliers (keeping broader range for accuracy)
    valid = sorted([p for p in prices if 50 < p < 400])
    if len(valid) < 2: return None
    
    adj = [p / peg for p in valid]
    n = len(adj)
    
    try:
        quantiles = statistics.quantiles(adj, n=100, method='inclusive')
        p10, q1, median, q3, p90 = quantiles[9], quantiles[24], quantiles[49], quantiles[74], quantiles[89]
    except:
        median = statistics.median(adj)
        p10, q1, q3, p90 = adj[int(n*0.1)], adj[int(n*0.25)], adj[int(n*0.75)], adj[int(n*0.9)]

    return {
        "median": median, "q1": q1, "q3": q3, "p10": p10, "p90": p90, 
        "min": adj[0], "max": adj[-1], "raw_data": adj, "count": n
    }

# --- 2. WEB GENERATOR (REAL FEED) ---
def update_website_html(stats, official, timestamp, all_ads, peg):
    prem = ((stats['median'] - official)/official)*100 if official else 0
    cache_buster = int(time.time())
    
    # 1. Data Table
    table_rows = ""
    # We reconstruct lists of prices from the ad objects for the table stats
    for source, ads in all_ads.items():
        prices = [ad['price'] for ad in ads]
        s = analyze(prices, peg)
        if s:
            table_rows += f"<tr><td style='font-weight:bold;color:#ccc'>{source}</td><td>{s['min']:.2f}</td><td>{s['q1']:.2f}</td><td style='color:#ff0055;font-weight:bold'>{s['median']:.2f}</td><td>{s['q3']:.2f}</td><td>{s['max']:.2f}</td><td>{s['count']}</td></tr>"
        else:
            table_rows += f"<tr><td>{source}</td><td colspan='6' style='opacity:0.5'>No Data</td></tr>"

    # 2. REAL ORDER FEED GENERATOR
    # Consolidate all ads into a single list
    market_feed = []
    for source, ads in all_ads.items():
        for ad in ads:
            # Flatten ad data structure
            item = {
                'source': source,
                'price': ad['price'],
                'price_usd': ad['price'] / peg,
                'user': ad.get('advertiser', 'Trader'),
                'min_limit': ad.get('min_limit', 0),
                'max_limit': ad.get('max_limit', 0),
                'method': ad.get('method', 'Bank')
            }
            market_feed.append(item)
    
    # Sort by Price (Cheapest Sellers First = Best Offers)
    # We only show the "Best" offers because that is the 'market price'
    market_feed.sort(key=lambda x: x['price'])
    
    feed_items = []
    
    if market_feed:
        # Take top 20 best offers
        for i, order in enumerate(market_feed[:20]):
            
            # Format numbers
            real_price_usd = order['price_usd']
            limit_str = f"{order['min_limit']:,.0f}-{order['max_limit']:,.0f}"
            
            # Icon logic based on source
            if "Binance" in order['source']:
                icon = "🔶" # Binance Yellow
                icon_bg = "#FCD535"
                text_color = "#000"
            elif "Bybit" in order['source']:
                icon = "⚫" 
                icon_bg = "#121212"
                text_color = "#fff"
            else:
                icon = "🟢"
                icon_bg = "#2ea043"
                text_color = "#fff"

            item_html = f"""
            <div class="feed-item">
                <div class="feed-icon" style="background-color: {icon_bg}; color: {text_color};">{icon}</div>
                <div class="feed-content">
                    <span class="feed-ts">LIVE OFFER #{i+1}</span> -> 
                    <span class="feed-user">{order['user']}</span> is selling USDT @ 
                    <span class="feed-price">{order['price']:.2f} ETB</span>.
                    <br><span style="color:#666; font-size:0.8em;">Limit: {limit_str} ETB | {order['source']}</span>
                </div>
            </div>
            """
            feed_items.append(item_html)
    else:
        feed_items.append("<div class='feed-item'>Waiting for market data...</div>")
    
    feed_html = "\n".join(feed_items)

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="60">
        <title>ETB Pro Terminal</title>
        <style>
            :root {{
                --bg: #050505; --card: #111; --text: #00ff9d; --sub: #ccc; --mute: #666;
                --accent: #ff0055; --link: #00bfff; --gold: #ffcc00;
                --border: #333; --hover: rgba(0, 255, 157, 0.05);
            }}
            body {{ background: var(--bg); color: var(--text); font-family: 'Courier New', monospace; margin: 0; padding: 20px; text-align: center; }}
            .container {{ max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 2fr 1fr; gap: 20px; text-align: left; }}
            
            header {{ grid-column: span 2; text-align: center; margin-bottom: 20px; }}
            h1 {{ font-size: 2.5rem; margin: 0; text-shadow: 0 0 10px var(--text); }}
            
            .left-col {{ display: flex; flex-direction: column; gap: 20px; }}
            .right-col {{ display: flex; flex-direction: column; gap: 20px; }}

            .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
            
            /* Ticker */
            .ticker {{ text-align: center; padding: 30px; background: linear-gradient(145deg, var(--card), var(--bg)); }}
            .price {{ font-size: 4rem; font-weight: bold; color: var(--sub); margin: 10px 0; }}
            .prem {{ color: var(--gold); border: 1px solid var(--gold); padding: 4px 12px; border-radius: 20px; font-size: 0.9rem; }}

            .chart img {{ width: 100%; border-radius: 8px; display: block; border: 1px solid var(--border); }}

            /* Table */
            table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
            th {{ text-align: left; padding: 12px; border-bottom: 2px solid var(--border); color: var(--text); }}
            td {{ padding: 12px; border-bottom: 1px solid var(--border); color: var(--sub); }}
            tr:last-child td {{ border-bottom: none; }}

            /* FEED STYLES (Transaction Mode) */
            .feed-title {{ font-size: 1.1rem; font-weight: bold; margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; color: #fff; display: flex; align-items: center; gap: 10px; }}
            .feed-container {{ max-height: 600px; overflow-y: auto; background: #0a0a0a; border-radius: 8px; padding: 5px; }}
            .feed-container::-webkit-scrollbar {{ width: 6px; }}
            .feed-container::-webkit-scrollbar-thumb {{ background: var(--border); }}

            .feed-item {{ display: flex; gap: 12px; padding: 12px 10px; border-bottom: 1px solid #222; align-items: flex-start; font-family: sans-serif; background: #0e0e0e; margin-bottom: 2px; }}
            .feed-icon {{ width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; flex-shrink: 0; }}
            .feed-content {{ font-size: 0.85rem; color: #ccc; line-height: 1.5; margin-top: 2px; }}
            .feed-ts {{ color: #00ff9d; font-family: monospace; font-weight:bold; }}
            .feed-user {{ font-weight: bold; color: #fff; }}
            .feed-vol {{ font-weight: bold; color: #fff; }}
            .feed-price {{ font-weight: bold; color: #fff; }}

            footer {{ grid-column: span 2; margin-top: 40px; text-align: center; color: var(--mute); font-size: 0.7rem; }}
            
            @media (max-width: 900px) {{ .container {{ grid-template-columns: 1fr; }} header, footer {{ grid-column: span 1; }} .price {{ font-size: 3rem; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>ETB MARKET INTELLIGENCE</h1>
                <div style="color:var(--mute); letter-spacing:4px; font-size:0.8rem;">/// LIVE P2P ORDER BOOK SCANNER ///</div>
            </header>

            <div class="left-col">
                <div class="card ticker">
                    <div style="color:var(--mute); font-size:0.8rem; letter-spacing:2px;">TRUE USD MEDIAN</div>
                    <div class="price">{stats['median']:.2f} <span style="font-size:1.5rem;color:var(--mute)">ETB</span></div>
                    <span class="prem">Premium: +{prem:.2f}%</span>
                </div>

                <div class="card chart">
                    <img src="{GRAPH_FILENAME}?v={cache_buster}" alt="Market Chart">
                </div>

                <div class="card">
                    <table>
                        <thead><tr><th>Source</th><th>Min</th><th>Q1</th><th>Med</th><th>Q3</th><th>Max</th><th>Ads</th></tr></thead>
                        <tbody>{table_rows}</tbody>
                    </table>
                </div>
            </div>

            <div class="right-col">
                <div class="card">
                    <div class="feed-title">📢 Real-Time Order Stream (Best Offers)</div>
                    <div class="feed-container">
                        {feed_html}
                    </div>
                </div>
            </div>

            <footer>
                Official Bank Rate: {official:.2f} ETB | Last Update: {timestamp} UTC
            </footer>
        </div>
    </body>
    </html>
    """
    
    with open(HTML_FILENAME, "w") as f:
        f.write(html_content)
    print(f"✅ Website generated.")

# --- 3. FETCHERS (Now returns Objects, not just float prices) ---
def fetch_official_rate():
    try: return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except: return None

def fetch_usdt_peg():
    try: return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except: return 1.00

def fetch_bybit_ads(side):
    url = "https://api2.bybit.com/fiat/otc/item/online"
    ads = []
    page = 1
    h = HEADERS.copy(); h["Referer"] = "https://www.bybit.com/"
    while True:
        try:
            r = requests.post(url, headers=h, json={"userId":"","tokenId":"USDT","currencyId":"ETB","payment":[],"side":side,"size":"20","page":str(page),"authMaker":False}, timeout=5)
            items = r.json().get("result", {}).get("items", [])
            if not items: break
            
            for i in items:
                ads.append({
                    'price': float(i['price']),
                    'advertiser': i.get('nickName', 'Bybit User'),
                    'min_limit': float(i.get('minAmount', 0)),
                    'max_limit': float(i.get('maxAmount', 0)),
                    'method': 'Bybit P2P'
                })
                
            if page >= 3: break # Limit depth
            page += 1; time.sleep(0.1)
        except: break
    return ads

def fetch_p2p_army_ads(market, side):
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    ads = []
    h = HEADERS.copy(); h["X-APIKEY"] = P2P_ARMY_KEY
    try:
        payload = {"market": market, "fiat": "ETB", "asset": "USDT", "side": side, "limit": 100}
        r = requests.post(url, headers=h, json=payload, timeout=10)
        data = r.json()
        candidates = data.get("result", data.get("data", data.get("ads", [])))
        
        if not candidates and isinstance(data, list): candidates = data
        
        if candidates:
            for ad in candidates:
                if isinstance(ad, dict) and 'price' in ad:
                    # Parse P2P Army structure (differs slightly by market)
                    ads.append({
                        'price': float(ad['price']),
                        'advertiser': ad.get('advertiser_name', f'{market} User'),
                        'min_limit': float(ad.get('min_limit', 0)) if 'min_limit' in ad else 0,
                        'max_limit': float(ad.get('max_limit', 0)) if 'max_limit' in ad else 0,
                        'method': 'Bank'
                    })
    except: pass
    return ads

# --- 4. HISTORY ---
def save_to_history(stats, official):
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='') as f:
        w = csv.writer(f)
        if not file_exists: w.writerow(["Timestamp", "Median", "Q1", "Q3", "Official"])
        w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), round(stats['median'],2), round(stats['q1'],2), round(stats['q3'],2), round(official,2) if official else 0])

def load_history():
    if not os.path.isfile(HISTORY_FILE): return [],[],[],[],[]
    d, m, q1, q3, off = [],[],[],[],[]
    with open(HISTORY_FILE, 'r') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            try:
                d.append(datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
                m.append(float(row[1])); q1.append(float(row[2])); q3.append(float(row[3])); off.append(float(row[4]))
            except: pass
    return d[-48:], m[-48:], q1[-48:], q3[-48:], off[-48:]

# --- 5. GRAPH GENERATOR ---
def generate_charts(stats, official_rate):
    if not GRAPH_ENABLED: return
    print(f"📊 Rendering Chart...", file=sys.stderr)
    
    style = {"bg":"#050505","fg":"#00ff9d","grid":"#222","median":"#ff0055","sec":"#00bfff","fill":"#00ff9d"}
    dates, medians, q1s, q3s, offs = load_history()

    plt.rcParams.update({"figure.facecolor": style["bg"], "axes.facecolor": style["bg"], "axes.edgecolor": style["fg"], "axes.labelcolor": style["fg"], "xtick.color": style["fg"], "ytick.color": style["fg"], "text.color": style["fg"]})
    fig = plt.figure(figsize=(12, 14))
    fig.suptitle(f'ETB LIQUIDITY SCANNER: {datetime.datetime.now().strftime("%H:%M")}', fontsize=20, color=style["fg"], fontweight='bold', y=0.97)

    ax1 = fig.add_subplot(2, 1, 1)
    data = stats['raw_data']
    y_jitter = [1 + random.uniform(-0.12, 0.12) for _ in data]
    ax1.scatter(data, y_jitter, color=style["fg"], alpha=0.6, s=30, edgecolors='none')
    ax1.axvline(stats['median'], color=style["median"], linewidth=3)
    ax1.axvline(stats['q1'], color=style["sec"], linewidth=2, linestyle='--', alpha=0.6)
    ax1.axvline(stats['q3'], color=style["sec"], linewidth=2, linestyle='--', alpha=0.6)
    
    ax1.text(stats['median'], 1.4, f"MEDIAN\n{stats['median']:.2f}", color=style["median"], ha='center', fontweight='bold')
    
    if official_rate: ax1.axvline(official_rate, color=style["fg"], linestyle=':', linewidth=1.5)
    margin = (stats['p90'] - stats['p10']) * 0.25
    ax1.set_xlim([min(official_rate or 999, stats['p10']) - margin, stats['p90'] + margin])
    ax1.set_ylim(0.5, 1.5); ax1.set_yticks([])
    ax1.set_title("Live Market Depth (Real Ads)", color=style["fg"], loc='left', pad=10)
    ax1.grid(True, axis='x', color=style["grid"], linestyle='--')

    ax2 = fig.add_subplot(2, 1, 2)
    if len(dates) > 1:
        ax2.fill_between(dates, q1s, q3s, color=style["fill"], alpha=0.2, linewidth=0)
        ax2.plot(dates, medians, color=style["median"], linewidth=2)
        if any(offs): ax2.plot(dates, offs, color=style["fg"], linestyle='--', linewidth=1, alpha=0.5)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.1f'))
        ax2.yaxis.tick_right()
        ax2.grid(True, color=style["grid"], linewidth=0.5)
        ax2.set_title("Historical Trend (24h)", color=style["fg"], loc='left')
    
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(GRAPH_FILENAME, dpi=150, facecolor=style["bg"])
    plt.close()

# --- 6. MAIN ---
def main():
    print("🔍 Running v17.0 REAL AD DATA Scan...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_bin = ex.submit(lambda: fetch_p2p_army_ads("binance", "SELL"))
        f_mexc = ex.submit(lambda: fetch_p2p_army_ads("mexc", "SELL"))
        f_byb = ex.submit(lambda: fetch_bybit_ads("1")) # Side 1 = Sell in Bybit API
        f_off = ex.submit(fetch_official_rate)
        f_peg = ex.submit(fetch_usdt_peg)
        
        # Collect full ad objects
        all_ads = {
            "Binance": f_bin.result(), 
            "Bybit": f_byb.result(), 
            "MEXC": f_mexc.result()
        }
        official = f_off.result() or 0.0
        peg = f_peg.result() or 1.0

    # Consolidate prices for stats
    all_prices = []
    for ads in all_ads.values():
        all_prices.extend([ad['price'] for ad in ads])
        
    stats = analyze(all_prices, peg)
    
    if stats:
        save_to_history(stats, official)
        generate_charts(stats, official)
    else:
        stats = {"median":0, "q1":0, "q3":0, "min":0, "max":0, "count":0, "p10":0, "p90":0, "raw_data":[]}

    update_website_html(stats, official, time.strftime('%Y-%m-%d %H:%M:%S'), all_ads, peg)
    print("✅ Update Complete.")

if __name__ == "__main__":
    main()
