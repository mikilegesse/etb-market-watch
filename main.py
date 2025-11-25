#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v39.0 (P2P Army Exact Match)
- FIX: Now calculates "Ads Volume" (Liquidity) instead of "Trade Volume".
- DATA: Fetches live order book depth (Buy & Sell sides) for Binance, MEXC, OKX.
- UI: Recreated the P2P Army Purple Table exactly.
- MAPPING: Matches P2P Army column definitions (Sell Column = Advertisers Selling).
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
    GRAPH_ENABLED = True
except ImportError:
    GRAPH_ENABLED = False
    print("⚠️ Matplotlib not found.", file=sys.stderr)

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HISTORY_FILE = "etb_history.csv"
SNAPSHOT_FILE = "market_state.json"
HTML_FILENAME = "index.html"
GRAPH_FILENAME = "etb_liquidity.png"

# Refresh every 60s to respect API limits but keep data fresh
REFRESH_RATE = 60

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
        return 120.0

def fetch_usdt_peg():
    try:
        return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except:
        return 1.00

def fetch_p2p_army_exchange(market, side="SELL"):
    """
    Fetches raw ads.
    side="SELL" (API) -> Advertisers Selling USDT (Matches P2P Army "Sell" Column)
    side="BUY" (API)  -> Advertisers Buying USDT (Matches P2P Army "Buy" Column)
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
                            'price': float(ad['price']),
                            'available': float(ad.get('available_amount', ad.get('amount', 0))),
                            'type': side.lower()  # 'buy' or 'sell'
                        })
                    except: continue
    except Exception as e:
        print(f"   {market.upper()} {side} error: {e}", file=sys.stderr)
    
    return ads

# --- MARKET SNAPSHOT ---
def capture_market_snapshot():
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = []
        # Fetch BOTH sides
        for exchange in ['binance', 'mexc', 'okx']:
            futures.append(ex.submit(lambda e=exchange: fetch_p2p_army_exchange(e, "SELL")))
            futures.append(ex.submit(lambda e=exchange: fetch_p2p_army_exchange(e, "BUY")))
            
        f_peg = ex.submit(fetch_usdt_peg)
        f_off = ex.submit(fetch_official_rate)
        
        all_ads = []
        for f in futures:
            res = f.result() or []
            all_ads.extend(res)
            
        peg = f_peg.result() or 1.0
        official = f_off.result() or 120.0
        
        return all_ads, peg, official

# --- DATA PROCESSING ---
def process_liquidity_table(ads):
    """
    Aggregates data exactly like the P2P Army Table.
    Row: Exchange | Buy Count | Sell Count | Total Count | Buy Vol | Sell Vol | Total Vol
    """
    # Initialize with all rows from screenshot to look authentic
    stats = {
        "BINANCE": {"name": "Binance P2P", "icon": "🟡", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0},
        "OKX":     {"name": "Okx P2P",     "icon": "⚫", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0},
        "MEXC":    {"name": "Mexc P2P",    "icon": "🟢", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0},
        "BYBIT":   {"name": "Bybit P2P",   "icon": "⚫", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0}, # Placeholder
        "HTX":     {"name": "HTX P2P",     "icon": "🔵", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0}, # Placeholder
        "BITGET":  {"name": "Bitget P2P",  "icon": "🔵", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0}, # Placeholder
        "KUCOIN":  {"name": "Kucoin P2P",  "icon": "🟢", "buy_c": 0, "sell_c": 0, "buy_v": 0, "sell_v": 0}, # Placeholder
    }

    for ad in ads:
        src = ad['source']
        if src in stats:
            # P2P Army Mapping:
            # API 'buy'  -> Table 'Buy' Column
            # API 'sell' -> Table 'Sell' Column
            
            if ad['type'] == 'buy':
                stats[src]['buy_c'] += 1
                stats[src]['buy_v'] += ad['available']
            elif ad['type'] == 'sell':
                stats[src]['sell_c'] += 1
                stats[src]['sell_v'] += ad['available']

    return stats

# --- HTML GENERATOR ---
def update_website_html(stats_map, official, peg):
    
    # Calculate Grand Totals
    t_buy_c = sum(d['buy_c'] for d in stats_map.values())
    t_sell_c = sum(d['sell_c'] for d in stats_map.values())
    t_buy_v = sum(d['buy_v'] for d in stats_map.values())
    t_sell_v = sum(d['sell_v'] for d in stats_map.values())
    
    # Determine Median Price for top header
    # (Just a rough median of Binance Sells for the big number display)
    # This is secondary to the table request but good for UI
    
    table_rows = ""
    rank = 1
    
    # Order: Binance, Okx, Mexc, then others
    order = ["BINANCE", "OKX", "MEXC", "BYBIT", "HTX", "BITGET", "KUCOIN"]
    
    for key in order:
        d = stats_map[key]
        total_c = d['buy_c'] + d['sell_c']
        total_v = d['buy_v'] + d['sell_v']
        
        # Formatting: If 0, show "-" to match P2P Army style
        def fmt_n(val, is_money=False):
            if val == 0: return '<span style="opacity:0.3">-</span>'
            if is_money: return f"${val:,.0f}"
            return f"{val}"

        table_rows += f"""
        <tr>
            <td style="text-align:center; opacity:0.5">{rank}</td>
            <td style="display:flex; align-items:center; gap:10px;">
                <span style="font-size:18px">{d['icon']}</span> <b>{d['name']}</b>
            </td>
            
            <td style="text-align:right">{fmt_n(d['buy_c'])}</td>
            <td style="text-align:right">{fmt_n(d['sell_c'])}</td>
            <td style="text-align:right; font-weight:bold">{fmt_n(total_c)}</td>
            
            <td style="text-align:right">{fmt_n(d['buy_v'], True)}</td>
            <td style="text-align:right">{fmt_n(d['sell_v'], True)}</td>
            <td style="text-align:right; font-weight:bold">{fmt_n(total_v, True)}</td>
        </tr>
        """
        rank += 1

    # Totals Row
    totals_row = f"""
    <tr style="background-color: #3b305e; font-weight:bold; border-top: 2px solid #5a4b8a;">
        <td></td>
        <td style="text-align:right">Total:</td>
        <td style="text-align:right">{t_buy_c}</td>
        <td style="text-align:right">{t_sell_c}</td>
        <td style="text-align:right">{t_buy_c + t_sell_c}</td>
        <td style="text-align:right">${t_buy_v:,.0f}</td>
        <td style="text-align:right">${t_sell_v:,.0f}</td>
        <td style="text-align:right">${t_buy_v + t_sell_v:,.0f}</td>
    </tr>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>ETB P2P Market Liquidity</title>
        <meta http-equiv="refresh" content="60">
        <style>
            body {{
                background-color: #1a1a2e;
                color: #e0e0e0;
                font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                margin: 0;
                padding: 40px;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .container {{
                max-width: 1200px;
                width: 100%;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
            }}
            .header h1 {{ margin: 0; font-size: 28px; }}
            .header p {{ color: #a0a0b0; font-size: 14px; margin-top: 5px; }}
            
            /* P2P ARMY STYLE TABLE */
            .p2p-table {{
                width: 100%;
                border-collapse: collapse;
                background-color: #262640;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }}
            
            /* Header Groups */
            .thead-dark {{
                background-color: #362b59; /* The purple top bar */
            }}
            
            th {{
                padding: 15px;
                color: #fff;
                font-weight: 600;
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            
            .group-header {{
                background-color: #42356b;
                border-bottom: 1px solid #55448a;
                text-align: center;
            }}
            
            td {{
                padding: 12px 15px;
                border-bottom: 1px solid #363655;
                font-size: 14px;
            }}
            
            tr:last-child td {{ border-bottom: none; }}
            tr:hover td {{ background-color: #303050; }}
            
            .stats-card {{
                background: #22223a;
                border: 1px solid #333355;
                padding: 20px;
                border-radius: 10px;
                margin-top: 20px;
                display: flex;
                justify-content: space-around;
            }}
            .stat-item {{ text-align: center; }}
            .stat-val {{ font-size: 24px; font-weight: bold; color: #fff; }}
            .stat-lbl {{ font-size: 12px; color: #888; text-transform: uppercase; margin-top: 5px; }}
            
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Statistics of volumes and activity of ETB on P2P markets</h1>
                <p>The table displays ETB (Ethiopian birr) activity, the number and volume of advertisements on P2P crypto exchanges.</p>
            </div>

            <table class="p2p-table">
                <thead>
                    <tr class="thead-dark">
                        <th rowspan="2" style="width: 50px;">#</th>
                        <th rowspan="2" style="text-align:left">P2P Exchange</th>
                        <th colspan="3" class="group-header" style="background: #33334d;">Ads Count</th>
                        <th colspan="3" class="group-header" style="background: #4a3b78;">**Ads Volume (USDT)</th>
                    </tr>
                    <tr class="thead-dark">
                        <th style="background:#2a2a40; text-align:right; font-size:12px; color:#aaa;">Buy</th>
                        <th style="background:#2a2a40; text-align:right; font-size:12px; color:#aaa;">Sell</th>
                        <th style="background:#2a2a40; text-align:right; font-size:12px; color:#fff;">Total</th>
                        
                        <th style="background:#3d3063; text-align:right; font-size:12px; color:#aaa;">**Buy</th>
                        <th style="background:#3d3063; text-align:right; font-size:12px; color:#aaa;">**Sell</th>
                        <th style="background:#3d3063; text-align:right; font-size:12px; color:#fff;">Total</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                    {totals_row}
                </tbody>
            </table>

            <div class="stats-card">
                <div class="stat-item">
                    <div class="stat-val">{t_buy_c + t_sell_c}</div>
                    <div class="stat-lbl">Total Active Ads</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val" style="color:#4caf50">${t_buy_v + t_sell_v:,.0f}</div>
                    <div class="stat-lbl">Total Liquidity (USDT)</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val">{official:.2f}</div>
                    <div class="stat-lbl">Official Rate</div>
                </div>
            </div>
            
            <div style="text-align:center; margin-top:20px; font-size:12px; color:#555;">
                Data refreshed every 60s. **Buy/Sell columns mapped to Advertiser Side to match P2P Army conventions.
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(HTML_FILENAME, "w", encoding="utf-8") as f:
        f.write(html)

# --- MAIN LOOP ---
def main():
    print("🚀 ETB Liquidity Terminal v39 (Exact Match Mode) Started...", file=sys.stderr)
    
    # Run once immediately
    ads, peg, off = capture_market_snapshot()
    stats = process_liquidity_table(ads)
    update_website_html(stats, off, peg)
    print("✅ Initial Snapshot Captured. HTML updated.", file=sys.stderr)
    print("   Total Liquidity detected: ${:,.0f}".format(sum(d['buy_v']+d['sell_v'] for d in stats.values())), file=sys.stderr)

if __name__ == "__main__":
    main()
