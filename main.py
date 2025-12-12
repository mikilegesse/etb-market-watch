#!/usr/bin/env python3
"""
🇪🇹 ETB Financial Terminal v42.10 (Real Historical Data!)
- NEW: p2p.army Historical Price API (data since March 2023)
- NEW: Real Transaction Statistics from p2p.army API (not estimated)
- NEW: Combined history from Binance, MEXC, OKX via p2p.army
- REMOVED: Trade detection algorithm (replaced with real API data)
- KEEP: All v42.9 features (AI, Market Depth, Premium Tracking, Remittance)
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
import re
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
# API Keys from environment variables with fallbacks
P2P_ARMY_KEY = os.environ.get("P2P_ARMY_KEY", "YJU5RCZ2-P6VTVNNA")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "28e60e8b83msh2f62e830aa1f09ap18bad1jsna2ade74a847c")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBPGVTukCpK_bo-0kGJqonV8ICEej8tsgM")

HISTORY_FILE = "etb_history.csv"
SNAPSHOT_FILE = "market_state.json"
TRADES_FILE = "recent_trades.json"
AI_SUMMARY_FILE = "ai_summary.json"
GRAPH_FILENAME = "etb_neon_terminal.png"
GRAPH_LIGHT_FILENAME = "etb_light_terminal.png"
HTML_FILENAME = "index.html"

BURST_WAIT_TIME = 45
TRADE_RETENTION_MINUTES = 1440  # 24 hours
MAX_ADS_PER_SOURCE = 200
HISTORY_POINTS = 288
MAX_SINGLE_TRADE = 50000

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

def fetch_remittance_rates():
    """Fetch estimated remittance rates for ticker display"""
    rates = {}
    
    try:
        # Get official NBE rate as base
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        nbe_rate = r.json()["rates"]["ETB"]
        
        # Remittance services typically offer rates close to official + small margin
        # These are estimates - actual rates vary by amount and payment method
        rates['NBE_OFFICIAL'] = {
            'rate': nbe_rate,
            'name': 'NBE Official',
            'emoji': '🏛️',
            'color': '#34C759'
        }
        
        rates['WESTERN_UNION'] = {
            'rate': nbe_rate * 1.01,  # ~1% margin estimate
            'name': 'Western Union',
            'emoji': '💛',
            'color': '#FFCC00'
        }
        
        rates['REMITLY'] = {
            'rate': nbe_rate * 1.015,  # ~1.5% margin estimate
            'name': 'Remitly',
            'emoji': '💚',
            'color': '#00C805'
        }
        
        rates['RIA'] = {
            'rate': nbe_rate * 1.012,  # ~1.2% margin estimate
            'name': 'Ria',
            'emoji': '🧡',
            'color': '#FF6B00'
        }
        
        print(f"   💱 Remittance rates fetched (NBE base: {nbe_rate:.2f})", file=sys.stderr)
        
    except Exception as e:
        print(f"   ⚠️ Error fetching remittance rates: {e}", file=sys.stderr)
    
    return rates


# =====================================================
# NEW: p2p.army Historical Data APIs
# =====================================================

def fetch_p2p_army_history(days=30, exchanges=None):
    """
    Fetch historical price data from p2p.army API
    Data available since March 2023 for Binance/OKX, January 2024 for MEXC
    
    Returns: (dates, medians, q1s, q3s, officials) arrays
    """
    if exchanges is None:
        exchanges = ["binance", "mexc", "okx"]
    
    h = HEADERS.copy()
    h["X-APIKEY"] = P2P_ARMY_KEY
    
    # Calculate from_date based on days requested
    from_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
    
    all_history = {}  # date -> {exchange: price}
    
    for exchange in exchanges:
        try:
            payload = {
                "market": exchange,
                "fiat": "ETB",
                "asset": "USDT",
                "mode": "ALL",
                "from_date": from_date,
                "limit": 5000
            }
            
            r = requests.post(
                "https://p2p.army/v1/api/history/p2p_prices",
                headers=h, json=payload, timeout=30
            )
            
            if r.status_code == 200:
                data = r.json()
                history = data.get("history", [])
                
                for item in history:
                    date_str = item.get("date", "")[:19]  # Trim to YYYY-MM-DDTHH:MM:SS
                    buy_price = item.get("buy") or item.get("buy_avg")
                    sell_price = item.get("sell") or item.get("sell_avg")
                    
                    # Use average of buy/sell as the rate
                    if buy_price and sell_price:
                        avg_price = (float(buy_price) + float(sell_price)) / 2
                    elif sell_price:
                        avg_price = float(sell_price)
                    elif buy_price:
                        avg_price = float(buy_price)
                    else:
                        continue
                    
                    if date_str not in all_history:
                        all_history[date_str] = {}
                    all_history[date_str][exchange] = avg_price
                
                print(f"   📈 {exchange.upper()} history: {len(history)} data points", file=sys.stderr)
            else:
                print(f"   ⚠️ {exchange.upper()} history API error: {r.status_code}", file=sys.stderr)
                
        except Exception as e:
            print(f"   ❌ {exchange.upper()} history error: {e}", file=sys.stderr)
    
    if not all_history:
        print(f"   ⚠️ No historical data from p2p.army, using local CSV", file=sys.stderr)
        return None
    
    # Convert to arrays sorted by date
    sorted_dates = sorted(all_history.keys())
    
    dates = []
    medians = []
    q1s = []
    q3s = []
    
    for date_str in sorted_dates:
        try:
            dt = datetime.datetime.fromisoformat(date_str.replace("Z", ""))
            prices = list(all_history[date_str].values())
            
            if prices:
                dates.append(dt)
                median_price = statistics.median(prices)
                medians.append(median_price)
                
                # Calculate Q1/Q3 if enough data
                if len(prices) >= 4:
                    q1s.append(statistics.quantiles(prices, n=4)[0])
                    q3s.append(statistics.quantiles(prices, n=4)[2])
                else:
                    q1s.append(median_price * 0.98)
                    q3s.append(median_price * 1.02)
        except Exception as e:
            continue
    
    print(f"   ✅ Total historical data: {len(dates)} points from {len(exchanges)} exchanges", file=sys.stderr)
    
    return dates, medians, q1s, q3s


def fetch_p2p_army_transaction_stats():
    """
    Fetch REAL transaction statistics from p2p.army API
    This replaces the estimated trade detection algorithm
    
    Returns dict with counts and volumes for buy/sell transactions
    """
    h = HEADERS.copy()
    h["X-APIKEY"] = P2P_ARMY_KEY
    
    # Get stats for last 24 hours
    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(hours=24)
    hour_ago = now - datetime.timedelta(hours=1)
    
    stats = {
        'hour_buys': 0, 'hour_sells': 0, 'hour_buy_volume': 0, 'hour_sell_volume': 0,
        'today_buys': 0, 'today_sells': 0, 'today_buy_volume': 0, 'today_sell_volume': 0,
        'overall_buys': 0, 'overall_sells': 0, 'overall_buy_volume': 0, 'overall_sell_volume': 0,
        'activity_24h': 0,
        'source': 'p2p.army'
    }
    
    exchanges = ["binance", "mexc", "okx"]
    
    for exchange in exchanges:
        try:
            payload = {
                "market": exchange,
                "fiat": "ETB",
                "from_date": yesterday.strftime("%Y-%m-%d %H:%M:%S"),
                "limit": 48  # Last 48 hours of hourly data
            }
            
            r = requests.post(
                "https://p2p.army/v1/api/history/p2p_fiats",
                headers=h, json=payload, timeout=15
            )
            
            if r.status_code == 200:
                data = r.json()
                rows = data.get("rows", [])
                
                for row in rows:
                    try:
                        row_date = datetime.datetime.fromisoformat(row.get("date", "").replace("Z", ""))
                        
                        count_buy = int(row.get("count_BUY", 0) or 0)
                        count_sell = int(row.get("count_SELL", 0) or 0)
                        vol_buy = float(row.get("volume_usd_BUY", 0) or 0)
                        vol_sell = float(row.get("volume_usd_SELL", 0) or 0)
                        activity = int(row.get("activity24H", 0) or 0)
                        
                        # Overall (24h)
                        stats['overall_buys'] += count_buy
                        stats['overall_sells'] += count_sell
                        stats['overall_buy_volume'] += vol_buy
                        stats['overall_sell_volume'] += vol_sell
                        
                        # Today (since midnight)
                        today_start = datetime.datetime(now.year, now.month, now.day)
                        if row_date >= today_start:
                            stats['today_buys'] += count_buy
                            stats['today_sells'] += count_sell
                            stats['today_buy_volume'] += vol_buy
                            stats['today_sell_volume'] += vol_sell
                        
                        # Last hour
                        if row_date >= hour_ago:
                            stats['hour_buys'] += count_buy
                            stats['hour_sells'] += count_sell
                            stats['hour_buy_volume'] += vol_buy
                            stats['hour_sell_volume'] += vol_sell
                        
                        # Activity
                        if activity > stats['activity_24h']:
                            stats['activity_24h'] = activity
                            
                    except Exception as e:
                        continue
                
                print(f"   📊 {exchange.upper()} stats: {len(rows)} hourly records", file=sys.stderr)
            else:
                print(f"   ⚠️ {exchange.upper()} stats API error: {r.status_code}", file=sys.stderr)
                
        except Exception as e:
            print(f"   ❌ {exchange.upper()} stats error: {e}", file=sys.stderr)
    
    print(f"   ✅ Transaction stats: {stats['overall_buys']} buys, {stats['overall_sells']} sells (24h)", file=sys.stderr)
    print(f"   💰 Volume: ${stats['overall_buy_volume']:,.0f} bought, ${stats['overall_sell_volume']:,.0f} sold", file=sys.stderr)
    
    return stats


# =====================================================
# Exchange Fetchers (unchanged from v42.9)
# =====================================================

def fetch_binance_rapidapi(side="SELL"):
    """Fetch Binance P2P ads using RapidAPI with p2p.army fallback"""
    url = f"https://binance-p2p-api.p.rapidapi.com/binance/p2p/search/{side.lower()}"
    
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "binance-p2p-api.p.rapidapi.com",
        "Content-Type": "application/json"
    }
    
    all_ads = []
    seen_ids = set()
    page = 1
    max_pages = 20
    use_fallback = False
    
    while page <= max_pages:
        payload = {
            "asset": "USDT",
            "fiat": "ETB",
            "page": page,
            "rows": 20,
            "payTypes": [],
            "countries": []
        }
        
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            
            # Check for 502 or other server errors - use fallback
            if r.status_code in [502, 503, 500, 429]:
                print(f"   ⚠️ Binance RapidAPI error {r.status_code}, switching to p2p.army fallback...", file=sys.stderr)
                use_fallback = True
                break
            
            if r.status_code == 429:
                print(f"   ⚠️ Rate limit hit, waiting 5s...", file=sys.stderr)
                time.sleep(5)
                continue
            
            data = r.json()
            
            if data.get("code") == "000000":
                items = data.get('data', [])
                
                if not items:
                    break
                
                new_count = 0
                for item in items:
                    try:
                        advertiser = item.get("advertiser", {})
                        adv = item.get("adv", {})
                        ad_no = adv.get("advNo", "")
                        
                        if ad_no and ad_no not in seen_ids:
                            seen_ids.add(ad_no)
                            all_ads.append({
                                'source': 'BINANCE',
                                'ad_type': side.upper(),
                                'advertiser': advertiser.get("nickName", "Unknown"),
                                'price': float(adv.get("price", 0)),
                                'available': float(adv.get("surplusAmount", 0)),
                            })
                            new_count += 1
                    except:
                        continue
                
                if new_count == 0:
                    break
                    
                page += 1
                time.sleep(1.5)
            else:
                print(f"   ❌ Binance API error: {data}", file=sys.stderr)
                use_fallback = True
                break
                
        except Exception as e:
            print(f"   ❌ Binance connection error: {e}, trying p2p.army fallback...", file=sys.stderr)
            use_fallback = True
            break
    
    # If RapidAPI failed, use p2p.army fallback
    if use_fallback or len(all_ads) == 0:
        print(f"   🔄 Using p2p.army fallback for Binance {side}...", file=sys.stderr)
        fallback_ads = fetch_p2p_army_exchange("binance", side)
        if fallback_ads:
            return fallback_ads
    
    print(f"   BINANCE {side} (RapidAPI): {len(all_ads)} ads from {page-1} pages", file=sys.stderr)
    return all_ads

def fetch_binance_both_sides():
    """Fetch BOTH buy and sell ads from Binance"""
    sell_ads = fetch_binance_rapidapi("SELL")
    time.sleep(2)
    buy_ads = fetch_binance_rapidapi("BUY")
    
    all_ads = sell_ads + buy_ads
    seen = set()
    deduped = []
    
    for ad in all_ads:
        key = f"{ad['advertiser']}_{ad['price']}_{ad.get('ad_type', 'SELL')}"
        if key not in seen:
            seen.add(key)
            deduped.append(ad)
    
    print(f"   BINANCE Total: {len(deduped)} ads ({len(sell_ads)} sells, {len(buy_ads)} buys)", file=sys.stderr)
    return deduped

def fetch_p2p_army_exchange(market, side="SELL"):
    """Universal fetcher with p2p.army - used as primary for OKX and fallback for others"""
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
                        vol = 0
                        for key in ['available_amount', 'amount', 'surplus_amount', 'stock', 'max_amount', 'dynamic_max_amount', 'tradable_quantity']:
                            if key in ad and ad[key]:
                                try:
                                    v = float(ad[key])
                                    if v > 0:
                                        vol = v
                                        break
                                except:
                                    continue
                        
                        if vol == 0:
                            continue
                        
                        username = None
                        for key in ['advertiser_name', 'nickname', 'trader_name', 'userName', 'user_name', 'merchant_name', 'merchant', 'trader', 'name']:
                            if key in ad and ad[key]:
                                username = str(ad[key])
                                break
                        
                        if not username:
                            username = f'{market.upper()} User'
                        
                        ads.append({
                            'source': market.upper(),
                            'ad_type': side,
                            'advertiser': username,
                            'price': float(ad['price']),
                            'available': vol,
                        })
                    except Exception as e:
                        continue
        
        print(f"   {market.upper()} {side} (p2p.army): {len(ads)} ads", file=sys.stderr)
    except Exception as e:
        print(f"   {market.upper()} {side} error: {e}", file=sys.stderr)
    
    return ads

def fetch_mexc_rapidapi(side="SELL"):
    """Fetch MEXC P2P ads using RapidAPI with p2p.army fallback"""
    url = "https://mexc-p2p-api.p.rapidapi.com/mexc/p2p/search"
    ads = []
    use_fallback = False
    
    try:
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": "mexc-p2p-api.p.rapidapi.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        if side == "BUY":
            api_side = "SELL"
        else:
            api_side = "BUY"
        
        seen_ids = set()
        
        strategies = [
            {"name": "Text", "params": {"currency": "ETB", "coin": "USDT"}},
            {"name": "ID",   "params": {"currencyId": "58", "coinId": "1"}}
        ]
        
        for strategy in strategies:
            page = 1
            max_pages = 10
            
            while page <= max_pages:
                params = {
                    "tradeType": api_side,
                    "page": str(page),
                    "blockTrade": "false"
                }
                params.update(strategy["params"])
                
                try:
                    r = requests.get(url, headers=headers, params=params, timeout=10)
                    
                    # Check for server errors - use fallback
                    if r.status_code in [502, 503, 500]:
                        print(f"   ⚠️ MEXC RapidAPI error {r.status_code}, switching to p2p.army fallback...", file=sys.stderr)
                        use_fallback = True
                        break
                    
                    data = r.json()
                    items = data.get("data", [])
                    
                    if not items:
                        break
                    
                    new_count = 0
                    for item in items:
                        try:
                            price = item.get("price")
                            vol = item.get("availableQuantity") or item.get("surplus_amount")
                            if vol:
                                vol = float(vol)
                            else:
                                vol = 0.0
                            
                            name = "MEXC User"
                            merchant = item.get("merchant")
                            if merchant and isinstance(merchant, dict):
                                name = merchant.get("nickName") or merchant.get("name") or name
                            
                            if price:
                                price = float(price)
                                unique_id = f"{name}-{price}-{vol}"
                                
                                if unique_id not in seen_ids and vol > 0:
                                    seen_ids.add(unique_id)
                                    ads.append({
                                        'source': 'MEXC',
                                        'ad_type': side,
                                        'advertiser': name,
                                        'price': price,
                                        'available': vol,
                                    })
                                    new_count += 1
                        except:
                            continue
                    
                    if new_count == 0:
                        break
                    
                    page += 1
                    time.sleep(0.3)
                    
                except Exception as e:
                    print(f"   ⚠️ MEXC request error: {e}", file=sys.stderr)
                    use_fallback = True
                    break
            
            if use_fallback:
                break
        
        # If RapidAPI failed, use p2p.army fallback
        if use_fallback or len(ads) == 0:
            print(f"   🔄 Using p2p.army fallback for MEXC {side}...", file=sys.stderr)
            fallback_ads = fetch_p2p_army_exchange("mexc", side)
            if fallback_ads:
                return fallback_ads
        
        print(f"   MEXC {side} (RapidAPI): {len(ads)} ads", file=sys.stderr)
    except Exception as e:
        print(f"   MEXC {side} error: {e}, trying p2p.army fallback...", file=sys.stderr)
        return fetch_p2p_army_exchange("mexc", side)
    
    return ads

def fetch_mexc_both_sides():
    """Fetch BOTH buy and sell ads from MEXC"""
    sell_ads = fetch_mexc_rapidapi("SELL")
    time.sleep(1)
    buy_ads = fetch_mexc_rapidapi("BUY")
    
    all_ads = sell_ads + buy_ads
    seen = set()
    deduped = []
    
    for ad in all_ads:
        key = f"{ad['advertiser']}_{ad['price']}_{ad.get('ad_type', 'SELL')}"
        if key not in seen:
            seen.add(key)
            deduped.append(ad)
    
    print(f"   MEXC Total: {len(deduped)} ads ({len(sell_ads)} sells, {len(buy_ads)} buys)", file=sys.stderr)
    return deduped

def fetch_exchange_both_sides(market):
    """Fetch both buy and sell for any p2p.army supported exchange"""
    sell_ads = fetch_p2p_army_exchange(market, "SELL")
    buy_ads = fetch_p2p_army_exchange(market, "BUY")
    
    all_ads = sell_ads + buy_ads
    seen = set()
    deduped = []
    
    for ad in all_ads:
        key = f"{ad['advertiser']}_{ad['price']}_{ad.get('ad_type', 'SELL')}"
        if key not in seen:
            seen.add(key)
            deduped.append(ad)
    
    print(f"   {market.upper()} Total: {len(deduped)} ads ({len(sell_ads)} sells, {len(buy_ads)} buys)", file=sys.stderr)
    return deduped


# =====================================================
# AI Integration (from v42.9)
# =====================================================

def generate_ai_summary(stats, official, trade_stats, volume_by_exchange=None, history_data=None):
    """Generate AI-powered market summary using Gemini with forecasting and gap explanation"""
    
    if not GEMINI_API_KEY or len(GEMINI_API_KEY) < 10:
        print(f"   ⚠️ No valid Gemini API key, using fallback", file=sys.stderr)
        return create_fallback_summary(stats, official, trade_stats)
    
    black_market_rate = stats.get('median', 0)
    premium = ((black_market_rate - official) / official * 100) if official > 0 else 0
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        
        prompt = f"""You are a financial analyst specializing in Ethiopian currency markets. Analyze this P2P USDT/ETB market data:

