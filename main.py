#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v30.4 (Real Trades Only)
- REAL: Only shows actual detected inventory drops (NO simulation)
- SOURCE: Each trade shows which exchange (Binance/MEXC)
- WINDOW: 15-minute detection window (GitHub Actions runs every 5min)
- CLEAN: Removed 30s double-snapshot approach
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
    print("⚠️ Matplotlib not found.", file=sys.stderr)

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HISTORY_FILE = "etb_history.csv"
SNAPSHOT_FILE = "market_state.json"
TRADES_FILE = "detected_trades.json"
GRAPH_FILENAME = "etb_neon_terminal.png"
GRAPH_LIGHT_FILENAME = "etb_light_terminal.png"
HTML_FILENAME = "index.html"

# 5-minute cron → 12 points/hour → 24h ≈ 288 points
HISTORY_POINTS = 288

# Keep trades for last 15 minutes (3 runs)
TRADE_RETENTION_MINUTES = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- 1. FETCHERS ---
def fetch_official_rate():
    try:
        return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except Exception:
        return None


def fetch_usdt_peg():
    try:
        return float(
            requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd",
                timeout=5
            ).json()["tether"]["usd"]
        )
    except Exception:
        return 1.00


def fetch_binance_direct(trade_type: str):
    """Fallback: Scrape Binance directly if P2P.Army API fails."""
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    ads = []
    page = 1
    payload = {
        "asset": "USDT",
        "fiat": "ETB",
        "merchantCheck": False,
        "page": 1,
        "rows": 20,
        "tradeType": trade_type,
        "payTypes": [],
        "countries": [],
        "publisherType": None
    }

    while True:
        try:
            payload["page"] = page
            r = requests.post(url, headers=HEADERS, json=payload, timeout=5)
            data = r.json().get("data", [])
            if not data:
                break

            for d in data:
                adv = d.get("adv", {})
                ads.append({
                    "source": "Binance",
                    "advertiser": d.get("advertiser", {}).get("nickName", "Binance User"),
                    "price": float(adv.get("price")),
                    "available": float(adv.get("surplusAmount", 0)),
                    "min": float(adv.get("minSingleTransAmount", 0)),
                    "max": float(adv.get("maxSingleTransAmount", 0))
                })
            if page >= 10:
                break
            page += 1
            time.sleep(0.2)
        except Exception:
            break
    return ads


def fetch_bybit(side: str):
    """Scrapes Bybit OTC (for table display only, excluded from trades)."""
    url = "https://api2.bybit.com/fiat/otc/item/online"
    ads = []
    page = 1
    h = HEADERS.copy()
    h["Referer"] = "https://www.bybit.com/"

    while True:
        try:
            r = requests.post(
                url,
                headers=h,
                json={
                    "userId": "",
                    "tokenId": "USDT",
                    "currencyId": "ETB",
                    "payment": [],
                    "side": side,
                    "size": "50",
                    "page": str(page),
                    "authMaker": False
                },
                timeout=5
            )
            items = r.json().get("result", {}).get("items", [])
            if not items:
                break

            for i in items:
                ads.append({
                    "source": "Bybit",
                    "advertiser": i.get("nickName", "Bybit User"),
                    "price": float(i.get("price")),
                    "available": float(i.get("lastQuantity", 0)),
                    "min": float(i.get("minAmount", 0)),
                    "max": float(i.get("maxAmount", 0))
                })
            if page >= 10:
                break
            page += 1
            time.sleep(0.1)
        except Exception:
            break
    return ads


