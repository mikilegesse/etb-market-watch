#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v7.0 (Day & Night Edition)
- VISUALS: Generates TWO charts (Dark/Neon + Light/Pro)
- FIXES: Smart label spacing prevents Q1/Q3 overlap
- WEB: Interactive Light/Dark Mode Toggle
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
IMG_DARK = "etb_neon_dark.png"
IMG_LIGHT = "etb_clean_light.png"
HTML_FILENAME = "index.html"

HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}

# --- 1. ANALYTICS ENGINE ---
def analyze(prices, peg):
    if not prices: return None
    valid = sorted([p for p in prices if 50 < p < 400])
    if len(valid) < 2: return None
    
    adj = [p / peg for p in valid]
    n = len(adj)
    
    median = statistics.median(adj)
    mean = statistics.mean(adj)
    # Inclusive method for quartiles
    try: q1, median_q, q3 = statistics.quantiles(adj, n=4, method='inclusive')[:3]
    except: q1, q3 = adj[int(n*0.25)], adj[int(n*0.75)]
    
    # Percentiles for range
    p10 = adj[int(n*0.1)]
    p90 = adj[int(n*0.9)]

    return {
        "median": median, "mean": mean,
        "q1": q1, "q3": q3, "p10": p10, "p90": p90, 
        "min": adj[0], "max": adj[-1],
        "raw_data": adj, "count": n
    }

# --- 2. DUAL-THEME CHART GENERATOR ---
def generate_charts(stats, official_rate):
    if not GRAPH_ENABLED: return
    
    themes = [
        ("dark", IMG_DARK, {
            "bg": "#050505", "fg": "#00ff9d", "grid": "#222", 
            "median": "#ff0055", "fill": "#00ff9d", "dot_alpha": 0.6
        }),
        ("light", IMG_LIGHT, {
            "bg": "#ffffff", "fg": "#1a1a1a", "grid": "#e0e0e0", 
            "median": "#d32f2f", "fill": "#008000", "dot_alpha": 0.4
        })
    ]

    dates, medians, q1s, q3s, offs = load_history()

    for mode, filename, style in themes:
        print(f"📊 Rendering {mode} chart...", file=sys.stderr)
        
        # Setup Style
        plt.rcParams.update({
            "figure.facecolor": style["bg"],
            "axes.facecolor": style["bg"],
            "axes.edgecolor": style["fg"],
            "axes.labelcolor": style["fg"],
            "xtick.color": style["fg"],
            "ytick.color": style["fg"],
            "text.color": style["fg"]
        })
        
        fig = plt.figure(figsize=(12, 14))
        fig.suptitle(f'ETB LIQUIDITY SCANNER: {datetime.datetime.now().strftime("%H:%M")}', 
                     fontsize=20, color=style["fg"], fontweight='bold', y=0.97)

        # --- TOP: DOT PLOT ---
        ax1 = fig.add_subplot(2, 1, 1)
        data = stats['raw_data']
        y_jitter = [1 + random.uniform(-0.12, 0.12) for _ in data]
        
        # Dots
        ax1.scatter(data, y_jitter, color=style["fg"], alpha=style["dot_alpha"], s=30, edgecolors='none')
        
        # Guidelines
        ax1.axvline(stats['median'], color=style["median"], linewidth=3, label='Median')
        ax1.axvline(stats['q1'], color=style["fg"], linewidth=1, linestyle='--', alpha=0.5)
        ax1.axvline(stats['q3'], color=style["fg"], linewidth=1, linestyle='--', alpha=0.5)

        # --- SMART LABELS (No Overlap Logic) ---
        # Median: Always Top Center
        ax1.text(stats['median'], 1.35, f"MEDIAN\n{stats['median']:.2f}", 
                 color=style["median"], ha='center', fontweight='bold', fontsize=11)
        
        # Q1: Bottom Left (Pushed Left)
        ax1.text(stats['q1'], 0.65, f"Q1 (Low)\n{stats['q1']:.2f}", 
                 color=style["fg"], ha='right', va='top', fontsize=10)
        
        # Q3: Bottom Right (Pushed Right)
        ax1.text(stats['q3'], 0.65, f"Q3 (High)\n{stats['q3']:.2f}", 
                 color=style["fg"], ha='left', va='top', fontsize=10)

        if official_rate:
            ax1.axvline(official_rate, color=style["fg"], linestyle=':', linewidth=1.5)
            ax1.text(official_rate, 0.65, f"Bank\n{official_rate:.0f}", color=style["fg"], ha='center', fontsize=9)

        # Dynamic Zoom
        margin = (stats['p90'] - stats['p10']) * 0.3
        ax1.set_xlim([min(official_rate or 999, stats['p10']) - margin, stats['p90'] + margin])
        ax1.set_ylim(0.5, 1.5)
        ax1.set_yticks([])
        ax1.set_title("Live Market Depth", color=style["fg"], loc='left', pad=10)
        ax1.grid(True, axis='x', color=style["grid"], linestyle='--')

        # --- BOTTOM: HISTORY ---
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
        else:
            ax2.text(0.5, 0.5, "Building History...", ha='center', color='gray')

        plt.tight_layout(rect=[0, 0, 1, 0.95])
        plt.savefig(filename, dpi=150, facecolor=style["bg"])
        plt.close()
    
    print("✅ Both charts generated.", file=sys.stderr)