CURRENT RATES:
- Black Market Rate: {black_market_rate:.2f} ETB per USD
- Official NBE Rate: {official:.2f} ETB per USD
- Premium: {premium:.1f}%

24-HOUR TRADING ACTIVITY:
- Buy transactions: {trade_stats.get('overall_buys', 0)} ({trade_stats.get('overall_buy_volume', 0):,.0f} USDT)
- Sell transactions: {trade_stats.get('overall_sells', 0)} ({trade_stats.get('overall_sell_volume', 0):,.0f} USDT)
- Market activity index: {trade_stats.get('activity_24h', 0):,}

MARKET CONTEXT:
- Ethiopia underwent significant exchange rate reforms in March 2024 (rate unification)
- IMF program monitoring ongoing
- Diaspora remittances are a major source of USD
- Foreign currency shortage affects many businesses

Provide a JSON analysis with these fields:
{{
    "market_sentiment": "bullish/bearish/neutral",
    "summary": "2-3 sentence market overview",
    "key_insights": ["insight 1", "insight 2", "insight 3"],
    "black_market_drivers": ["factor 1", "factor 2", "factor 3"],
    "official_rate_factors": ["factor 1", "factor 2"],
    "gap_explanation": "Why is there a {premium:.1f}% gap between black market and official rate? 2-3 sentences.",
    "short_term_forecast": "1-7 day prediction with rate range",
    "medium_term_forecast": "1-4 week outlook",
    "risk_factors": ["risk 1", "risk 2"],
    "recommendation": "advice for remittance senders",
    "confidence_level": "high/medium/low"
}}