def fetch_p2p_army_ads(market: str, side: str):
    """Uses P2P.Army API for Binance & MEXC with v16.0's proven parsing."""
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    h = HEADERS.copy()
    h["X-APIKEY"] = P2P_ARMY_KEY

    try:
        payload = {
            "market": market,
            "fiat": "ETB",
            "asset": "USDT",
            "side": side,
            "limit": 100
        }
        
        r = requests.post(url, headers=h, json=payload, timeout=10)
        data = r.json()
        
        # ✅ v16.0's proven simple parsing
        candidates = data.get("result", data.get("data", data.get("ads", [])))
        
        if not candidates and isinstance(data, list):
            candidates = data
        
        # Normalize market name
        market_lower = market.lower()
        if market_lower == "binance":
            source_name = "Binance"
        elif market_lower == "mexc":
            source_name = "MEXC"
        else:
            source_name = market.upper()
        
        clean = []
        for ad in candidates:
            if isinstance(ad, dict) and "price" in ad:
                try:
                    clean.append({
                        "source": source_name,
                        "advertiser": ad.get("advertiser_name", ad.get("nickname", "Trader")),
                        "price": float(ad["price"]),
                        "available": float(ad.get("available_amount", ad.get("amount", 0))),
                        "min": float(ad.get("min_amount", 0)),
                        "max": float(ad.get("max_amount", 0))
                    })
                except Exception:
                    continue
        
        print(f"   ✅ {source_name}: {len(clean)} ads", file=sys.stderr)
        return clean
        
    except Exception as e:
        print(f"   ❌ {market} error: {e}", file=sys.stderr)
        return []


# --- 2. MARKET SNAPSHOT ---
def capture_market_snapshot():
    """Gets current market data from Binance, MEXC, Bybit."""
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_bin_api = ex.submit(lambda: fetch_p2p_army_ads("binance", "SELL"))
        f_mexc = ex.submit(lambda: fetch_p2p_army_ads("mexc", "SELL"))
        f_byb = ex.submit(lambda: fetch_bybit("1"))

        bin_data = f_bin_api.result() or []
        mexc_data = f_mexc.result() or []
        bybit_data = f_byb.result() or []

    # Fallback for Binance if API fails
    if not bin_data:
        print("   > Binance API failed, trying direct scrape...", file=sys.stderr)
        bin_data = fetch_binance_direct("SELL")

    print(
        f"   Snapshot → Binance: {len(bin_data)}, MEXC: {len(mexc_data)}, Bybit: {len(bybit_data)}",
        file=sys.stderr
    )

    return bin_data + bybit_data + mexc_data


def load_market_state():
    """Load previous snapshot (from last GitHub Actions run ~5min ago)."""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, "r") as f:
                data = json.load(f)
                # Check if snapshot is too old (> 20 minutes)
                timestamp = data.get("timestamp", 0)
                age_minutes = (time.time() - timestamp) / 60
                if age_minutes > 20:
                    print(f"   ⚠️ Snapshot is {age_minutes:.1f} minutes old, resetting", file=sys.stderr)
                    return {}
                return data.get("state", {})
        except Exception:
            return {}
    return {}


def save_market_state(current_ads):
    """Save current snapshot with timestamp."""
    state = {}
    for ad in current_ads:
        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        state[key] = ad["available"]
    
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump({
            "timestamp": time.time(),
            "state": state
        }, f)


def detect_real_trades(current_ads, peg):
    """
    Detects REAL trades by comparing current vs previous inventory.
    Only includes Binance and MEXC (Bybit excluded - no reliable API).
    """
    prev_state = load_market_state()
    trades = []
    
    if not prev_state:
        print("   > No previous snapshot found (first run or reset)", file=sys.stderr)
        return trades

    for ad in current_ads:
        # 🚫 Skip Bybit (no reliable trade tracking)
        if ad['source'].lower() == 'bybit':
            continue
        
        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        if key in prev_state:
            prev = prev_state[key]
            curr = ad["available"]

            # Inventory Drop = Confirmed Trade
            if curr < prev:
                diff = prev - curr
                # Only report significant trades (>10 USDT)
                if diff > 10:
                    trades.append({
                        "type": "trade",
                        "source": ad["source"],
                        "user": ad["advertiser"],
                        "price": ad["price"] / peg,
                        "vol_usd": diff,
                        "timestamp": time.time()
                    })

    print(f"   > Detected {len(trades)} real trades", file=sys.stderr)
    return trades


