
# =============================================================================
# ⚙️ V5.0 PRO QUANT DUAL-STRATEGY (VCP Swing + Short-term Tactical)
# 核心功能：波段與短線獨立演算、雙市場監控、整合式 HTML 介面
# =============================================================================

import pandas as pd, numpy as np, yfinance as yf, matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt, matplotlib.dates as mdates, concurrent.futures
import warnings, os, datetime, json, logging, webbrowser, time
import requests
import json

# discord link
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def send_discord_alert(ticker, strategy_name, price, sl, tp, is_bullish):
    """
    發送精美嘅 Discord 提示卡片
    """
    if not DISCORD_WEBHOOK_URL or "你的專屬碼" in DISCORD_WEBHOOK_URL:
        return # 如果未設定 URL 就跳過，避免報錯

    # 設定卡片顏色：好消息用綠色(00ff00)，壞消息/做空用紅色(ff0000)
    color = 65280 if is_bullish else 16711680 

    # 組合 Discord Embed 卡片內容
    embed_data = {
        "title": f"🚨 系統異動觸發: {ticker}",
        "description": f"**{strategy_name}** 條件已達成！",
        "color": color,
        "fields": [
            {"name": "💵 當前現價", "value": f"${price}", "inline": True},
            {"name": "🛑 嚴格止損", "value": f"${sl}", "inline": True},
            {"name": "🎯 目標止盈", "value": f"${tp}", "inline": True}
        ],
        "footer": {"text": "V5.0 Quant Master 實時監控系統"}
    }

    payload = {"embeds": [embed_data]}

    try:
        # 發送 POST 請求到 Discord
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code != 204:
            print(f"⚠️ Discord 提示發送失敗: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Discord 連線錯誤: {e}")

logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')
plt.style.use('dark_background')
plt.ioff()

OUTPUT_DIR = "docs"
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# 核心參數
LOOKBACK_YEARS = 3
VIX_PANIC_THRESHOLD = 25
PQR_SWING_MIN = 75   # 波段策略要求較高 PQR

# =============================================================================
# MODULE 1 & 2 — 數據引擎
# =============================================================================
print("⏳ [1-3/7] 正在抓取美日雙市場數據 (V5.0 雙策略引擎)...")

_US_STOCKS = ['AAPL','MSFT','NVDA','GOOGL','AMZN','META','TSLA','AVGO','LLY','JPM','V','MA','UNH','XOM','PG','COST','CRM','ADBE','NFLX','AMD']
_JP_STOCKS = ['7203.T','8306.T','8058.T','9984.T','6861.T','9432.T','8031.T','6758.T','8001.T','8316.T','7974.T','4063.T','6920.T','8002.T']

ALL_TICKERS = list(dict.fromkeys(_US_STOCKS + _JP_STOCKS + ['SPY', '^VIX', '^N225']))

data_raw = yf.download(ALL_TICKERS, period=f"{LOOKBACK_YEARS}y", progress=False)
closes = data_raw['Close'].ffill(); highs = data_raw['High'].ffill(); lows = data_raw['Low'].ffill(); vols = data_raw['Volume'].ffill(); opens = data_raw['Open'].ffill()

# 大盤參考
vix_c = closes['^VIX'].ffill()
spy_c = closes['SPY'].ffill(); spy_200 = spy_c.rolling(200).mean()
n225_c = closes['^N225'].ffill(); n225_200 = n225_c.rolling(200).mean()

# RS Rank (波段策略核心)
rs_rank = (closes / closes.shift(252) - 1).rank(axis=1, pct=True) * 99 + 1

# =============================================================================
# MODULE 5 — 雙策略判定邏輯
# =============================================================================
print("⏳ [4-6/7] 正在分開演算：波段 VCP 策略 vs 短線游擊策略...")

swing_results = []
short_term_results = []