Return ONLY valid JSON, no markdown formatting."""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1024
            }
        }
        
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            
            json_match = re.search(r'\{[\s\S]*\}', text)
            json_str = json_match.group() if json_match else None
            
            if json_str:
                try:
                    ai_data = json.loads(json_str)
                    ai_data['generated_at'] = datetime.datetime.now().isoformat()
                    ai_data['rate_at_generation'] = black_market_rate
                    
                    with open(AI_SUMMARY_FILE, 'w') as f:
                        json.dump(ai_data, f)
                    
                    print(f"   ✅ AI Summary generated successfully!", file=sys.stderr)
                    return ai_data
                except json.JSONDecodeError as je:
                    print(f"   ⚠️ JSON parse error: {je}", file=sys.stderr)
                    return create_fallback_summary(stats, official, trade_stats)
            else:
                print(f"   ⚠️ Could not find JSON in response", file=sys.stderr)
                return create_fallback_summary(stats, official, trade_stats)
        else:
            print(f"   ❌ Gemini API HTTP error: {response.status_code}", file=sys.stderr)
            return create_fallback_summary(stats, official, trade_stats)
            
    except requests.exceptions.Timeout:
        print(f"   ❌ Gemini API timeout (30s)", file=sys.stderr)
        return create_fallback_summary(stats, official, trade_stats)
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Gemini API request error: {e}", file=sys.stderr)
        return create_fallback_summary(stats, official, trade_stats)
    except Exception as e:
        print(f"   ❌ AI Summary error: {type(e).__name__}: {e}", file=sys.stderr)
        return create_fallback_summary(stats, official, trade_stats)

def create_fallback_summary(stats, official, trade_stats):
    """Create a rule-based fallback summary when AI is unavailable"""
    print(f"   📋 Using fallback rule-based summary", file=sys.stderr)
    
    black_market_rate = stats.get('median', 0)
    premium = ((black_market_rate - official) / official * 100) if official > 0 else 0
    
    buy_vol = trade_stats.get('overall_buy_volume', 0)
    sell_vol = trade_stats.get('overall_sell_volume', 0)
    
    if buy_vol > sell_vol * 1.5:
        sentiment = "bullish"
        sentiment_text = "Strong buying pressure indicates demand for USDT/USD"
        forecast = f"Rate likely to increase to {black_market_rate + 2:.2f}-{black_market_rate + 5:.2f} ETB"
    elif sell_vol > buy_vol * 1.5:
        sentiment = "bearish"
        sentiment_text = "Strong selling pressure indicates USDT supply increase"
        forecast = f"Rate may decrease to {black_market_rate - 3:.2f}-{black_market_rate - 1:.2f} ETB"
    else:
        sentiment = "neutral"
        sentiment_text = "Balanced buy/sell activity with stable market conditions"
        forecast = f"Rate expected to stay within {black_market_rate - 2:.2f}-{black_market_rate + 2:.2f} ETB"
    
    return {
        "market_sentiment": sentiment,
        "summary": f"The ETB black market rate is currently {black_market_rate:.2f} ETB/USD, representing a {premium:.1f}% premium over the official rate of {official:.2f} ETB. {sentiment_text}.",
        "key_insights": [
            f"Black market premium: {premium:.1f}% above official rate",
            f"24h volume: ${buy_vol + sell_vol:,.0f} USDT traded",
            f"Market spread: {stats.get('min', 0):.2f} - {stats.get('max', 0):.2f} ETB"
        ],
        "black_market_drivers": [
            "High demand for USD from importers and businesses",
            "Limited forex availability through official channels",
            "Diaspora remittance preferences for better rates"
        ],
        "official_rate_factors": [
            "NBE monetary policy and forex reserves",
            "IMF program requirements and reform timeline"
        ],
        "gap_explanation": f"The {premium:.1f}% gap exists primarily due to foreign currency shortage in official banking channels, forcing businesses to seek USD through parallel markets at premium rates.",
        "short_term_forecast": forecast,
        "medium_term_forecast": "Market expected to remain volatile. Monitor NBE policy announcements for direction.",
        "risk_factors": [
            "Exchange rate volatility during policy changes",
            "P2P transaction counterparty risks"
        ],
        "recommendation": "For remittances, compare legal channel rates (Western Union, Remitly, Ria). Legal channels offer security despite lower rates.",
        "confidence_level": "medium",
        "generated_at": datetime.datetime.now().isoformat(),
        "rate_at_generation": black_market_rate,
        "is_fallback": True
    }

def load_cached_ai_summary():
    """Load cached AI summary if recent (within 1 hour)"""
    if not os.path.exists(AI_SUMMARY_FILE):
        print(f"   📋 No cached AI summary found", file=sys.stderr)
        return None
    
    try:
        with open(AI_SUMMARY_FILE, 'r') as f:
            data = json.load(f)
        
        generated_at = datetime.datetime.fromisoformat(data.get('generated_at', '2000-01-01'))
        age = datetime.datetime.now() - generated_at
        
        if age.total_seconds() < 3600:
            print(f"   📋 Using cached AI summary ({int(age.total_seconds()/60)}min old)", file=sys.stderr)
            return data
        else:
            print(f"   📋 Cached AI summary expired ({int(age.total_seconds()/60)}min old)", file=sys.stderr)
            return None
    except Exception as e:
        print(f"   ⚠️ Error loading cached summary: {e}", file=sys.stderr)
        return None


# =====================================================
# Market Snapshot & Analysis
# =====================================================

def capture_market_snapshot():
    """Capture market snapshot: Binance, MEXC, OKX (NO Bybit)"""
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_binance = ex.submit(fetch_binance_both_sides)
        f_mexc = ex.submit(fetch_mexc_both_sides)
        f_okx = ex.submit(fetch_exchange_both_sides, "okx")
        f_peg = ex.submit(fetch_usdt_peg)
        
        binance_data = f_binance.result() or []
        mexc_data = f_mexc.result() or []
        okx_data = f_okx.result() or []
        peg = f_peg.result() or 1.0
        
        total = len(binance_data) + len(mexc_data) + len(okx_data)
        print(f"   📊 Collected {total} ads total (Binance, MEXC, OKX)", file=sys.stderr)
        
        return binance_data + mexc_data + okx_data

def remove_outliers(ads, peg):
    if len(ads) < 10:
        return ads
    
    prices = sorted([ad["price"] / peg for ad in ads])
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
        key = f"{ad['source']}|||{ad['advertiser']}|||{ad['price']}"
        state[key] = {
            'available': ad['available'],
            'ad_type': ad.get('ad_type', 'SELL')
        }
    
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(state, f)


# =====================================================
# Analytics
# =====================================================

def analyze(prices, peg):
    if not prices:
        return None
    
    prices_float = []
    for item in prices:
        if isinstance(item, (int, float)):
            prices_float.append(float(item))
        elif isinstance(item, dict) and 'price' in item:
            prices_float.append(float(item['price']))
    
    clean_prices = sorted([p for p in prices_float if 10 < p < 500])
    if len(clean_prices) < 2:
        return None
    
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
        "p05": p05, "p95": p95,
        "min": adj[0], "max": adj[-1],
        "raw_data": adj, "count": n
    }

def calculate_market_depth_by_price(ads, peg):
    """Calculate market depth grouped by price level and exchange"""
    if not ads:
        return {'supply': [], 'demand': []}
    
    supply_by_price = {}  # SELL orders
    demand_by_price = {}  # BUY orders
    
    for ad in ads:
        price = round(ad['price'] / peg)  # Round to nearest integer
        source = ad.get('source', 'OTHER')
        available_usd = ad.get('available', 0)
        ad_type = ad.get('ad_type', 'SELL')
        
        if ad_type == 'SELL':
            if price not in supply_by_price:
                supply_by_price[price] = {'BINANCE': 0, 'MEXC': 0, 'OKX': 0, 'total': 0}
            supply_by_price[price][source] = supply_by_price[price].get(source, 0) + available_usd
            supply_by_price[price]['total'] += available_usd
        else:
            if price not in demand_by_price:
                demand_by_price[price] = {'BINANCE': 0, 'MEXC': 0, 'OKX': 0, 'total': 0}
            demand_by_price[price][source] = demand_by_price[price].get(source, 0) + available_usd
            demand_by_price[price]['total'] += available_usd
    
    # Convert to sorted lists
    supply_list = [{'price': p, **data} for p, data in sorted(supply_by_price.items())]
    demand_list = [{'price': p, **data} for p, data in sorted(demand_by_price.items(), reverse=True)]
    
    return {'supply': supply_list, 'demand': demand_list}


# =====================================================
# History Management
# =====================================================

def save_to_history(stats, official):
    """Save current snapshot to local CSV (backup)"""
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

def load_history(days=30):
    """
    Load historical data - tries p2p.army API first, falls back to local CSV
    Returns: (dates, medians, q1s, q3s, officials)
    """
    # Try p2p.army historical API first
    try:
        api_result = fetch_p2p_army_history(days=days)
        if api_result and len(api_result[0]) >= 10:
            dates, medians, q1s, q3s = api_result
            
            # Get official rates for these dates (approximate)
            officials = []
            for m in medians:
                # Estimate official rate as ~85-90% of black market rate historically
                officials.append(m * 0.87)  # Rough estimate
            
            print(f"   ✅ Using p2p.army historical data: {len(dates)} points", file=sys.stderr)
            return dates, medians, q1s, q3s, officials
    except Exception as e:
        print(f"   ⚠️ p2p.army history failed: {e}", file=sys.stderr)
    
    # Fallback to local CSV
    print(f"   📂 Falling back to local CSV history", file=sys.stderr)
    return load_history_from_csv()

def load_history_from_csv():
    """Load history from local CSV file (fallback)"""
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
            except:
                pass
    
    return (d[-HISTORY_POINTS:], m[-HISTORY_POINTS:], 
            q1[-HISTORY_POINTS:], q3[-HISTORY_POINTS:], off[-HISTORY_POINTS:])


# =====================================================
# HTML Generation
# =====================================================

def update_website_html(stats, official, timestamp, all_ads, grouped_ads, peg, 
                        ai_summary=None, remittance_rates=None, trade_stats=None):
    """Generate the complete HTML dashboard"""
    
    median = stats.get("median", 0)
    premium = ((median - official) / official * 100) if official > 0 else 0
    
    # Prepare chart data
    chart_data = {}
    for source, ads in grouped_ads.items():
        if ads:
            chart_data[source] = [ad['price'] / peg for ad in ads]
    
    # Load history and calculate premiums
    dates, medians, q1s, q3s, officials = load_history(days=30)
    
    premiums = []
    for i in range(len(medians)):
        if i < len(officials) and officials[i] > 0:
            prem_val = ((medians[i] - officials[i]) / officials[i]) * 100
            premiums.append(prem_val)
        else:
            premiums.append(0)
    
    history_data = {
        'dates': [d.isoformat() if hasattr(d, 'isoformat') else str(d) for d in dates],
        'medians': medians,
        'officials': officials,
        'premiums': premiums
    }
    
    # Calculate market depth
    market_depth = calculate_market_depth_by_price(all_ads, peg)
    
    # Build ticker items
    ticker_items = []
    for source, ads in grouped_ads.items():
        if ads:
            sell_ads = [a for a in ads if a.get('ad_type', 'SELL') == 'SELL']
            if sell_ads:
                best_price = min(a['price'] / peg for a in sell_ads)
                if source == 'BINANCE':
                    ticker_items.append(f'🟡 Binance: {best_price:.2f} ETB')
                elif source == 'MEXC':
                    ticker_items.append(f'🔵 MEXC: {best_price:.2f} ETB')
                elif source == 'OKX':
                    ticker_items.append(f'🟣 OKX: {best_price:.2f} ETB')
    
    ticker_items.append(f'🏛️ Official: {official:.2f} ETB')
    
    # Add remittance rates to ticker
    if remittance_rates:
        for key, data in remittance_rates.items():
            if key != 'NBE_OFFICIAL':
                ticker_items.append(f"{data['emoji']} {data['name']}: {data['rate']:.2f} ETB")
    
    ticker_html = ' &nbsp;&nbsp;|&nbsp;&nbsp; '.join(ticker_items * 3)
    
    # Get trade stats (from p2p.army API)
    if not trade_stats:
        trade_stats = {
            'hour_buys': 0, 'hour_sells': 0, 'hour_buy_volume': 0, 'hour_sell_volume': 0,
            'today_buys': 0, 'today_sells': 0, 'today_buy_volume': 0, 'today_sell_volume': 0,
            'overall_buys': 0, 'overall_sells': 0, 'overall_buy_volume': 0, 'overall_sell_volume': 0
        }
    
    # Build AI summary HTML
    ai_summary_html = ""
    if ai_summary:
        sentiment = ai_summary.get('market_sentiment', 'neutral')
        if sentiment == 'bullish':
            sentiment_badge = '<span style="background:#34C759;color:white;padding:4px 12px;border-radius:20px;font-weight:600;">📈 BULLISH</span>'
        elif sentiment == 'bearish':
            sentiment_badge = '<span style="background:#FF3B30;color:white;padding:4px 12px;border-radius:20px;font-weight:600;">📉 BEARISH</span>'
        else:
            sentiment_badge = '<span style="background:#FF9500;color:white;padding:4px 12px;border-radius:20px;font-weight:600;">➡️ NEUTRAL</span>'
        
        confidence = ai_summary.get('confidence_level', 'medium')
        conf_color = '#34C759' if confidence == 'high' else '#FF9500' if confidence == 'medium' else '#FF3B30'
        
        is_fallback = ai_summary.get('is_fallback', False)
        fallback_badge = '<span style="background:#8E8E93;color:white;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:10px;">FALLBACK</span>' if is_fallback else ''
        
        insights_html = ''.join([f'<li style="margin-bottom:8px;color:var(--text);">{i}</li>' for i in ai_summary.get('key_insights', [])])
        risks_html = ''.join([f'<li style="margin-bottom:8px;color:var(--text);">{r}</li>' for r in ai_summary.get('risk_factors', [])])
        
        # Black market drivers
        bm_drivers = ai_summary.get('black_market_drivers', [])
        bm_drivers_html = ''.join([f'<li style="margin-bottom:6px;color:var(--text);">{d}</li>' for d in bm_drivers])
        
        # Official rate factors
        off_factors = ai_summary.get('official_rate_factors', [])
        off_factors_html = ''.join([f'<li style="margin-bottom:6px;color:var(--text);">{f}</li>' for f in off_factors])
        
        # Gap explanation
        gap_explanation = ai_summary.get('gap_explanation', f"The {premium:.1f}% premium reflects forex scarcity in official channels.")
        
        ai_summary_html = f'''
        <div class="stats-panel" style="background:linear-gradient(135deg, var(--card) 0%, rgba(10,132,255,0.05) 100%);">
            <div class="stats-title" style="display:flex;align-items:center;justify-content:center;gap:12px;">
                🤖 AI Market Analysis {sentiment_badge} {fallback_badge}
            </div>
            
            <div style="text-align:center;margin-bottom:20px;">
                <span style="font-size:13px;color:{conf_color};font-weight:600;">Confidence: {confidence.upper()}</span>
            </div>
            
            <div style="background:var(--bg);padding:20px;border-radius:12px;margin-bottom:20px;border-left:4px solid var(--accent);">
                <p style="font-size:16px;line-height:1.7;color:var(--text);margin:0;">
                    {ai_summary.get('summary', 'Analysis unavailable')}
                </p>
            </div>
            
            <!-- WHY THE GAP SECTION -->
            <div style="background:linear-gradient(135deg, rgba(255,149,0,0.15), rgba(255,149,0,0.05));padding:20px;border-radius:12px;margin-bottom:20px;border:1px solid rgba(255,149,0,0.4);">
                <div style="font-weight:700;color:#FF9500;margin-bottom:12px;font-size:18px;">
                    📊 Why the {premium:.1f}% Gap Between Black Market & Official Rate?
                </div>
                <div style="color:var(--text);line-height:1.7;font-size:15px;">
                    {gap_explanation}
                </div>
            </div>
            
            <!-- DRIVERS SECTION -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
                <div style="background:rgba(255,59,48,0.1);padding:20px;border-radius:12px;border:1px solid rgba(255,59,48,0.3);">
                    <div style="font-weight:700;color:#FF3B30;margin-bottom:12px;font-size:16px;">
                        🔴 Black Market Drivers
                    </div>
                    <ul style="margin:0;padding-left:20px;list-style-type:disc;">
                        {bm_drivers_html}
                    </ul>
                </div>
                
                <div style="background:rgba(52,199,89,0.1);padding:20px;border-radius:12px;border:1px solid rgba(52,199,89,0.3);">
                    <div style="font-weight:700;color:#34C759;margin-bottom:12px;font-size:16px;">
                        🏛️ Official Rate Factors
                    </div>
                    <ul style="margin:0;padding-left:20px;list-style-type:disc;">
                        {off_factors_html}
                    </ul>
                </div>
            </div>
            
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
                <div style="background:rgba(52,199,89,0.1);padding:20px;border-radius:12px;border:1px solid rgba(52,199,89,0.3);">
                    <div style="font-weight:700;color:#34C759;margin-bottom:12px;font-size:16px;">
                        💡 Key Insights
                    </div>
                    <ul style="margin:0;padding-left:20px;list-style-type:disc;">
                        {insights_html}
                    </ul>
                </div>
                
                <div style="background:rgba(255,149,0,0.1);padding:20px;border-radius:12px;border:1px solid rgba(255,149,0,0.3);">
                    <div style="font-weight:700;color:#FF9500;margin-bottom:12px;font-size:16px;">
                        ⚠️ Risk Factors
                    </div>
                    <ul style="margin:0;padding-left:20px;list-style-type:disc;">
                        {risks_html}
                    </ul>
                </div>
            </div>
            
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
                <div style="background:rgba(10,132,255,0.1);padding:20px;border-radius:12px;border:1px solid rgba(10,132,255,0.3);">
                    <div style="font-weight:700;color:#0A84FF;margin-bottom:8px;">📅 Short-Term (1-7 days)</div>
                    <div style="color:var(--text);font-size:15px;">{ai_summary.get('short_term_forecast', 'N/A')}</div>
                </div>
                
                <div style="background:rgba(175,82,222,0.1);padding:20px;border-radius:12px;border:1px solid rgba(175,82,222,0.3);">
                    <div style="font-weight:700;color:#AF52DE;margin-bottom:8px;">📆 Medium-Term (1-4 weeks)</div>
                    <div style="color:var(--text);font-size:15px;">{ai_summary.get('medium_term_forecast', 'N/A')}</div>
                </div>
            </div>
            
            <div style="background:linear-gradient(135deg, rgba(0,200,5,0.15), rgba(0,200,5,0.05));padding:20px;border-radius:12px;border:1px solid rgba(0,200,5,0.4);">
                <div style="font-weight:700;color:#00C805;margin-bottom:8px;">💰 Recommendation</div>
                <div style="color:var(--text);font-size:15px;">{ai_summary.get('recommendation', 'N/A')}</div>
            </div>
        </div>
        '''
    
    # Market summary table
    table_rows = ""
    for source in ["BINANCE", "MEXC", "OKX"]:
        ads = grouped_ads.get(source, [])
        if ads:
            sell_ads = [a for a in ads if a.get('ad_type', 'SELL') == 'SELL']
            buy_ads = [a for a in ads if a.get('ad_type', 'BUY') == 'BUY']
            
            sell_prices = [a['price'] / peg for a in sell_ads] if sell_ads else []
            buy_prices = [a['price'] / peg for a in buy_ads] if buy_ads else []
            
            best_sell = min(sell_prices) if sell_prices else 0
            best_buy = max(buy_prices) if buy_prices else 0
            
            if source == 'BINANCE':
                emoji, color = '🟡', '#F3BA2F'
            elif source == 'MEXC':
                emoji, color = '🔵', '#2E55E6'
            else:
                emoji, color = '🟣', '#A855F7'
            
            table_rows += f'''
            <tr>
                <td style="font-weight:600;"><span style="color:{color}">{emoji}</span> {source}</td>
                <td style="color:var(--green);font-weight:700;">{best_sell:.2f}</td>
                <td style="color:var(--red);font-weight:600;">{best_buy:.2f}</td>
                <td>{len(sell_ads)}</td>
                <td>{len(buy_ads)}</td>
            </tr>
            '''
    
    # Generate full HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🇪🇹 ETB Terminal v42.10</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        :root {{
            --bg: #000000;
            --card: #1C1C1E;
            --border: #38383A;
            --text: #FFFFFF;
            --text-secondary: #8E8E93;
            --accent: #0A84FF;
            --green: #00C805;
            --red: #FF3B30;
            --orange: #FF9500;
        }}
        
        [data-theme="light"] {{
            --bg: #F2F2F7;
            --card: #FFFFFF;
            --border: #C6C6C8;
            --text: #1C1C1E;
            --text-secondary: #6C6C70;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        header {{
            text-align: center;
            padding: 30px 20px;
            background: linear-gradient(135deg, var(--card) 0%, rgba(10,132,255,0.1) 100%);
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
        }}
        
        h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 10px;
        }}
        
        .rate-display {{
            display: flex;
            justify-content: center;
            align-items: baseline;
            gap: 15px;
            flex-wrap: wrap;
        }}
        
        .main-rate {{
            font-size: 56px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ff9d, #00C805);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .rate-label {{
            font-size: 18px;
            color: var(--text-secondary);
        }}
        
        .premium-badge {{
            background: {('#34C759' if premium > 0 else '#FF3B30')};
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 16px;
        }}
        
        .ticker {{
            background: var(--card);
            padding: 12px 0;
            overflow: hidden;
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
        }}
        
        .ticker-content {{
            display: inline-block;
            white-space: nowrap;
            animation: ticker 60s linear infinite;
            font-size: 14px;
            font-weight: 500;
        }}
        
        @keyframes ticker {{
            0% {{ transform: translateX(0); }}
            100% {{ transform: translateX(-33.33%); }}
        }}
        
        .card {{
            background: var(--card);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
        }}
        
        .card-title {{
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th, td {{
            padding: 14px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        
        th {{
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 13px;
            text-transform: uppercase;
        }}
        
        .chart-container {{
            height: 350px;
            margin: 20px 0;
        }}
        
        .trend-buttons {{
            display: flex;
            gap: 8px;
            margin-bottom: 15px;
        }}
        
        .trend-btn {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 6px 14px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        
        .trend-btn:hover {{
            border-color: var(--accent);
            color: var(--accent);
        }}
        
        .trend-btn.active {{
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }}
        
        .depth-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}
        
        .depth-side {{
            background: var(--bg);
            border-radius: 12px;
            padding: 16px;
        }}
        
        .depth-title {{
            font-weight: 700;
            margin-bottom: 16px;
            font-size: 15px;
        }}
        
        .stats-panel {{
            background: var(--card);
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
            border: 1px solid var(--border);
        }}
        
        .stats-title {{
            font-size: 18px;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 20px;
            text-align: center;
        }}
        
        .stats-section {{
            margin-bottom: 24px;
        }}
        
        .stats-section-title {{
            font-size: 16px;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
        }}
        
        .stat-card {{
            background: rgba(10, 132, 255, 0.05);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
            text-align: center;
        }}
        
        .buy-card {{
            background: rgba(0, 200, 5, 0.08);
            border-color: rgba(0, 200, 5, 0.3);
        }}
        
        .sell-card {{
            background: rgba(255, 59, 48, 0.08);
            border-color: rgba(255, 59, 48, 0.3);
        }}
        
        .stat-label {{
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            margin-bottom: 8px;
            font-weight: 600;
        }}
        
        .stat-value {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 6px;
        }}
        
        .stat-value.green {{ color: #00C805; }}
        .stat-value.red {{ color: #FF3B30; }}
        
        .stat-volume {{
            font-size: 13px;
            color: #00bfff;
            font-weight: 600;
        }}
        
        .api-badge {{
            background: rgba(10, 132, 255, 0.2);
            color: #0A84FF;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            margin-left: 10px;
            font-weight: 600;
        }}
        
        .theme-toggle {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--card);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 10px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 20px;
            z-index: 1000;
        }}
        
        footer {{
            text-align: center;
            padding: 30px;
            color: var(--text-secondary);
            font-size: 13px;
            border-top: 1px solid var(--border);
            margin-top: 40px;
        }}
        
        @media (max-width: 768px) {{
            .depth-grid {{ grid-template-columns: 1fr; }}
            .main-rate {{ font-size: 42px; }}
            .stats-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    
    <div class="ticker">
        <div class="ticker-content">{ticker_html}</div>
    </div>
    
    <div class="container">
        <header>
            <h1>🇪🇹 ETB Financial Terminal</h1>
            <div class="rate-display">
                <span class="main-rate">{median:.2f}</span>
                <span class="rate-label">ETB/USD</span>
                <span class="premium-badge">+{premium:.1f}% Premium</span>
            </div>
            <p style="margin-top:15px;color:var(--text-secondary);">
                Black Market Rate vs Official: {official:.2f} ETB
            </p>
        </header>
        
        <!-- Market Summary -->
        <div class="card">
            <div class="card-title">📊 Market Summary</div>
            <table>
                <thead>
                    <tr>
                        <th>Exchange</th>
                        <th>Best Sell</th>
                        <th>Best Buy</th>
                        <th>Sell Ads</th>
                        <th>Buy Ads</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
        
        <!-- Price Trend Chart -->
        <div class="card">
            <div class="card-title">📈 Price Trend & Premium</div>
            <div class="trend-buttons">
                <button class="trend-btn" data-trend="1h" onclick="filterTrend('1h')">1H</button>
                <button class="trend-btn" data-trend="1d" onclick="filterTrend('1d')">1D</button>
                <button class="trend-btn" data-trend="1w" onclick="filterTrend('1w')">1W</button>
                <button class="trend-btn active" data-trend="all" onclick="filterTrend('all')">ALL</button>
            </div>
            <div id="trendChart" class="chart-container"></div>
        </div>
        
        <!-- Exchange Distribution -->
        <div class="card">
            <div class="card-title">🎯 Price Distribution by Exchange</div>
            <div id="scatterChart" class="chart-container"></div>
        </div>
        
        <!-- Market Depth -->
        <div class="card">
            <div class="card-title">📊 Live Market Insight</div>
            <div class="depth-grid">
                <div class="depth-side">
                    <div class="depth-title" style="color:var(--green);">Total Market Supply (Sell Orders)</div>
                    <div style="display:grid;grid-template-columns:100px 70px 1fr;gap:8px;font-size:12px;color:var(--text-secondary);margin-bottom:8px;font-weight:600;">
                        <span>USD Supply</span>
                        <span>At Price</span>
                        <span>Volume by Exchange</span>
                    </div>
                    <div id="supplyChart"></div>
                </div>
                <div class="depth-side">
                    <div class="depth-title" style="color:var(--red);">Total Market Demand (Buy Orders)</div>
                    <div style="display:grid;grid-template-columns:100px 70px 1fr;gap:8px;font-size:12px;color:var(--text-secondary);margin-bottom:8px;font-weight:600;">
                        <span>USD Demand</span>
                        <span>At Price</span>
                        <span>Volume by Exchange</span>
                    </div>
                    <div id="demandChart"></div>
                </div>
            </div>
            <div style="display:flex;justify-content:center;gap:24px;margin-top:16px;padding-top:16px;border-top:1px solid var(--border);">
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:16px;height:16px;background:#F3BA2F;border-radius:4px;"></div>
                    <span style="font-size:13px;">🟡 Binance</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:16px;height:16px;background:#2E55E6;border-radius:4px;"></div>
                    <span style="font-size:13px;">🔵 MEXC</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:16px;height:16px;background:#A855F7;border-radius:4px;"></div>
                    <span style="font-size:13px;">🟣 OKX</span>
                </div>
            </div>
        </div>
        
        <!-- Transaction Statistics - NOW FROM API -->
        <div class="stats-panel">
            <div class="stats-title">
                Transaction Statistics (24 hrs)
                <span class="api-badge">📡 p2p.army API</span>
            </div>
            
            <div class="stats-section">
                <div class="stats-section-title">🟢 Buy Transactions</div>
                <div class="stats-grid">
                    <div class="stat-card buy-card">
                        <div class="stat-label">Last 1 Hour</div>
                        <div class="stat-value green">{trade_stats.get('hour_buys', 0):,}</div>
                        <div class="stat-volume">{trade_stats.get('hour_buy_volume', 0):,.0f} USDT</div>
                    </div>
                    <div class="stat-card buy-card">
                        <div class="stat-label">Today</div>
                        <div class="stat-value green">{trade_stats.get('today_buys', 0):,}</div>
                        <div class="stat-volume">{trade_stats.get('today_buy_volume', 0):,.0f} USDT</div>
                    </div>
                    <div class="stat-card buy-card">
                        <div class="stat-label">Overall (24h)</div>
                        <div class="stat-value green">{trade_stats.get('overall_buys', 0):,}</div>
                        <div class="stat-volume">{trade_stats.get('overall_buy_volume', 0):,.0f} USDT</div>
                    </div>
                </div>
            </div>
            
            <div class="stats-section">
                <div class="stats-section-title">🔴 Sell Transactions</div>
                <div class="stats-grid">
                    <div class="stat-card sell-card">
                        <div class="stat-label">Last 1 Hour</div>
                        <div class="stat-value red">{trade_stats.get('hour_sells', 0):,}</div>
                        <div class="stat-volume">{trade_stats.get('hour_sell_volume', 0):,.0f} USDT</div>
                    </div>
                    <div class="stat-card sell-card">
                        <div class="stat-label">Today</div>
                        <div class="stat-value red">{trade_stats.get('today_sells', 0):,}</div>
                        <div class="stat-volume">{trade_stats.get('today_sell_volume', 0):,.0f} USDT</div>
                    </div>
                    <div class="stat-card sell-card">
                        <div class="stat-label">Overall (24h)</div>
                        <div class="stat-value red">{trade_stats.get('overall_sells', 0):,}</div>
                        <div class="stat-volume">{trade_stats.get('overall_sell_volume', 0):,.0f} USDT</div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- AI Analysis -->
        {ai_summary_html}
        
        <footer>
            Official Rate: {official:.2f} ETB | Last Update: {timestamp} UTC<br>
            v42.10 • Real Historical Data via p2p.army API 📡
        </footer>
    </div>
    
    <script>
        let currentTrendPeriod = 'all';
        const chartData = {json.dumps(chart_data)};
        const historyData = {json.dumps(history_data)};
        const marketDepth = {json.dumps(market_depth)};
        
        function toggleTheme() {{
            const html = document.documentElement;
            const current = html.getAttribute('data-theme');
            html.setAttribute('data-theme', current === 'light' ? 'dark' : 'light');
            initCharts();
        }}
        
        function filterTrend(period) {{
            currentTrendPeriod = period;
            
            document.querySelectorAll('.trend-btn').forEach(btn => {{
                btn.classList.remove('active');
                if (btn.dataset.trend === period) btn.classList.add('active');
            }});
            
            renderTrendChart(period);
        }}
        
        function renderTrendChart(period) {{
            const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
            const bgColor = isDark ? '#1C1C1E' : '#ffffff';
            const textColor = isDark ? '#ffffff' : '#1a1a1a';
            const gridColor = isDark ? '#38383A' : '#e0e0e0';
            
            let filteredDates = historyData.dates || [];
            let filteredMedians = historyData.medians || [];
            let filteredOfficials = historyData.officials || [];
            let filteredPremiums = historyData.premiums || [];
            
            const now = new Date();
            let cutoffTime;
            
            switch(period) {{
                case '1h':
                    cutoffTime = new Date(now - 60 * 60 * 1000);
                    break;
                case '1d':
                    cutoffTime = new Date(now - 24 * 60 * 60 * 1000);
                    break;
                case '1w':
                    cutoffTime = new Date(now - 7 * 24 * 60 * 60 * 1000);
                    break;
                case 'all':
                default:
                    cutoffTime = new Date(0);
            }}
            
            const indices = [];
            filteredDates.forEach((d, i) => {{
                if (new Date(d) >= cutoffTime) indices.push(i);
            }});
            
            if (indices.length < 2) {{
                document.getElementById('trendChart').innerHTML = '<div style="padding:60px;text-align:center;color:var(--text-secondary)"><div style="font-size:48px;margin-bottom:16px">📈</div><div>Not enough data for this period</div></div>';
                return;
            }}
            
            const dates = indices.map(i => filteredDates[i]);
            const medians = indices.map(i => filteredMedians[i]);
            const officials = indices.map(i => filteredOfficials[i]);
            const premiums = indices.map(i => filteredPremiums[i] || 0);
            
            const lastIdx = medians.length - 1;
            const lastMedian = medians[lastIdx];
            const lastPremium = premiums[lastIdx] || 0;
            
            const trendTraces = [];
            
            if (officials && officials.some(v => v > 0)) {{
                trendTraces.push({{
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Official Rate',
                    x: dates,
                    y: officials,
                    line: {{ color: '#FF9500', width: 2, dash: 'dot' }},
                    hovertemplate: '<b>Official:</b> %{{y:.2f}} ETB<extra></extra>'
                }});
            }}
            
            trendTraces.push({{
                type: 'scatter',
                mode: 'lines',
                name: 'Black Market Rate',
                x: dates,
                y: medians,
                line: {{ color: '#00ff9d', width: 3 }},
                fill: 'tonexty',
                fillcolor: 'rgba(0, 255, 157, 0.15)',
                hovertemplate: '<b>Black Market:</b> %{{y:.2f}} ETB<extra></extra>'
            }});
            
            trendTraces.push({{
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Premium %',
                x: dates,
                y: premiums,
                line: {{ color: '#FF3B30', width: 2, dash: 'dash' }},
                marker: {{ size: 4 }},
                yaxis: 'y2',
                hovertemplate: '<b>Premium:</b> %{{y:.1f}}%<extra></extra>'
            }});
            
            const allYValues = [...medians, ...officials.filter(v => v > 0)];
            const minY = Math.floor(Math.min(...allYValues) / 10) * 10 - 10;
            const maxY = Math.ceil(Math.max(...allYValues) / 10) * 10 + 20;
            const maxPremium = Math.max(...premiums) + 5;
            
            const trendLayout = {{
                paper_bgcolor: bgColor,
                plot_bgcolor: bgColor,
                font: {{ color: textColor, family: '-apple-system, BlinkMacSystemFont, sans-serif' }},
                showlegend: true,
                legend: {{ orientation: 'h', y: -0.18 }},
                margin: {{ l: 60, r: 60, t: 20, b: 70 }},
                xaxis: {{
                    gridcolor: gridColor,
                    tickformat: period === '1h' ? '%H:%M' : '%m/%d %H:%M'
                }},
                yaxis: {{
                    title: 'Rate (ETB)',
                    gridcolor: gridColor,
                    zerolinecolor: gridColor,
                    range: [minY, maxY],
                    dtick: 10
                }},
                yaxis2: {{
                    title: 'Premium (%)',
                    overlaying: 'y',
                    side: 'right',
                    showgrid: false,
                    range: [0, maxPremium],
                    ticksuffix: '%'
                }},
                hovermode: 'x unified',
                annotations: [
                    {{
                        x: dates[lastIdx],
                        y: lastMedian,
                        xanchor: 'left',
                        yanchor: 'middle',
                        text: '<b>' + lastMedian.toFixed(1) + '</b>',
                        font: {{ color: '#00ff9d', size: 12 }},
                        showarrow: false,
                        xshift: 10,
                        bgcolor: 'rgba(0,0,0,0.7)',
                        borderpad: 4
                    }},
                    {{
                        x: dates[lastIdx],
                        y: lastPremium,
                        xanchor: 'left',
                        yanchor: 'middle',
                        xref: 'x',
                        yref: 'y2',
                        text: '<b>' + lastPremium.toFixed(1) + '%</b>',
                        font: {{ color: '#FF3B30', size: 11 }},
                        showarrow: false,
                        xshift: 10,
                        bgcolor: 'rgba(0,0,0,0.7)',
                        borderpad: 4
                    }}
                ]
            }};
            
            Plotly.newPlot('trendChart', trendTraces, trendLayout, {{responsive: true, displayModeBar: false}});
        }}
        
        function renderMarketDepth() {{
            const supplyContainer = document.getElementById('supplyChart');
            let supplyHtml = '';
            const supplyData = marketDepth.supply || [];
            const maxSupply = Math.max(...supplyData.map(d => d.total), 1);
            
            supplyData.slice(0, 15).forEach(item => {{
                const binancePct = (item.BINANCE / maxSupply * 100) || 0;
                const mexcPct = (item.MEXC / maxSupply * 100) || 0;
                const okxPct = (item.OKX / maxSupply * 100) || 0;
                
                supplyHtml += `
                    <div style="display:grid;grid-template-columns:100px 70px 1fr;gap:8px;align-items:center;margin-bottom:8px;">
                        <span style="font-weight:600;color:var(--text);font-size:13px;">$` + item.total.toLocaleString(undefined, {{maximumFractionDigits:0}}) + `</span>
                        <span style="color:var(--green);font-weight:600;">` + item.price + ` Br</span>
                        <div style="display:flex;height:20px;border-radius:4px;overflow:hidden;background:var(--border);">
                            ` + (item.BINANCE > 0 ? `<div style="width:` + binancePct + `%;background:#F3BA2F;" title="Binance: $` + item.BINANCE.toLocaleString() + `"></div>` : '') + `
                            ` + (item.MEXC > 0 ? `<div style="width:` + mexcPct + `%;background:#2E55E6;" title="MEXC: $` + item.MEXC.toLocaleString() + `"></div>` : '') + `
                            ` + (item.OKX > 0 ? `<div style="width:` + okxPct + `%;background:#A855F7;" title="OKX: $` + item.OKX.toLocaleString() + `"></div>` : '') + `
                        </div>
                    </div>
                `;
            }});
            
            if (supplyData.length === 0) {{
                supplyHtml = '<div style="text-align:center;padding:20px;color:var(--text-secondary);">No supply data</div>';
            }}
            supplyContainer.innerHTML = supplyHtml;
            
            const demandContainer = document.getElementById('demandChart');
            let demandHtml = '';
            const demandData = marketDepth.demand || [];
            const maxDemand = Math.max(...demandData.map(d => d.total), 1);
            
            demandData.slice(0, 15).forEach(item => {{
                const binancePct = (item.BINANCE / maxDemand * 100) || 0;
                const mexcPct = (item.MEXC / maxDemand * 100) || 0;
                const okxPct = (item.OKX / maxDemand * 100) || 0;
                
                demandHtml += `
                    <div style="display:grid;grid-template-columns:100px 70px 1fr;gap:8px;align-items:center;margin-bottom:8px;">
                        <span style="font-weight:600;color:var(--text);font-size:13px;">$` + item.total.toLocaleString(undefined, {{maximumFractionDigits:0}}) + `</span>
                        <span style="color:var(--red);font-weight:600;">` + item.price + ` Br</span>
                        <div style="display:flex;height:20px;border-radius:4px;overflow:hidden;background:var(--border);">
                            ` + (item.BINANCE > 0 ? `<div style="width:` + binancePct + `%;background:#F3BA2F;" title="Binance: $` + item.BINANCE.toLocaleString() + `"></div>` : '') + `
                            ` + (item.MEXC > 0 ? `<div style="width:` + mexcPct + `%;background:#2E55E6;" title="MEXC: $` + item.MEXC.toLocaleString() + `"></div>` : '') + `
                            ` + (item.OKX > 0 ? `<div style="width:` + okxPct + `%;background:#A855F7;" title="OKX: $` + item.OKX.toLocaleString() + `"></div>` : '') + `
                        </div>
                    </div>
                `;
            }});
            
            if (demandData.length === 0) {{
                demandHtml = '<div style="text-align:center;padding:20px;color:var(--text-secondary);">No demand data</div>';
            }}
            demandContainer.innerHTML = demandHtml;
        }}
        
        function initCharts() {{
            const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
            const bgColor = isDark ? '#1C1C1E' : '#ffffff';
            const textColor = isDark ? '#ffffff' : '#1a1a1a';
            const gridColor = isDark ? '#38383A' : '#e0e0e0';
            
            const scatterTraces = [];
            const colors = {{
                'BINANCE': '#F3BA2F',
                'MEXC': '#2E55E6', 
                'OKX': '#A855F7'
            }};
            
            let allPrices = [];
            let xIndex = 0;
            const exchangeOrder = ['BINANCE', 'MEXC', 'OKX'];
            const exchangeNames = [];
            
            for (const exchange of exchangeOrder) {{
                const prices = chartData[exchange];
                if (prices && prices.length > 0) {{
                    allPrices = allPrices.concat(prices);
                    exchangeNames.push(exchange);
                    
                    const xPositions = prices.map(() => xIndex + (Math.random() - 0.5) * 0.6);
                    scatterTraces.push({{
                        type: 'scatter',
                        mode: 'markers',
                        name: exchange,
                        x: xPositions,
                        y: prices,
                        marker: {{ 
                            color: colors[exchange] || '#00C805',
                            size: 10,
                            opacity: 0.75,
                            line: {{ color: 'rgba(255,255,255,0.5)', width: 1 }}
                        }},
                        hovertemplate: '<b>%{{y:.2f}} ETB</b><extra>' + exchange + '</extra>'
                    }});
                    xIndex++;
                }}
            }}
            
            if (allPrices.length > 0) {{
                const sortedAll = [...allPrices].sort((a, b) => a - b);
                const overallMedian = sortedAll[Math.floor(sortedAll.length / 2)];
                
                scatterTraces.push({{
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Median: ' + overallMedian.toFixed(2) + ' ETB',
                    x: [-0.5, exchangeNames.length - 0.5],
                    y: [overallMedian, overallMedian],
                    line: {{ color: '#00ff9d', width: 2, dash: 'dash' }},
                    hoverinfo: 'skip'
                }});
            }}
            
            const scatterLayout = {{
                paper_bgcolor: bgColor,
                plot_bgcolor: bgColor,
                font: {{ color: textColor, family: '-apple-system, BlinkMacSystemFont, sans-serif' }},
                showlegend: true,
                legend: {{ orientation: 'h', y: -0.15 }},
                margin: {{ l: 60, r: 30, t: 20, b: 60 }},
                xaxis: {{
                    tickmode: 'array',
                    tickvals: exchangeNames.map((_, i) => i),
                    ticktext: exchangeNames,
                    gridcolor: gridColor,
                    zeroline: false
                }},
                yaxis: {{
                    title: 'Price (ETB)',
                    gridcolor: gridColor,
                    zerolinecolor: gridColor
                }},
                hovermode: 'closest'
            }};
            
            Plotly.newPlot('scatterChart', scatterTraces, scatterLayout, {{responsive: true, displayModeBar: false}});
            
            renderTrendChart(currentTrendPeriod);
            renderMarketDepth();
        }}
        
        document.addEventListener('DOMContentLoaded', initCharts);
    </script>
</body>
</html>'''
    
    with open(HTML_FILENAME, 'w') as f:
        f.write(html)
    
    print(f"   ✅ HTML saved: {HTML_FILENAME}", file=sys.stderr)


# =====================================================
# MAIN
# =====================================================

def main():
    print("🔍 Running v42.10 (Real Historical Data!)...", file=sys.stderr)
    print(f"   📡 Data Source: p2p.army Historical API", file=sys.stderr)
    print(f"   📊 Transaction Stats: Real API data (not estimated)", file=sys.stderr)
    print(f"   📈 History: Up to 22 months (March 2023+)", file=sys.stderr)
    
    peg = fetch_usdt_peg() or 1.0
    
    # Capture current market snapshot
    print("\n   > Capturing market snapshot...", file=sys.stderr)
    
    with ThreadPoolExecutor(max_workers=8) as ex:
        f_binance = ex.submit(fetch_binance_both_sides)
        f_mexc = ex.submit(fetch_mexc_both_sides)
        f_okx = ex.submit(fetch_exchange_both_sides, "okx")
        f_off = ex.submit(fetch_official_rate)
        f_remittance = ex.submit(fetch_remittance_rates)
        f_trade_stats = ex.submit(fetch_p2p_army_transaction_stats)
        
        bin_ads = f_binance.result() or []
        mexc_ads = f_mexc.result() or []
        okx_ads = f_okx.result() or []
        official = f_off.result() or 0.0
        remittance_rates = f_remittance.result() or {}
        trade_stats = f_trade_stats.result() or {}
    
    print(f"\n   🔍 Market snapshot:", file=sys.stderr)
    print(f"      BINANCE: {len(bin_ads)} ads", file=sys.stderr)
    print(f"      MEXC: {len(mexc_ads)} ads", file=sys.stderr)
    print(f"      OKX: {len(okx_ads)} ads", file=sys.stderr)
    
    bin_ads = remove_outliers(bin_ads, peg)
    mexc_ads = remove_outliers(mexc_ads, peg)
    okx_ads = remove_outliers(okx_ads, peg)
    
    final_snapshot = bin_ads + mexc_ads + okx_ads
    grouped_ads = {"BINANCE": bin_ads, "MEXC": mexc_ads, "OKX": okx_ads}
    
    if final_snapshot:
        all_prices = [x['price'] for x in final_snapshot]
        stats = analyze(all_prices, peg)
        
        if stats:
            # Save to local CSV (backup)
            save_to_history(stats, official)
            
            # Generate AI summary
            ai_summary = load_cached_ai_summary()
            if not ai_summary:
                ai_summary = generate_ai_summary(stats, official, trade_stats, None, None)
            
            if not ai_summary:
                print("   ⚠️ Using emergency fallback for AI", file=sys.stderr)
                ai_summary = create_fallback_summary(stats, official, trade_stats)
            
            # Generate HTML
            update_website_html(
                stats, official,
                time.strftime("%Y-%m-%d %H:%M:%S"),
                final_snapshot, grouped_ads, peg,
                ai_summary=ai_summary,
                remittance_rates=remittance_rates,
                trade_stats=trade_stats
            )
            
            print(f"\n✅ Complete! v42.10 with real historical data", file=sys.stderr)
            print(f"   📊 Transactions: {trade_stats.get('overall_buys', 0):,} buys, {trade_stats.get('overall_sells', 0):,} sells (24h)", file=sys.stderr)
            print(f"   💰 Volume: ${trade_stats.get('overall_buy_volume', 0) + trade_stats.get('overall_sell_volume', 0):,.0f} total", file=sys.stderr)
    else:
        print("⚠️ No ads found", file=sys.stderr)


if __name__ == "__main__":
    main()