# --- 3. WEB GENERATOR (Toggle Logic) ---
def update_website_html(stats, official, timestamp, all_data_sources, peg):
    prem = ((stats['median'] - official)/official)*100 if official else 0
    
    # Data Table
    rows = ""
    for src, prices in all_data_sources.items():
        s = analyze(prices, peg)
        if s:
            rows += f"<tr><td>{src}</td><td>{s['min']:.1f}</td><td>{s['q1']:.1f}</td><td class='med'>{s['median']:.1f}</td><td>{s['q3']:.1f}</td><td>{s['max']:.1f}</td><td>{s['count']}</td></tr>"
        else:
            rows += f"<tr><td>{src}</td><td colspan='6'>No Data</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html lang="en" data-theme="dark">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ETB Market Watch</title>
        <style>
            :root {{ --bg: #050505; --card-bg: #111; --text: #00ff9d; --accent: #ff0055; --border: #333; --grid: #222; }}
            [data-theme="light"] {{ --bg: #f4f4f9; --card-bg: #ffffff; --text: #1a1a1a; --accent: #d32f2f; --border: #ddd; --grid: #eee; }}
            
            body {{ background: var(--bg); color: var(--text); font-family: monospace; transition: 0.3s; text-align: center; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            
            /* Toggle Switch */
            .toggle-btn {{ position: absolute; top: 20px; right: 20px; cursor: pointer; background: var(--card-bg); border: 1px solid var(--border); padding: 10px; border-radius: 50%; font-size: 1.2rem; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
            
            /* Cards */
            .ticker {{ background: var(--card-bg); padding: 30px; border-radius: 15px; border: 1px solid var(--border); margin: 30px 0; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
            .price {{ font-size: 4rem; font-weight: bold; color: var(--accent); margin: 10px 0; }}
            .label {{ text-transform: uppercase; letter-spacing: 2px; font-size: 0.9rem; opacity: 0.8; }}
            .premium {{ background: rgba(255, 204, 0, 0.15); color: #ffcc00; padding: 5px 15px; border-radius: 20px; border: 1px solid #ffcc00; display: inline-block; }}
            
            /* Graph */
            #market-chart {{ width: 100%; border-radius: 15px; border: 1px solid var(--border); margin-bottom: 30px; }}
            
            /* Table */
            table {{ width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 10px; overflow: hidden; margin-bottom: 30px; }}
            th {{ background: var(--border); color: var(--text); padding: 12px; font-size: 0.8rem; text-transform: uppercase; }}
            td {{ padding: 12px; border-bottom: 1px solid var(--border); color: var(--text); opacity: 0.9; }}
            .med {{ font-weight: bold; color: var(--accent); }}
            
            footer {{ font-size: 0.8rem; opacity: 0.6; border-top: 1px solid var(--border); padding-top: 20px; }}
        </style>
    </head>
    <body>
        <button class="toggle-btn" onclick="toggleTheme()">🌗</button>
        
        <div class="container">
            <div class="label">LIVE ETB/USD P2P RATE</div>
            
            <div class="ticker">
                <div class="label">True USD Median</div>
                <div class="price">{stats['median']:.2f} ETB</div>
                <div class="premium">Black Market Premium: +{prem:.2f}%</div>
            </div>

            <img id="market-chart" src="{IMG_DARK}" alt="Chart">

            <table>
                <thead><tr><th>Source</th><th>Min</th><th>Q1</th><th>Median</th><th>Q3</th><th>Max</th><th>Ads</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>

            <footer>
                OFFICIAL BANK RATE: {official:.2f} ETB <br>
                LAST UPDATE: {timestamp} UTC
            </footer>
        </div>

        <script>
            const imgDark = "{IMG_DARK}";
            const imgLight = "{IMG_LIGHT}";
            const chart = document.getElementById('market-chart');
            const html = document.documentElement;

            // Load saved theme
            if (localStorage.getItem('theme') === 'light') {{
                html.setAttribute('data-theme', 'light');
                chart.src = imgLight;
            }}

            function toggleTheme() {{
                const current = html.getAttribute('data-theme');
                const newTheme = current === 'dark' ? 'light' : 'dark';
                
                html.setAttribute('data-theme', newTheme);
                chart.src = newTheme === 'dark' ? imgDark : imgLight;
                localStorage.setItem('theme', newTheme);
            }}
        </script>
    </body>
    </html>
    """
    with open(HTML_FILENAME, "w") as f: f.write(html)
    print("✅ Website generated.")

# --- 4. FETCHERS & HISTORY ---
def fetch_official_rate():
    try: return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except: return None

def fetch_usdt_peg():
    try: return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except: return 1.00

def fetch_data_source(url_func):
    prices = []
    try: prices = url_func()
    except: pass
    return prices

def fetch_binance(trade_type):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    prices, page = [], 1
    while True:
        try:
            r = requests.post(url, headers=HEADERS, json={"asset":"USDT","fiat":"ETB","merchantCheck":False,"page":page,"rows":20,"tradeType":trade_type}, timeout=5)
            ads = r.json().get('data', [])
            if not ads: break
            prices.extend([float(ad['adv']['price']) for ad in ads])
            if page >= 5: break
            page += 1; time.sleep(0.1)
        except: break
    return prices

def fetch_bybit(side):
    url = "https://api2.bybit.com/fiat/otc/item/online"
    prices, page = [], 1
    h = HEADERS.copy(); h["Referer"] = "https://www.bybit.com/"
    while True:
        try:
            r = requests.post(url, headers=h, json={"userId":"","tokenId":"USDT","currencyId":"ETB","payment":[],"side":side,"size":"20","page":str(page),"authMaker":False}, timeout=5)
            items = r.json().get("result", {}).get("items", [])
            if not items: break
            prices.extend([float(i['price']) for i in items])
            if page >= 5: break
            page += 1; time.sleep(0.1)
        except: break
    return prices

def fetch_mexc(side):
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    h = HEADERS.copy(); h["X-APIKEY"] = P2P_ARMY_KEY
    try:
        r = requests.post(url, headers=h, json={"market":"mexc","fiat":"ETB","asset":"USDT","side":side,"limit":100}, timeout=10)
        return [float(ad['price']) for ad in r.json().get("result", {}).get("data", {}).get("ads", [])]
    except: return []

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
    return d[-48:], m[-48:], q1[-48:], q3[-48:], off[-48:] # Last 24h (approx)

# --- MAIN ---
def main():
    print("🔍 Running v7.0 Scan...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as ex:
        f_bin = ex.submit(lambda: fetch_binance("BUY") + fetch_binance("SELL"))
        f_byb = ex.submit(lambda: fetch_bybit("1") + fetch_bybit("0"))
        f_mexc = ex.submit(lambda: fetch_mexc("SELL"))
        f_off = ex.submit(fetch_official_rate)
        f_peg = ex.submit(fetch_usdt_peg)
        
        data = {"Binance": f_bin.result(), "Bybit": f_byb.result(), "MEXC": f_mexc.result()}
        official = f_off.result()
        peg = f_peg.result()

    visual_data = data["Binance"] + data["MEXC"]
    stats = analyze(visual_data, peg)
    
    if stats:
        save_to_history(stats, official)
        generate_charts(stats, official) # Generates BOTH images
        update_website_html(stats, official, time.strftime('%H:%M UTC'), data, peg)
        print("✅ Update Complete.")

if __name__ == "__main__":
    main()
