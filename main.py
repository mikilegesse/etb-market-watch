#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v30.2 (MEXC Fix + Trade Logic)
- FIX: Robust JSON parsing for MEXC (handles all API formats)
- FIX: Min/Max column order corrected
- LOGIC: Excludes Bybit from trade detection
- DATA: Enhanced error handling and fallback API routing
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

# --- CONFIGURATION ---
P2P_ARMY_KEY = "YJU5RCZ2-P6VTVNNA"
HISTORY_FILE = "etb_history.csv"
SNAPSHOT_FILE = "market_state.json"
GRAPH_FILENAME = "etb_neon_terminal.png"
GRAPH_LIGHT_FILENAME = "etb_light_terminal.png"
HTML_FILENAME = "index.html"
BURST_WAIT_TIME = 30  # Seconds to detect inventory drops

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- 1. FETCHERS ---
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

def fetch_p2p_army_ads(market, side):
    """Universal p2p.army parser (works for Binance/MEXC)"""
    url = "https://p2p.army/v1/api/get_p2p_order_book"
    h = HEADERS.copy()
    h["X-APIKEY"] = P2P_ARMY_KEY
    ads = []

    try:
        payload = {"market": market, "fiat": "ETB", "asset": "USDT", "side": side, "limit": 100}
        r = requests.post(url, headers=h, json=payload, timeout=10)
        data = r.json()

        # Handle all possible response formats
        candidates = (
            data.get("result", {}).get("data", {}).get("ads")
            or data.get("data", {}).get("ads")
            or data.get("ads")
            or data.get("result")
            or []
        )

        # If it's a list directly
        if isinstance(candidates, list):
            raw_ads = candidates
        elif isinstance(candidates, dict):
            raw_ads = candidates.get("ads", [])
        else:
            raw_ads = []

        for ad in raw_ads:
            try:
                ads.append({
                    'source': market.upper(),
                    'advertiser': ad.get('advertiser_name', 'Trader'),
                    'price': float(ad['price']),
                    'available': float(ad.get('available_amount', 0)),
                    'min': float(ad.get('min_amount', 0)),
                    'max': float(ad.get('max_amount', 0))
                })
            except:
                continue

        print(f"✅ {market.upper()} fetched {len(ads)} ads")
        return ads

    except Exception as e:
        print(f"⚠️ {market.upper()} fetch failed: {e}")
        return []

def fetch_bybit(side):
    """Simple Bybit fetcher (for display only, not used for trade detection)"""
    url = "https://api2.bybit.com/fiat/otc/item/online"
    ads = []
    page = 1
    h = HEADERS.copy()
    h["Referer"] = "https://www.bybit.com/"

    while True:
        try:
            r = requests.post(url, headers=h, json={
                "userId": "", "tokenId": "USDT", "currencyId": "ETB",
                "payment": [], "side": side, "size": "50", "page": str(page)
            }, timeout=5)

            items = r.json().get("result", {}).get("items", [])
            if not items:
                break

            for i in items:
                ads.append({
                    'source': 'BYBIT',
                    'advertiser': i.get('nickName', 'Bybit User'),
                    'price': float(i.get('price')),
                    'available': float(i.get('lastQuantity', 0))
                })
            if page >= 3:
                break
            page += 1
        except:
            break
    print(f"✅ BYBIT fetched {len(ads)} ads")
    return ads

# --- 2. TRADE DETECTION ---
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
    trades = []

    for ad in current_ads:
        # Skip BYBIT entirely
        if ad['source'].upper() == "BYBIT":
            continue

        key = f"{ad['source']}_{ad['advertiser']}_{ad['price']}"
        if key in prev_state:
            prev = prev_state[key]
            curr = ad['available']
            if curr < prev:
                diff = prev - curr
                if diff > 5:
                    trades.append({
                        'type': 'trade',
                        'source': ad['source'],
                        'user': ad['advertiser'],
                        'price': ad['price'] / peg,
                        'vol_usd': diff
                    })
    return trades

# --- 3. ANALYTICS ---
def analyze(prices, peg):
    if not prices:
        return None
    clean = sorted([p / peg for p in prices if 50 < p < 400])
    if len(clean) < 2:
        return None

    try:
        q = statistics.quantiles(clean, n=100, method='inclusive')
        return {
            "median": q[49],
            "q1": q[24],
            "q3": q[74],
            "p05": q[4],
            "p95": q[94],
            "min": clean[0],
            "max": clean[-1],
            "raw_data": clean,
            "count": len(clean)
        }
    except:
        return None

# --- 4. MAIN ---
def main():
    print("🔍 Running v30.2 (MEXC FIX)...", file=sys.stderr)

    # --- SNAPSHOT 1 ---
    print("📸 Snapshot 1/2...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_bin = ex.submit(lambda: fetch_p2p_army_ads("binance", "SELL"))
        f_mxc = ex.submit(lambda: fetch_p2p_army_ads("mexc", "SELL"))
        f_byb = ex.submit(lambda: fetch_bybit("1"))
        snapshot1 = f_bin.result() + f_mxc.result() + f_byb.result()

    # --- WAIT ---
    print(f"⏳ Waiting {BURST_WAIT_TIME}s for trades...")
    time.sleep(BURST_WAIT_TIME)

    # --- SNAPSHOT 2 ---
    print("📸 Snapshot 2/2...")
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_bin2 = ex.submit(lambda: fetch_p2p_army_ads("binance", "SELL"))
        f_mxc2 = ex.submit(lambda: fetch_p2p_army_ads("mexc", "SELL"))
        f_byb2 = ex.submit(lambda: fetch_bybit("1"))
        f_off = ex.submit(fetch_official_rate)
        f_peg = ex.submit(fetch_usdt_peg)

        bin_ads = f_bin2.result()
        mexc_ads = f_mxc2.result()
        bybit_ads = f_byb2.result()
        official = f_off.result() or 0
        peg = f_peg.result() or 1

    all_ads = bin_ads + mexc_ads + bybit_ads
    grouped = {"Binance": bin_ads, "MEXC": mexc_ads, "Bybit": bybit_ads}

    # --- TRADE DETECTION ---
    trades = detect_real_trades(all_ads, peg)
    save_market_state(all_ads)

    # --- STATS ---
    prices = [x['price'] for x in all_ads]
    stats = analyze(prices, peg)
    if not stats:
        print("⚠️ No valid prices found.")
        return

    # --- OUTPUT ---
    print(f"✅ Median: {stats['median']:.2f}, Q1: {stats['q1']:.2f}, Q3: {stats['q3']:.2f}, Count: {stats['count']}")
    print(f"✅ {len(trades)} trades detected.")

if __name__ == "__main__":
    main()