for ticker in [t for t in ALL_TICKERS if t not in ['SPY','^VIX','^N225']]:
    try:
        c = closes[ticker]; h = highs[ticker]; l = lows[ticker]; v = vols[ticker]; op = opens[ticker]
        is_jp = ticker.endswith('.T')
        sma20 = c.rolling(20).mean(); sma50 = c.rolling(50).mean(); sma200 = c.rolling(200).mean()
        atr = (h-l).rolling(14).mean(); cp = float(c.iloc[-1]); catr = float(atr.iloc[-1])
        
        # 指標計算
        rs = rs_rank[ticker].iloc[-1]
        std20 = c.rolling(20).std(); bb_lower = sma20 - (2 * std20); bb_width = (4 * std20) / sma20
        delta = c.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        # 大盤判定
        bench_200 = n225_200.iloc[-1] if is_jp else spy_200.iloc[-1]
        bench_c = n225_c.iloc[-1] if is_jp else spy_c.iloc[-1]
        is_bull = bench_c > bench_200

        # --- 策略 A: 波段 VCP 邏輯 (持有 1-4 週) ---
        base_dd = (c.rolling(60).max() - c.rolling(60).min()) / c.rolling(60).max()
        rec_volat = (c.rolling(10).max() - c.rolling(10).min()) / c.rolling(10).max()
        is_vcp = (base_dd <= 0.35) and (rec_volat <= 0.06) and (v.iloc[-1] < v.rolling(50).mean().iloc[-1])
        is_bb_sqz = (bb_width.iloc[-1] <= bb_width.rolling(120).min().iloc[-1] * 1.1)

        if is_bull and rs >= PQR_SWING_MIN and (is_vcp or is_bb_sqz):
            swing_results.append({
                'tk': ticker, 'pqr': round(rs, 0), 'px': round(cp, 2),
                'sl': round(cp - 2.5 * catr, 2), 'tp': round(cp + 4.5 * catr, 2),
                'tag': "🏆 VCP 突破" if is_vcp else "💥 BB 擠壓", 'type': 'SWING'
            })

        # --- 策略 B: 短線游擊邏輯 (持有 1-3 日) ---
        # 1. 缺口動能 (Gap and Go)
        gap_pct = (op.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
        is_gap_up = (gap_pct >= 0.03) and (v.iloc[-1] > v.rolling(20).mean().iloc[-1] * 2)
        
        # 2. 超跌反彈 (Mean Reversion)
        is_oversold = (rsi.iloc[-1] < 28) and (cp < bb_lower.iloc[-1])

        if is_gap_up or is_oversold:
            strategy_tag = "⚡ 缺口動能" if is_gap_up else "📉 極度超賣"
            sl_price = round(cp * 0.95, 2)
            tp_price = round(cp * 1.05, 2)
            
            short_term_results.append({
                'tk': ticker, 'px': round(cp, 2),
                'sl': sl_price, 'tp': tp_price, 
                'tag': strategy_tag, 'type': 'SHORT'
            })
            
            # 【新增】自動發送 Discord 提示！
            # 只有當日觸發嘅短線訊號，先會推送到手機
            send_discord_alert(
                ticker=ticker, 
                strategy_name=strategy_tag, 
                price=round(cp, 2), 
                sl=sl_price, 
                tp=tp_price, 
                is_bullish=True
            )
    except: pass

# =============================================================================
# MODULE 7 — 整合式 Dashboard 生成
# =============================================================================
print("⏳ [7/7] 正在生成雙策略整合儀表板...")

html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8"><script src="https://cdn.tailwindcss.com"></script>
    <title>V5.0 DUAL STRATEGY HUB</title>
</head>
<body class="bg-[#020617] text-slate-300 p-8">
    <header class="mb-10 text-center">
        <h1 class="text-5xl font-black text-white italic tracking-tighter">QUANT HUB <span class="text-indigo-500">V5.0</span></h1>
        <p class="text-slate-500 mt-2 font-bold uppercase tracking-widest text-xs">波段趨勢 (Swing) x 短線游擊 (Tactical) 雙系統</p>
    </header>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-12 max-w-7xl mx-auto">
        
        <div class="space-y-6">
            <h2 class="text-2xl font-black text-indigo-400 border-b-2 border-indigo-500/30 pb-2 flex items-center gap-2">
                🏆 波段長抱 (1-4 週)
                <span class="text-[10px] bg-indigo-500/20 px-2 py-1 rounded text-indigo-300 font-normal">Minervini SEPA 邏輯</span>
            </h2>
            <div class="grid grid-cols-1 gap-4">
                {"".join([f'''
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-indigo-500/50 transition shadow-lg">
                    <div class="flex justify-between items-center mb-3">
                        <span class="text-2xl font-black text-white">{d['tk']}</span>
                        <span class="text-[10px] font-bold px-2 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded">{d['tag']}</span>
                    </div>
                    <div class="flex justify-between text-xs mb-4 text-slate-400">
                        <span>PQR: {d['pqr']}</span>
                        <span>止損: <b class="text-red-400">${d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-400">${d['tp']}</b></span>
                    </div>
                    <div class="text-center font-black text-xl text-white bg-black/40 py-2 rounded-xl border border-slate-800">${d['px']}</div>
                </div>
                ''' for d in swing_results]) if swing_results else '<p class="text-slate-600">目前無波段訊號</p>'}
            </div>
        </div>

        <div class="space-y-6">
            <h2 class="text-2xl font-black text-amber-400 border-b-2 border-amber-500/30 pb-2 flex items-center gap-2">
                ⚡ 短線游擊 (1-3 日)
                <span class="text-[10px] bg-amber-500/20 px-2 py-1 rounded text-amber-300 font-normal">高勝率事件驅動</span>
            </h2>
            <div class="grid grid-cols-1 gap-4">
                {"".join([f'''
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-amber-500/50 transition shadow-lg">
                    <div class="flex justify-between items-center mb-3">
                        <span class="text-2xl font-black text-white">{d['tk']}</span>
                        <span class="text-[10px] font-bold px-2 py-1 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded">{d['tag']}</span>
                    </div>
                    <div class="flex justify-between text-xs mb-4 text-slate-400">
                        <span>持倉: 1-3 天</span>
                        <span>止損: <b class="text-red-400">${d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-400">${d['tp']}</b></span>
                    </div>
                    <div class="text-center font-black text-xl text-white bg-black/40 py-2 rounded-xl border border-slate-800">${d['px']}</div>
                </div>
                ''' for d in short_term_results]) if short_term_results else '<p class="text-slate-600">目前無短線訊號</p>'}
            </div>
        </div>

    </div>

    <footer class="mt-20 text-center text-slate-600 text-[10px] uppercase tracking-widest">
        Quant System V5.0 | 數據源：Yahoo Finance | 僅供學術研究使用
    </footer>
</body>
</html>"""

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f: f.write(html)
print(f"\n🎉 V5.0 雙策略儀表板建置完成！")
#webbrowser.open('file://' + os.path.abspath(os.path.join(OUTPUT_DIR, "index.html")))