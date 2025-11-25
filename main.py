#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v45.0 (Ultimate Merge)
- FEATURE 1: "Liquidity Table" (Purple) -> Matches P2P Army 1:1 (Capped at 10k).
- FEATURE 2: "Transaction Tracker" (Green/Red) -> Calculates "Bought Today" by watching changes.
- LOGIC: Runs a loop. If an ad's inventory drops, it records a "Buy".
- FILTER: Ignores fake whale movements to prevent fake volume spikes.
"""

import requests
import sys
import time
import os
import json
import datetime
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HTML_FILENAME = "index.html"
TRADES_FILE = "recent_trades.json"
SNAPSHOT_FILE = "market_state.json"
REFRESH_RATE = 45  # Check for trades every 45s
VOLUME_CAP = 10000.0  # P2P Army Cap for Liquidity Table
WHALE_IGNORE_THRESHOLD = 20000.0 # Ignore "Trades" larger than this (likely fake ad removal)

# --- FETCHERS ---
def fetch_official_rate():
    try:
        return float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=5).json()["rates"]["ETB"])
    except: return 120.0

def fetch_usdt_peg():
    try:
        return float(requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd", timeout=5).json()["tether"]["usd"])
    except: return 1.00

def fetch_p2p_army_exchange(market, side="SELL"):
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    ads = []
    h = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "X-APIKEY": P2P_ARMY_KEY}
    
    try:
        payload = {"market": market, "fiat": "ETB", "asset": "USDT", "side": side, "limit": 1000}
        r = requests.post(url, headers=h, json=payload, timeout=15)
        data = r.json()
        candidates = data.get("result", data.get("data", data.get("ads", [])))
        if not candidates and isinstance(data, list): candidates = data
        
        if candidates:
            for ad in candidates:
                item = ad.get('adv', ad) 
                try:
                    price = float(item.get('price', 0))
                    vol_keys = ['tradableQuantity', 'available_amount', 'surplus_amount', 'surplusAmount', 'stock']
                    vol = 0.0
                    for key in vol_keys:
                        if key in item and item[key] is not None:
                            try:
                                v = float(item[key])
                                if v > 0:
                                    vol = v
                                    break
                            except: continue
                    
                    if price > 0 and vol > 0:
                        ads.append({
                            'source': market.upper(),
                            'advertiser': item.get('advertiser', {}).get('nickName', item.get('advertiser_name', 'User')),
                            'price': price,
                            'available': vol,
                            'type': side.lower()
                        })
                except: continue
    except Exception as e:
        print(f"   ⚠️ {market} {side}: {e}", file=sys.stderr)
    return ads

def capture_market_snapshot():
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = []
        for exchange in ['binance', 'mexc', 'okx']:
            futures.append(ex.submit(lambda e=exchange: fetch_p2p_army_exchange(e, "SELL")))
            futures.append(ex.submit(lambda e=exchange: fetch_p2p_army_exchange(e, "BUY")))
        f_peg = ex.submit(fetch_usdt_peg)
        f_off = ex.submit(fetch_official_rate)
        
        all_ads = []
        for f in futures: all_ads.extend(f.result() or [])
        return all_ads, f_peg.result() or 1.0, f_off.result() or 120.0

# --- TRADE DETECTION LOGIC ---
def load_state():
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'r') as f: return json.load(f)
        except: pass
    return {}

def save_state(ads):
    state = {}
    for ad in ads:
        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        state[key] = ad['available']
    with open(SNAPSHOT_FILE, 'w') as f: json.dump(state, f)

def detect_trades(current_ads):
    prev_state = load_state()
    if not prev_state: return []
    
    trades = []
    for ad in current_ads:
        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        if key in prev_state:
            prev_vol = prev_state[key]
            curr_vol = ad['available']
            diff = abs(prev_vol - curr_vol)
            
            # Logic: If inventory DROPPED, someone bought.
            # Filter: Ignore tiny dust (<5) and huge fake spikes (>20k)
            if 5 < diff < WHALE_IGNORE_THRESHOLD:
                if curr_vol < prev_vol:
                    # If Advertiser (SELL side) inventory drops -> User BOUGHT
                    # If Advertiser (BUY side) inventory drops -> User SOLD
                    trade_type = 'buy' if ad['type'] == 'sell' else 'sell'
                    trades.append({
                        'type': trade_type,
                        'source': ad['source'],
                        'vol': diff,
                        'price': ad['price'],
                        'time': time.time()
                    })
    return trades

def update_trade_history(new_trades):
    history = []
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f: history = json.load(f)
        except: pass
    
    # Add new, sort desc, keep last 24h
    history.extend(new_trades)
    cutoff = time.time() - 86400
    history = [t for t in history if t['time'] > cutoff]
    
    with open(TRADES_FILE, 'w') as f: json.dump(history, f)
    return history

# --- HTML GENERATOR ---
def update_html(ads, history, official, peg):
    # 1. LIQUIDITY STATS (Capped at 10k Logic)
    liq_stats = {ex: {'buy_c':0,'sell_c':0,'buy_v':0,'sell_v':0,'icon':i} 
                 for ex, i in [('BINANCE','🟡'),('OKX','⚫'),('MEXC','🟢')]}
    
    for ad in ads:
        if ad['source'] in liq_stats:
            s = liq_stats[ad['source']]
            capped_vol = min(ad['available'], VOLUME_CAP)
            if ad['type'] == 'buy':
                s['buy_c'] += 1
                s['buy_v'] += capped_vol
            else:
                s['sell_c'] += 1
                s['sell_v'] += capped_vol

    # 2. TRADE STATS (24h)
    t_stats = {'buy_c':0, 'sell_c':0, 'buy_v':0, 'sell_v':0}
    feed_html = ""
    for t in sorted(history, key=lambda x: x['time'], reverse=True):
        if t['type'] == 'buy':
            t_stats['buy_c'] += 1
            t_stats['buy_v'] += t['vol']
        else:
            t_stats['sell_c'] += 1
            t_stats['sell_v'] += t['vol']
            
        # Generate top 10 feed items
        if len(feed_html.split('div class="feed-item"')) < 11:
            ago = int(time.time() - t['time'])
            ago_str = f"{ago//60}m" if ago > 60 else f"{ago}s"
            color = "#00C805" if t['type'] == 'buy' else "#FF3B30"
            arrow = "↗" if t['type'] == 'buy' else "↘"
            feed_html += f"""
            <div class="feed-item">
                <span style="color:{color}; font-size:18px; width:20px">{arrow}</span>
                <span style="color:#888; font-size:12px; width:50px">{ago_str}</span>
                <span style="color:#fff; font-weight:bold">${t['vol']:,.0f}</span>
                <span style="color:#666; font-size:12px">via {t['source']}</span>
            </div>
            """

    # 3. BUILD TABLE ROWS
    table_rows = ""
    rank = 1
    t_liq = {'bc':0,'sc':0,'bv':0,'sv':0}
    
    for ex in ['BINANCE', 'OKX', 'MEXC']:
        d = liq_stats[ex]
        total_c = d['buy_c'] + d['sell_c']
        total_v = d['buy_v'] + d['sell_v']
        t_liq['bc']+=d['buy_c']; t_liq['sc']+=d['sell_c']
        t_liq['bv']+=d['buy_v']; t_liq['sv']+=d['sell_v']
        
        table_rows += f"""
        <tr>
            <td style="text-align:center; opacity:0.5">{rank}</td>
            <td><span style="font-size:16px">{d['icon']}</span> <b>{ex} P2P</b></td>
            <td style="text-align:right">{d['buy_c']}</td>
            <td style="text-align:right">{d['sell_c']}</td>
            <td style="text-align:right; font-weight:bold">{total_c}</td>
            <td style="text-align:right">${d['buy_v']:,.0f}</td>
            <td style="text-align:right">${d['sell_v']:,.0f}</td>
            <td style="text-align:right; font-weight:bold">${total_v:,.0f}</td>
        </tr>
        """
        rank += 1
        
    totals_row = f"""
    <tr style="background:#3b305e; font-weight:bold; border-top:2px solid #5a4b8a">
        <td></td><td>TOTAL</td>
        <td style="text-align:right">{t_liq['bc']}</td>
        <td style="text-align:right">{t_liq['sc']}</td>
        <td style="text-align:right">{t_liq['bc']+t_liq['sc']}</td>
        <td style="text-align:right">${t_liq['bv']:,.0f}</td>
        <td style="text-align:right">${t_liq['sv']:,.0f}</td>
        <td style="text-align:right">${t_liq['bv']+t_liq['sv']:,.0f}</td>
    </tr>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>ETB Terminal</title>
        <meta http-equiv="refresh" content="45">
        <style>
            body {{ background:#1a1a2e; color:#fff; font-family:sans-serif; margin:0; padding:20px; }}
            .grid {{ display:grid; grid-template-columns: 2fr 1fr; gap:20px; max-width:1400px; margin:0 auto; }}
            .card {{ background:#22223a; border-radius:12px; padding:20px; margin-bottom:20px; border:1px solid #333355; }}
            h3 {{ margin:0 0 15px 0; font-size:16px; opacity:0.7; text-transform:uppercase; letter-spacing:1px; }}
            
            /* TRANSACTIONS CARD */
            .tx-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:15px; }}
            .tx-box {{ background:rgba(255,255,255,0.03); padding:15px; border-radius:8px; text-align:center; }}
            .tx-val {{ font-size:28px; font-weight:bold; display:block; }}
            .tx-lbl {{ font-size:12px; opacity:0.5; }}
            
            /* TABLE */
            table {{ width:100%; border-collapse:collapse; background:#262640; border-radius:8px; overflow:hidden; }}
            th {{ background:#362b59; padding:12px; text-align:right; font-size:12px; color:#aaa; }}
            td {{ padding:10px; border-bottom:1px solid #363655; text-align:right; font-size:14px; }}
            tr:last-child td {{ border:none; }}
            
            /* FEED */
            .feed-item {{ display:flex; align-items:center; padding:8px 0; border-bottom:1px solid #333; }}
        </style>
    </head>
    <body>
        <div class="grid">
            <div>
                <div class="card">
                    <h3>🔴 Live Liquidity (Ads Volume)</h3>
                    <div style="font-size:12px; color:#aaa; margin-bottom:10px">
                        Matches P2P Army: Capped at 10,000 USDT max per ad.
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th style="text-align:center">#</th><th style="text-align:left">Exchange</th>
                                <th>Buy Ads</th><th>Sell Ads</th><th style="color:#fff">Total</th>
                                <th>**Buy Vol</th><th>**Sell Vol</th><th style="color:#fff">Total Vol</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows}{totals_row}</tbody>
                    </table>
                </div>

                <div class="card" style="display:flex; justify-content:space-around; text-align:center">
                    <div>
                        <div style="font-size:32px; font-weight:bold; color:#4caf50">${t_liq['bv']+t_liq['sv']:,.0f}</div>
                        <div style="font-size:12px; opacity:0.5">TOTAL LIQUIDITY AVAILABLE</div>
                    </div>
                    <div>
                        <div style="font-size:32px; font-weight:bold">{official:.2f}</div>
                        <div style="font-size:12px; opacity:0.5">OFFICIAL RATE</div>
                    </div>
                </div>
            </div>

            <div>
                <div class="card">
                    <h3>⚡ Transactions (24h Est.)</h3>
                    <div class="tx-grid">
                        <div class="tx-box" style="border-bottom:3px solid #00C805">
                            <div class="tx-lbl" style="color:#00C805">BOUGHT TODAY</div>
                            <span class="tx-val">${t_stats['buy_v']:,.0f}</span>
                            <span style="font-size:12px">{t_stats['buy_c']} Trades</span>
                        </div>
                        <div class="tx-box" style="border-bottom:3px solid #FF3B30">
                            <div class="tx-lbl" style="color:#FF3B30">SOLD TODAY</div>
                            <span class="tx-val">${t_stats['sell_v']:,.0f}</span>
                            <span style="font-size:12px">{t_stats['sell_c']} Trades</span>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <h3>Recent Trades</h3>
                    {feed_html}
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    with open(HTML_FILENAME, "w", encoding="utf-8") as f: f.write(html)

def main():
    print("🚀 ETB Ultimate Terminal Started...", file=sys.stderr)
    while True:
        try:
            # 1. Capture Snapshot
            ads, peg, off = capture_market_snapshot()
            
            # 2. Detect Trades (Compare with prev snapshot)
            new_trades = detect_trades(ads)
            history = update_trade_history(new_trades)
            save_state(ads)
            
            # 3. Update UI
            update_html(ads, history, off, peg)
            
            # 4. Log
            t_buy_v = sum(t['vol'] for t in history if t['type']=='buy')
            print(f"✅ Refreshed. Liquidity: OK | Bought Today: ${t_buy_v:,.0f} | Waiting {REFRESH_RATE}s...", file=sys.stderr)
            
        except Exception as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            
        time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    main()