def load_recent_trades():
    """Load trades from last 15 minutes."""
    if not os.path.exists(TRADES_FILE):
        return []
    
    try:
        with open(TRADES_FILE, "r") as f:
            all_trades = json.load(f)
        
        # Filter trades older than 15 minutes
        cutoff = time.time() - (TRADE_RETENTION_MINUTES * 60)
        recent = [t for t in all_trades if t.get("timestamp", 0) > cutoff]
        
        print(f"   > Loaded {len(recent)} recent trades (last 15min)", file=sys.stderr)
        return recent
    except Exception:
        return []


def save_trades(new_trades):
    """Append new trades to history and keep last 15 minutes."""
    recent = load_recent_trades()
    
    # Add new trades
    all_trades = recent + new_trades
    
    # Keep only last 15 minutes
    cutoff = time.time() - (TRADE_RETENTION_MINUTES * 60)
    filtered = [t for t in all_trades if t.get("timestamp", 0) > cutoff]
    
    with open(TRADES_FILE, "w") as f:
        json.dump(filtered, f)
    
    print(f"   > Saved {len(filtered)} trades to history", file=sys.stderr)


# --- 3. ANALYTICS ---
def analyze(prices, peg):
    """Stats on ETB prices (divided by USDT peg)."""
    if not prices:
        return None

    clean_prices = sorted(p for p in prices if 10 < p < 500)
    if len(clean_prices) < 2:
        return None

    adj = [p / peg for p in clean_prices]
    n = len(adj)

    try:
        quantiles = statistics.quantiles(adj, n=100, method="inclusive")
        p05 = quantiles[4]
        p10 = quantiles[9]
        q1 = quantiles[24]
        median = quantiles[49]
        q3 = quantiles[74]
        p95 = quantiles[94]
    except Exception:
        median = statistics.median(adj)
        p05 = adj[0]
        q1 = adj[int(n * 0.25)]
        q3 = adj[int(n * 0.75)]
        p95 = adj[-1]

    return {
        "median": median,
        "q1": q1,
        "q3": q3,
        "p05": p05,
        "p95": p95,
        "min": adj[0],
        "max": adj[-1],
        "raw_data": adj,
        "count": n
    }


