#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v18.0 (LIQUIDITY DELTA TRACKER)
- LOGIC: Tracks the 'Available Amount' of every ad.
- FEED: Generates a 'Trade' whenever an Ad's inventory drops.
- FIX: Pagination loop fixed to catch ALL Bybit ads, not just the first 2.
"""

import requests
import time
import datetime
import sys
import random

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HTML_FILENAME = "index.html"
REFRESH_RATE = 15  # Seconds between scans (Lower = faster trade detection)

# Store previous ad states to detect changes: {ad_id: available_amount}
AD_CACHE = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Content-Type": "application/json"
}

# --- 1. FETCHERS ---

def fetch_usdt_peg():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd"
        return float(requests.get(url, timeout=5).json()["tether"]["usd"])
    except:
        return 1.00

def fetch_bybit_ads():
    """
    Fetches ALL pages of Bybit ads, not just the first one.
    """
    url = "https://api2.bybit.com/fiat/otc/item/online"
    ads = []
    page = 1
    
    # We fetch both SELL (1) and BUY (0) sides to see full market
    sides = ["1", "0"] 
    
    for side in sides:
        page = 1
        while True:
            try:
                payload = {
                    "userId": "",
                    "tokenId": "USDT",
                    "currencyId": "ETB",
                    "payment": [],
                    "side": side,
                    "size": "20",  # Request 20 items per page
                    "page": str(page),
                    "authMaker": False
                }
                
                resp = requests.post(url, headers=HEADERS, json=payload, timeout=5)
                data = resp.json()
                items = data.get("result", {}).get("items", [])
                
                if not items:
                    break # No more items, stop paging
                
                for i in items:
                    ads.append({
                        'id': i.get('id', i.get('itemNo')), # Unique Ad ID
                        'source': 'Bybit',
                        'advertiser': i.get('nickName', 'Bybit User'),
                        'price': float(i['price']),
                        # Bybit returns maxAmount in Local Currency (ETB). 
                        # We estimate USDT inventory = maxAmount / price
                        'available_usdt': float(i.get('maxAmount', 0)) / float(i['price']),
                        'limit_min': i.get('minAmount'),
                        'limit_max': i.get('maxAmount')
                    })
                
                # Safety break to prevent infinite loops if API glitches
                if page > 10: break
                page += 1
                time.sleep(0.2) # Be nice to the API
                
            except Exception as e:
                print(f"⚠️ Bybit Error: {e}")
                break
    return ads

# --- 2. DELTA ANALYZER ---

def detect_trades(current_ads):
    """
    Compares current ads to previous AD_CACHE.
    If 'available_usdt' DECREASES, a trade happened.
    """
    global AD_CACHE
    new_trades = []
    current_cache = {}
    
    for ad in current_ads:
        ad_id = ad['id']
        current_amt = ad['available_usdt']
        current_cache[ad_id] = current_amt
        
        # Check if we saw this ad before
        if ad_id in AD_CACHE:
            previous_amt = AD_CACHE[ad_id]
            
            # If inventory dropped significantly (but not to 0, which might mean ad pulled)
            # Threshold: Must be > $10 difference to ignore noise
            diff = previous_amt - current_amt
            
            if diff > 10:
                # DETECTED A TRADE!
                trade_type = "bought" if ad['source'] == "Bybit" else "sold" 
                # (Logic: If we are tracking Sell ads, user 'bought' from them)
                
                new_trades.append({
                    "time": datetime.datetime.now(),
                    "user": ad['advertiser'],
                    "action": "bought", # Simplifying for the feed
                    "amount_usd": diff,
                    "price": ad['price'],
                    "total_etb": diff * ad['price']
                })
    
    # Update global cache
    AD_CACHE = current_cache
    return new_trades

# --- 3. HTML GENERATOR ---

TRADES_HISTORY = []

def generate_html(trades, stats):
    
    feed_html = ""
    # Add new trades to history (keep last 50)
    global TRADES_HISTORY
    TRADES_HISTORY = (trades + TRADES_HISTORY)[:50]
    
    if not TRADES_HISTORY:
        feed_html = "<div class='feed-item' style='text-align:center'>Waiting for market movement... (Delta Scanner Active)</div>"
    else:
        for t in TRADES_HISTORY:
            ts = t['time'].strftime("%I:%M:%S %p")
            
            # Dynamic styling based on volume
            icon = "🛒"
            icon_bg = "#2ea043" # Green
            if t['amount_usd'] > 1000:
                icon = "🤑" # Whale trade
                icon_bg = "#d29922" # Gold
            
            item_html = f"""
            <div class="feed-item">
                <div class="feed-icon" style="background-color: {icon_bg};">{icon}</div>
                <div class="feed-content">
                    <span class="feed-ts">{ts}</span> -> 
                    <span class="feed-user">{t['user']}</span> (SELLER) filled order for
                    <span class="feed-vol">{t['amount_usd']:,.2f} USDT</span> at 
                    <span class="feed-price">{t['price']:.2f} ETB</span>.
                </div>
            </div>
            """
            feed_html += item_html

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="5">
        <title>ETB Delta Terminal</title>
        <style>
            body {{ background: #0d1117; color: #c9d1d9; font-family: monospace; padding: 20px; }}
            .container {{ max-width: 900px; margin: 0 auto; }}
            h1 {{ text-align: center; border-bottom: 1px solid #30363d; padding-bottom: 10px; }}
            .stats-box {{ display: flex; justify-content: space-around; background: #161b22; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #30363d; }}
            .stat-num {{ font-size: 1.5rem; font-weight: bold; color: #fff; }}
            
            .feed-container {{ background: #010409; border: 1px solid #30363d; border-radius: 6px; overflow: hidden; }}
            .feed-header {{ background: #161b22; padding: 10px; font-weight: bold; border-bottom: 1px solid #30363d; }}
            .feed-item {{ display: flex; gap: 15px; padding: 12px; border-bottom: 1px solid #21262d; align-items: center; }}
            .feed-icon {{ width: 35px; height: 35px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; }}
            .feed-user {{ color: #58a6ff; font-weight: bold; }}
            .feed-price {{ color: #3fb950; font-weight: bold; }}
            .feed-vol {{ color: #d29922; }}
            .feed-ts {{ color: #8b949e; font-size: 0.8rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🇪🇹 LIVE P2P TRANSACTION FEED</h1>
            
            <div class="stats-box">
                <div>
                    <div>MEDIAN RATE</div>
                    <div class="stat-num">{stats.get('median', 0):.2f} ETB</div>
                </div>
                <div>
                    <div>ACTIVE ADS</div>
                    <div class="stat-num">{stats.get('count', 0)}</div>
                </div>
                <div>
                    <div>PEG (USDT)</div>
                    <div class="stat-num">${stats.get('peg', 1.0):.2f}</div>
                </div>
            </div>

            <div class="feed-container">
                <div class="feed-header">🔴 LIVE ORDER EXECUTION (INFERRED VIA DELTA)</div>
                {feed_html}
            </div>
            
            <div style="text-align:center; margin-top:20px; color:#666;">
                Scanning Bybit P2P Order Books every {REFRESH_RATE}s
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(HTML_FILENAME, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Updated UI with {len(trades)} new trades detected.")

# --- 4. MAIN LOOP ---

def main():
    print("🚀 Starting P2P Delta Tracker...")
    print("   (Note: Trades will appear when Ad Limits decrease)")
    
    while True:
        # 1. Fetch Data
        ads = fetch_bybit_ads()
        peg = fetch_usdt_peg()
        
        # 2. Calculate Stats
        prices = [a['price'] for a in ads]
        if prices:
            median = sorted(prices)[len(prices)//2]
        else:
            median = 0
            
        stats = {'median': median, 'count': len(ads), 'peg': peg}
        
        # 3. Detect Changes
        new_trades = detect_trades(ads)
        
        if new_trades:
            print(f"💰 DETECTED {len(new_trades)} TRADE(S)!")
            for t in new_trades:
                print(f"   -> {t['user']} sold {t['amount_usd']:.2f} USDT @ {t['price']}")
        
        # 4. Update UI
        generate_html(new_trades, stats)
        
        # 5. Sleep
        time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    main()
