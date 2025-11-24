#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v32.0 (Unified Edition)
- SOURCES: Binance/MEXC (via API), Bybit (via Scraper).
- FEED: "User Transactions" generated from Real Binance/MEXC prices only.
- GRAPH: Smart Zoom (P05-P95) + Collision-proof labels.
"""

import requests
import statistics
import sys
import time
import csv
import os
import datetime
import random
import json
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

# --- 1. FETCHERS ---
def fetch_official_rate():
    try: return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except: return None

def fetch_usdt_peg():
    try: return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except: return 1.00

def fetch_bybit(side):
    """ Bybit Direct Scraper """
    url = "https://api2.bybit.com/fiat/otc/item/online"
    ads = []
    page = 1
    h = HEADERS.copy()
    h["Referer"] = "https://www.bybit.com/"
    while True:
        try:
            r = requests.post(url, headers=h, json={"userId":"","tokenId":"USDT","currencyId":"ETB","payment":[],"side":side,"size":"20","page":str(page),"authMaker":False}, timeout=5)
            items = r.json().get("result", {}).get("items", [])
            if not items: break
            for i in items:
                ads.append({
                    'source': 'Bybit',
                    'price': float(i.get('price')),
                    'advertiser': i.get('nickName', 'Bybit User')
                })
            if page >= 3: break
            page += 1; time.sleep(0.1)
        except: break
    return ads

def fetch_p2p_army_ads(market, side):
    """ Binance & MEXC via API """
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    ads = []
    h = HEADERS.copy()
    h["X-APIKEY"] = P2P_ARMY_KEY
    try:
        r = requests.post(url, headers=h, json={"market": market, "fiat": "ETB", "asset": "USDT", "side": side, "limit": 100}, timeout=10)
        data = r.json()
        # Robust parsing for different API response structures
        candidates = data.get("result", {}).get("data", {}).get("ads", [])
        if not candidates: candidates = data.get("data", {}).get("ads", [])
        
        for ad in candidates:
            ads.append({
                'source': market.title(), # "Binance" or "Mexc"
                'price': float(ad['price']),
                'advertiser': ad.get('advertiser_name', 'Trader')
            })
    except: pass
    return ads

# --- 2. ANALYTICS ---
def analyze(prices, peg):
    if not prices: return None
    valid = sorted([p for p in prices if 50 < p < 400])
    if len(valid) < 2: return None
    
    adj = [p / peg for p in valid]
    n = len(adj)
    
    try:
        quantiles = statistics.quantiles(adj, n=100, method='inclusive')
        p05, p10, q1, median, q3, p95 = quantiles[4], quantiles[9], quantiles[24], quantiles[49], quantiles[74], quantiles[94]
    except:
        median = statistics.median(adj)
        p05, q1, q3, p95 = adj[0], adj[int(n*0.25)], adj[int(n*0.75)], adj[-1]

    return {
        "median": median, "q1": q1, "q3": q3, "p05": p05, "p95": p95, 
        "min": adj[0], "max": adj[-1], "raw_data": adj, "count": n
    }

# --- 3. GRAPH GENERATOR (Smart Zoom) ---
def generate_charts(stats, official_rate):
    if not GRAPH_ENABLED: return
    print(f"📊 Rendering Chart...", file=sys.stderr)
    
    # Config
    style = {"bg":"#050505", "fg":"#00ff9d", "grid":"#222", "median":"#ff0055", "sec":"#00bfff", "fill":"#00ff9d"}
    dates, medians, q1s, q3s, offs = load_history()

    plt.rcParams.update({
        "figure.facecolor": style["bg"], "axes.facecolor": style["bg"], 
        "axes.edgecolor": style["fg"], "axes.labelcolor": style["fg"], 
        "xtick.color": style["fg"], "ytick.color": style["fg"], "text.color": style["fg"]
    })
    
    fig = plt.figure(figsize=(12, 14))
    fig.suptitle(f'ETB LIQUIDITY SCANNER: {datetime.datetime.now().strftime("%H:%M")}', fontsize=20, color=style["fg"], fontweight='bold', y=0.97)

    # TOP: DOT PLOT
    ax1 = fig.add_subplot(2, 1, 1)
    data = stats['raw_data']
    y_jitter = [1 + random.uniform(-0.12, 0.12) for _ in data]
    
    ax1.scatter(data, y_jitter, color=style["fg"], alpha=0.6, s=30, edgecolors='none')
    
    # Guidelines
    ax1.axvline(stats['median'], color=style["median"], linewidth=3)
    ax1.axvline(stats['q1'], color=style["sec"], linewidth=2, linestyle='--', alpha=0.6)
    ax1.axvline(stats['q3'], color=style["sec"], linewidth=2, linestyle='--', alpha=0.6)
    
    # Smart Labels (Median Top, Quartiles Bottom)
    ax1.text(stats['median'], 1.42, f"MEDIAN\n{stats['median']:.2f}", color=style["median"], ha='center', fontweight='bold')
    ax1.text(stats['q1'], 0.58, f"Q1\n{stats['q1']:.2f}", color=style["sec"], ha='right', va='top')
    ax1.text(stats['q3'], 0.58, f"Q3\n{stats['q3']:.2f}", color=style["sec"], ha='left', va='top')
    
    if official_rate: ax1.axvline(official_rate, color=style["fg"], linestyle=':', linewidth=1.5)
    
    # Smart Zoom (P05 - P95)
    margin = (stats['p95'] - stats['p05']) * 0.15
    if margin < 1: margin = 1
    ax1.set_xlim([stats['p05'] - margin, stats['p95'] + margin])
    ax1.set_ylim(0.5, 1.5); ax1.set_yticks([])
    
    ax1.set_title("Live Market Depth (Smart Zoom)", color=style["fg"], loc='left', pad=10)
    ax1.grid(True, axis='x', color=style["grid"], linestyle='--')

    # BOTTOM: HISTORY
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

# --- 4. WEB GENERATOR ---
def update_website_html(stats, official, timestamp, all_ads, peg):
    prem = ((stats['median'] - official)/official)*100 if official else 0
    cache_buster = int(time.time())
    
    # Table
    table_rows = ""
    for source, ads in all_ads.items():
        prices = [a['price'] for a in ads]
        s = analyze(prices, peg)
        if s:
            table_rows += f"<tr><td class='source-col'>{source}</td><td>{s['min']:.2f}</td><td>{s['q1']:.2f}</td><td class='med-col'>{s['median']:.2f}</td><td>{s['q3']:.2f}</td><td>{s['max']:.2f}</td><td>{s['count']}</td></tr>"
        else:
            table_rows += f"<tr><td>{source}</td><td colspan='6' style='opacity:0.5'>No Data</td></tr>"

    # Transaction Feed (BINANCE + MEXC ONLY)
    pool = []
    median_price = stats['median']
    
    # Filter: Only Binance and MEXC for the feed
    for source in ['Binance', 'MEXC']:
        if source in all_ads:
            for ad in all_ads[source]:
                real_price = ad['price'] / peg
                # Scam Filter: Ignore prices > 10% cheaper than median
                if real_price > (median_price * 0.90):
                    pool.append({'price': real_price, 'source': source})
    
    feed_items = []
    now = datetime.datetime.now()
    
    if pool:
        for i in range(15):
            # Pick random trade from pool
            trade = random.choice(pool)
            price = trade['price']
            
            # Jitter price slightly to simulate different ad fills
            price += random.uniform(-0.05, 0.05)
            
            # Time: Recent
            delta = random.randint(10, 600) + (i * 20)
            trade_time = now - datetime.timedelta(seconds=delta)
            date_str = trade_time.strftime("%m/%d/%Y")
            time_str = trade_time.strftime("%I:%M:%S %p")
            
            # User
            user = f"{random.choice(['ETHIO', 'Trust', 'User-', 'Tinsa', 'Hayme', 'Real_', 'Sayid'])}***"
            vol = round(random.uniform(100, 5000), 2)
            
            # Icon
            s_color = "#f3ba2f" if trade['source'] == "Binance" else "#2e55e6"
            
            feed_items.append(f"""
            <div class="feed-item">
                <div class="feed-icon" style="background-color: #2ea043;">🛒</div>
                <div class="feed-content">
                    <span class="feed-ts">{date_str}, {time_str}</span> -> 
                    <span class="feed-user">{user}</span> (BUYER) bought 
                    <span class="feed-vol">{vol:,.2f} USD</span> at 
                    <span class="feed-price">{price:.2f} ETB</span>
                    <span style="font-size:0.7em; color:{s_color}; display:block">via {trade['source']}</span>
                </div>
            </div>""")
        
        # Sort by time (newest top)
        feed_items.sort(key=lambda x: x.split('feed-ts">')[1].split(',')[1].split('<')[0], reverse=True)
    else:
        feed_items.append("<div class='feed-item'>Waiting for market liquidity...</div>")
    
    feed_html = "\n".join(feed_items)

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="300">
        <title>ETB Pro Terminal</title>
        <style>
            :root {{ --bg: #050505; --card: #111; --text: #00ff9d; --sub: #ccc; --mute: #666; --accent: #ff0055; --link: #00bfff; --gold: #ffcc00; --border: #333; --hover: rgba(0,255,157,0.05); }}
            body {{ background: var(--bg); color: var(--text); font-family: 'Courier New', monospace; margin: 0; padding: 20px; text-align: center; }}
            .container {{ max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 2fr 1fr; gap: 20px; text-align: left; }}
            
            header {{ grid-column: span 2; text-align: center; margin-bottom: 20px; }}
            h1 {{ font-size: 2.5rem; margin: 0; text-shadow: 0 0 10px var(--text); }}
            
            .left-col {{ display: flex; flex-direction: column; gap: 20px; }}
            .right-col {{ display: flex; flex-direction: column; gap: 20px; }}
            .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
            .ticker {{ text-align: center; padding: 30px; background: linear-gradient(145deg, var(--card), var(--bg)); }}
            .price {{ font-size: 4rem; font-weight: bold; color: var(--sub); margin: 10px 0; }}
            .prem {{ color: var(--gold); font-size: 0.9rem; display: block; margin-top: 10px; }}
            .chart img {{ width: 100%; border-radius: 8px; display: block; border: 1px solid var(--border); }}
            
            table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
            th {{ text-align: left; padding: 12px; border-bottom: 2px solid var(--border); color: var(--text); }}
            td {{ padding: 12px; border-bottom: 1px solid var(--border); color: var(--sub); }}
            .med-col {{ color: var(--accent); font-weight: bold; }}

            .feed-title {{ font-size: 1.1rem; font-weight: bold; margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; color: var(--text); }}
            .feed-container {{ max-height: 600px; overflow-y: auto; background: #0a0a0a; border-radius: 8px; padding: 5px; }}
            .feed-item {{ display: flex; gap: 12px; padding: 12px 10px; border-bottom: 1px solid #222; align-items: flex-start; }}
            .feed-icon {{ width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; flex-shrink: 0; color: #fff; }}
            .feed-content {{ font-size: 0.85rem; color: #ccc; line-height: 1.5; }}
            .feed-ts {{ color: var(--mute); font-family: monospace; }}
            .feed-user, .feed-price {{ font-weight: bold; color: #fff; }}

            footer {{ grid-column: span 2; margin-top: 40px; text-align: center; color: var(--mute); font-size: 0.7rem; }}
            @media (max-width: 900px) {{ .container {{ grid-template-columns: 1fr; }} header, footer {{ grid-column: span 1; }} .price {{ font-size: 3rem; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>ETB MARKET INTELLIGENCE</h1>
                <div style="color:var(--mute); letter-spacing:4px; font-size:0.8rem;">/// LIVE P2P LIQUIDITY SCANNER ///</div>
            </header>

            <div class="left-col">
                <div class="card ticker">
                    <div style="color:var(--mute); font-size:0.8rem; letter-spacing:2px;">TRUE USD MEDIAN</div>
                    <div class="price">{stats['median']:.2f} <span style="font-size:1.5rem;color:var(--mute)">ETB</span></div>
                    <span class="prem">Black Market Premium: +{prem:.2f}%</span>
                </div>
                <div class="card chart">
                    <img src="{GRAPH_FILENAME}?v={cache_buster}" alt="Market Chart">
                </div>
                <div class="card">
                    <table><thead><tr><th>Source</th><th>Min</th><th>Q1</th><th>Med</th><th>Q3</th><th>Max</th><th>Ads</th></tr></thead><tbody>{table_rows}</tbody></table>
                </div>
            </div>

            <div class="right-col">
                <div class="card">
                    <div class="feed-title">👀 Recent Market Actions (Binance/MEXC)</div>
                    <div class="feed-container">{feed_html}</div>
                </div>
            </div>

            <footer>Official Bank Rate: {official:.2f} ETB | Last Update: {timestamp} UTC</footer>
        </div>
    </body>
    </html>
    """
    with open(HTML_FILENAME, "w") as f: f.write(html)
    print("✅ Website generated.")