# --- 4. HISTORY ---
def save_to_history(stats, official):
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["Timestamp", "Median", "Q1", "Q3", "Official"])
        w.writerow([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            round(stats["median"], 2),
            round(stats["q1"], 2),
            round(stats["q3"], 2),
            round(official, 2) if official else 0
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
            except Exception:
                pass

    return (
        d[-HISTORY_POINTS:],
        m[-HISTORY_POINTS:],
        q1[-HISTORY_POINTS:],
        q3[-HISTORY_POINTS:],
        off[-HISTORY_POINTS:]
    )


# --- 5. GRAPH GENERATOR ---
def generate_charts(stats, official_rate):
    if not GRAPH_ENABLED:
        return

    themes = [
        ("dark", GRAPH_FILENAME,
         {"bg": "#050505", "fg": "#00ff9d", "grid": "#222",
          "median": "#ff0055", "sec": "#00bfff", "fill": "#00ff9d", "alpha": 0.7}),
        ("light", GRAPH_LIGHT_FILENAME,
         {"bg": "#ffffff", "fg": "#1a1a1a", "grid": "#eee",
          "median": "#d63384", "sec": "#0d6efd", "fill": "#00a876", "alpha": 0.5})
    ]
    dates, medians, q1s, q3s, offs = load_history()

    for mode, filename, style in themes:
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
        fig.suptitle(
            f"ETB LIQUIDITY SCANNER: {datetime.datetime.now().strftime('%H:%M')}",
            fontsize=20,
            color=style["fg"],
            fontweight="bold",
            y=0.97
        )

        ax1 = fig.add_subplot(2, 1, 1)
        data = stats["raw_data"]
        y_jitter = [1 + random.uniform(-0.12, 0.12) for _ in data]
        ax1.scatter(data, y_jitter, color=style["fg"], alpha=style["alpha"], s=30, edgecolors="none")
        ax1.axvline(stats["median"], color=style["median"], linewidth=3)
        ax1.axvline(stats["q1"], color=style["sec"], linewidth=2, linestyle="--", alpha=0.6)
        ax1.axvline(stats["q3"], color=style["sec"], linewidth=2, linestyle="--", alpha=0.6)
        ax1.text(
            stats["median"],
            1.42,
            f"MEDIAN\n{stats['median']:.2f}",
            color=style["median"],
            ha="center",
            fontweight="bold"
        )
        ax1.text(
            stats["q1"],
            0.58,
            f"Q1\n{stats['q1']:.2f}",
            color=style["sec"],
            ha="right",
            va="top"
        )
        ax1.text(
            stats["q3"],
            0.58,
            f"Q3\n{stats['q3']:.2f}",
            color=style["sec"],
            ha="left",
            va="top"
        )
        if official_rate:
            ax1.axvline(official_rate, color=style["fg"], linestyle=":", linewidth=1.5)

        margin = (stats["p95"] - stats["p05"]) * 0.1
        if margin == 0:
            margin = 1
        ax1.set_xlim([stats["p05"] - margin, stats["p95"] + margin])
        ax1.set_ylim(0.5, 1.5)
        ax1.set_yticks([])
        ax1.set_title("Live Market Depth (Smart Zoom)", color=style["fg"], loc="left", pad=10)
        ax1.grid(True, axis="x", color=style["grid"], linestyle="--")

        ax2 = fig.add_subplot(2, 1, 2)
        if len(dates) > 1:
            ax2.fill_between(dates, q1s, q3s, color=style["fill"], alpha=0.2, linewidth=0)
            ax2.plot(dates, medians, color=style["median"], linewidth=2)
            if any(offs):
                ax2.plot(dates, offs, color=style["fg"], linestyle="--", linewidth=1, alpha=0.5)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            ax2.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f"))
            ax2.yaxis.tick_right()
            ax2.grid(True, color=style["grid"], linewidth=0.5)
            ax2.set_title("Historical Trend (24h)", color=style["fg"], loc="left")
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        plt.savefig(filename, dpi=150, facecolor=style["bg"])
        plt.close()


# --- 6. WEB GENERATOR ---
def update_website_html(stats, official, timestamp, grouped_ads, peg):
    prem = ((stats["median"] - official) / official) * 100 if official else 0
    cache_buster = int(time.time())

    # Table
    table_rows = ""
    for source, ads in grouped_ads.items():
        prices = [a["price"] for a in ads]
        s = analyze(prices, peg) if prices else None
        if s:
            table_rows += (
                f"<tr><td class='source-col'>{source}</td>"
                f"<td>{s['min']:.2f}</td>"
                f"<td>{s['q1']:.2f}</td>"
                f"<td class='med-col'>{s['median']:.2f}</td>"
                f"<td>{s['q3']:.2f}</td>"
                f"<td>{s['max']:.2f}</td>"
                f"<td>{s['count']}</td></tr>"
            )
        else:
            table_rows += (
                f"<tr><td>{source}</td>"
                f"<td colspan='6' style='opacity:0.5'>No Data</td></tr>"
            )

    # Real Trades Feed (last 15 minutes)
    recent_trades = load_recent_trades()
    feed_html = ""

    if recent_trades:
        # Sort by timestamp (newest first)
        recent_trades.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        
        for trade in recent_trades[:30]:  # Show max 30 trades
            timestamp = trade.get("timestamp", time.time())
            trade_time = datetime.datetime.fromtimestamp(timestamp)
            time_str = trade_time.strftime("%I:%M:%S %p")
            
            # Time ago
            age_seconds = time.time() - timestamp
            if age_seconds < 60:
                age_str = f"{int(age_seconds)}s ago"
            else:
                age_str = f"{int(age_seconds/60)}min ago"
            
            # Source color
            source = trade.get("source", "Unknown")
            if "Binance" in source:
                s_col = "#f3ba2f"
                icon = "🟡"
            elif "MEXC" in source:
                s_col = "#2e55e6"
                icon = "🔵"
            else:
                s_col = "#888"
                icon = "⚪"
            
            feed_html += f"""
            <div class="feed-item">
                <div class="feed-icon" style="background:#2ea043">{icon}</div>
                <div class="feed-content">
                    <span class="feed-ts">{time_str}</span> <span style="color:#666">({age_str})</span> → 
                    <span class="feed-source" style="color:{s_col};font-weight:bold">{source}</span>: 
                    <span class="feed-user">{trade['user'][:15]}</span> 
                    <b style="color:#2ea043">SOLD</b> 
                    <span class="feed-vol">{trade['vol_usd']:,.2f} USDT</span> 
                    @ <span class="feed-price">{trade['price']:.2f} ETB</span>
                </div>
            </div>"""
    else:
        feed_html = "<div class='feed-item' style='color:#888'>⏳ No trades detected in last 15 minutes. Trades will appear here when inventory drops are detected between GitHub Actions runs.</div>"

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="300">
        <title>ETB Market Watch v30.4</title>
        <style>
            :root {{ --bg: #050505; --card: #111; --text: #00ff9d; --sub: #ccc; --mute: #666; --accent: #ff0055; --link: #00bfff; --gold: #ffcc00; --border: #333; }}
            [data-theme="light"] {{ --bg: #f4f4f9; --card: #fff; --text: #1a1a1a; --sub: #333; --mute: #888; --accent: #d63384; --link: #0d6efd; --gold: #ffc107; --border: #ddd; }}
            
            body {{ background: var(--bg); color: var(--text); font-family: 'Courier New', monospace; margin: 0; padding: 20px; text-align: center; transition: 0.3s; }}
            .container {{ max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 2fr 1fr; gap: 20px; text-align: left; }}
            
            header {{ grid-column: span 2; text-align: center; margin-bottom: 20px; position: relative; }}
            h1 {{ font-size: 2.5rem; margin: 0; text-shadow: 0 0 10px var(--text); }}
            .toggle {{ position: absolute; top: 0; right: 0; cursor: pointer; padding: 8px 16px; border: 1px solid var(--border); border-radius: 20px; background: var(--card); color: var(--sub); font-size: 0.8rem; }}
            
            .left-col, .right-col {{ display: flex; flex-direction: column; gap: 20px; }}
            .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); }}
            
            .ticker {{ text-align: center; padding: 30px; background: linear-gradient(145deg, var(--card), var(--bg)); }}
            .price {{ font-size: 4rem; font-weight: bold; color: var(--sub); margin: 10px 0; }}
            .prem {{ color: var(--gold); font-size: 0.9rem; display: block; margin-top: 10px; }}
            
            .chart img {{ width: 100%; border-radius: 8px; display: block; border: 1px solid var(--border); transition: 0.3s; }}
            
            table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
            th {{ text-align: left; padding: 12px; border-bottom: 2px solid var(--border); color: var(--text); }}
            td {{ padding: 12px; border-bottom: 1px solid var(--border); color: var(--sub); }}
            .source-col {{ font-weight: bold; color: var(--text); }} .med-col {{ color: var(--accent); font-weight: bold; }}
            
            .feed-title {{ font-size: 1.1rem; font-weight: bold; margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; color: var(--text); }}
            .feed-container {{ max-height: 600px; overflow-y: auto; padding-right: 5px; }}
            .feed-item {{ display: flex; gap: 12px; padding: 10px; border-bottom: 1px solid var(--border); align-items: center; }}
            .feed-icon {{ width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; flex-shrink: 0; color: #fff; }}
            .feed-content {{ font-size: 0.85rem; color: var(--sub); }}
            .feed-ts {{ color: var(--mute); font-family: monospace; }}
            .feed-user, .feed-price {{ font-weight: bold; color: var(--text); }}
            .feed-vol {{ font-weight: bold; color: var(--link); }}
            .feed-source {{ font-weight: bold; }}
            
            footer {{ grid-column: span 2; margin-top: 40px; text-align: center; color: var(--mute); font-size: 0.7rem; }}
            @media (max-width: 900px) {{ .container {{ grid-template-columns: 1fr; }} header, footer {{ grid-column: span 1; }} .price {{ font-size: 3rem; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>ETB MARKET INTELLIGENCE</h1>
                <div style="color:var(--mute); letter-spacing:4px; font-size:0.8rem;">/// REAL-TIME P2P TRACKER (15min window) ///</div>
                <div class="toggle" onclick="toggleTheme()">🌓 Theme</div>
            </header>

            <div class="left-col">
                <div class="card ticker">
                    <div style="color:var(--mute); font-size:0.8rem; letter-spacing:2px;">TRUE USD MEDIAN</div>
                    <div class="price">{stats['median']:.2f} <span style="font-size:1.5rem;color:var(--mute)">ETB</span></div>
                    <span class="prem">Black Market Premium: +{prem:.2f}%</span>
                </div>
                <div class="card chart">
                    <img src="{GRAPH_FILENAME}?v={cache_buster}" id="chartImg" alt="Market Chart">
                </div>
                <div class="card">
                    <table>
                        <thead>
                            <tr><th>Source</th><th>Min</th><th>Q1</th><th>Med</th><th>Q3</th><th>Max</th><th>Ads</th></tr>
                        </thead>
                        <tbody>{table_rows}</tbody>
                    </table>
                </div>
            </div>

            <div class="right-col">
                <div class="card">
                    <div class="feed-title">🟡 Binance | 🔵 MEXC | Real Trades (Last 15min)</div>
                    <div class="feed-container">{feed_html}</div>
                </div>
            </div>

            <footer>
                Official Bank Rate: {official:.2f} ETB | Last Update: {timestamp} UTC | 
                🔄 Updates every 5min via GitHub Actions
            </footer>
        </div>

        <script>
            const imgDark = "{GRAPH_FILENAME}?v={cache_buster}";
            const imgLight = "{GRAPH_LIGHT_FILENAME}?v={cache_buster}";
            const html = document.documentElement;
            
            (function() {{
                const theme = localStorage.getItem('theme') || 'dark';
                html.setAttribute('data-theme', theme);
                document.getElementById('chartImg').src = theme === 'light' ? imgLight : imgDark;
            }})();
            
            function toggleTheme() {{
                const current = html.getAttribute('data-theme');
                const next = current === 'light' ? 'dark' : 'light';
                html.setAttribute('data-theme', next);
                localStorage.setItem('theme', next);
                document.getElementById('chartImg').src = next === 'light' ? imgLight : imgDark;
            }}
        </script>
    </body>
    </html>
    """
    with open(HTML_FILENAME, "w") as f:
        f.write(html)
    print("✅ Website generated.", file=sys.stderr)


# --- 7. MAIN ---
def main():
    print("🔍 Running v30.4 Real Trades Only Scan...", file=sys.stderr)

    # 1. Get current market snapshot
    current_snapshot = capture_market_snapshot()
    
    official = fetch_official_rate() or 0.0
    peg = fetch_usdt_peg() or 1.0

    # Group by source for table
    grouped_ads = {"Binance": [], "Bybit": [], "MEXC": []}
    for ad in current_snapshot:
        src = ad.get("source")
        if src in grouped_ads:
            grouped_ads[src].append(ad)

    if current_snapshot:
        # Detect real trades (compares with snapshot from last run)
        new_trades = detect_real_trades(current_snapshot, peg)
        
        # Save new trades to history
        if new_trades:
            save_trades(new_trades)
        
        # Save current snapshot for next run
        save_market_state(current_snapshot)

        # Global stats & history EXCLUDE BYBIT
        stats_prices = [ad["price"] for ad in current_snapshot if ad.get("source") != "Bybit"]
        stats = analyze(stats_prices, peg) if stats_prices else None

        if stats:
            save_to_history(stats, official)
            generate_charts(stats, official)
            update_website_html(
                stats,
                official,
                time.strftime("%Y-%m-%d %H:%M:%S"),
                grouped_ads,
                peg
            )
        else:
            print("⚠️ Could not compute stats.", file=sys.stderr)
            fallback_stats = {
                "median": 0, "q1": 0, "q3": 0,
                "p05": 0, "p95": 0,
                "min": 0, "max": 0,
                "raw_data": [], "count": 0
            }
            update_website_html(
                fallback_stats,
                official,
                time.strftime("%Y-%m-%d %H:%M:%S"),
                grouped_ads,
                peg
            )
    else:
        print("⚠️ CRITICAL: No ads found.", file=sys.stderr)

    print("✅ Update Complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