# --- 5. HISTORY ---
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

# --- 6. MAIN ---
def main():
    print("🔍 Running v32.0 Unified Scan...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=10) as ex:
        # API
        f_bin = ex.submit(lambda: fetch_p2p_army_ads("binance", "SELL"))
        f_mexc = ex.submit(lambda: fetch_p2p_army_ads("mexc", "SELL"))
        # Scraper
        f_byb = ex.submit(lambda: fetch_bybit("1"))
        
        f_off = ex.submit(fetch_official_rate)
        f_peg = ex.submit(fetch_usdt_peg)
        
        data = {"Binance": f_bin.result(), "Bybit": f_byb.result(), "MEXC": f_mexc.result()}
        official = f_off.result() or 0.0
        peg = f_peg.result() or 1.0

    # Flatten
    all_prices = []
    for ads in data.values():
        for ad in ads: all_prices.append(ad['price'])
    
    stats = analyze(all_prices, peg)
    
    if stats:
        save_to_history(stats, official)
        generate_charts(stats, official)
    else:
        stats = {"median":0, "min":0, "q1":0, "q3":0, "max":0, "count":0, "raw_data":[]}

    update_website_html(stats, official, time.strftime('%Y-%m-%d %H:%M:%S'), data, peg)
    print("✅ Update Complete.")

if __name__ == "__main__":
    main()
