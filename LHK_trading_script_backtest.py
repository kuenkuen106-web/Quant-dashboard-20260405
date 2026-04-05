# backtest=============================================================================
# ⚙️ V1 PRO QUANT DUAL-STRATEGY (UAT 時光機模式)
# 核心功能：模擬過去交易日 / 雙引擎演算 / 來源追蹤 / 自動結算
# =============================================================================

import pandas as pd, numpy as np, yfinance as yf, matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt, matplotlib.dates as mdates, concurrent.futures
import warnings, os, datetime, json, logging, webbrowser, time
import requests

# 關閉不必要嘅警告
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')
plt.style.use('dark_background')
plt.ioff()

# =============================================================================
# 系統環境設定
# =============================================================================
OUTPUT_DIR = "docs/backtest" 
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_BACKTEST_WEBHOOK_URL", "")
DISCORD_SUMMARY_WEBHOOK = os.environ.get("DISCORD_BACKTEST_SUMMARY_WEBHOOK", "")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "uat_trade_history.json")

# =============================================================================
# 功能函數區
# =============================================================================
def send_discord_alert(ticker, strategy_name, price, sl, tp, is_bullish, sources):
    """【實時警報】加入 UAT 標記與來源顯示"""
    if not DISCORD_WEBHOOK_URL or "你的專屬碼" in DISCORD_WEBHOOK_URL: return
    
    source_str = " | ".join(sources) if sources else "動態掃描"
    color = 65280 if is_bullish else 16711680 
    
    embed_data = {
        "title": f"🚨 [UAT 模擬] 系統異動觸發: {ticker}",
        "description": f"**{strategy_name}** 條件已達成！\n🔍 來源: `{source_str}`",
        "color": color,
        "fields": [
            {"name": "💵 模擬當時價格", "value": f"${price}", "inline": True},
            {"name": "🛑 建議止損", "value": f"${sl}", "inline": True},
            {"name": "🎯 建議止盈", "value": f"${tp}", "inline": True}
        ],
        "footer": {"text": f"時光機模式執行中 | 模擬日期: {today_str}"}
    }
    try: requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed_data]})
    except Exception as e: print(f"⚠️ Discord 連線錯誤: {e}")

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

trade_history = load_history()

# =============================================================================
# 核心策略參數 (Hyperparameters)
# =============================================================================
LOOKBACK_YEARS = 3
PQR_SWING_MIN = 75 
SIMULATE_DAYS_AGO = 10  # 🌟 【時光機設定】設定你想返去幾多個交易日前 (0 = 真實今日)

# =============================================================================
# MODULE 1 & 2 — 數據引擎與時光機截斷
# =============================================================================
print(f"⏳ [1-3/7] 正在構建股票池與抓取歷史數據...")

def build_dynamic_watchlist():
    ticker_sources = {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    def add_to_map(tickers, source_label):
        for t in tickers:
            if not isinstance(t, str): continue
            if t not in ticker_sources: ticker_sources[t] = []
            if source_label not in ticker_sources[t]: ticker_sources[t].append(source_label)

    # 1. S&P 500
    try:
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp500_table = pd.read_html(sp500_url)[0]
        sp500_tickers = sp500_table['Symbol'].str.replace('.', '-').tolist()
        add_to_map(sp500_tickers, "S&P500")
    except: print("⚠️ S&P 500 載入失敗")

    # 2. Finviz 異動
    finviz_configs = [
        ("https://finviz.com/screener.ashx?v=111&s=ta_topgainers", "Finviz升幅"),
        ("https://finviz.com/screener.ashx?v=111&s=ta_unusualvolume", "Finviz異動")
    ]
    for url, label in finviz_configs:
        try:
            response = requests.get(url, headers=headers)
            found_tickers = pd.read_html(response.text)[-2][1].tolist()
            found_tickers = [t for t in found_tickers if isinstance(t, str) and t.isupper() and len(t) <= 5]
            add_to_map(found_tickers, label)
        except: pass

    # 3. 日股名單
    try:
        n225_url = 'https://en.wikipedia.org/wiki/Nikkei_225'
        n225_table = pd.read_html(n225_url, match='Company')[0]
        n225_tickers = (n225_table.iloc[:, 1].astype(str) + '.T').tolist()
        add_to_map(n225_tickers, "NK225")
        
        jp_trending_url = "https://query1.finance.yahoo.com/v1/finance/trending/JP?count=20"
        res_jp = requests.get(jp_trending_url, headers=headers)
        if res_jp.status_code == 200:
            jp_trending = [q['symbol'] for q in res_jp.json()['finance']['result'][0]['quotes']]
            add_to_map(jp_trending, "JP熱門")
    except: print("⚠️ 日股載入失敗")

    add_to_map(['SPY', '^VIX', '^N225'], "基準指數")
    return ticker_sources

TICKER_MAP = build_dynamic_watchlist()
ALL_TICKERS = list(TICKER_MAP.keys())

# 下載數據
data_raw = yf.download(ALL_TICKERS, period=f"{LOOKBACK_YEARS}y", progress=False, threads=True, timeout=30, group_by='column')
closes = data_raw['Close'].ffill(); highs = data_raw['High'].ffill(); lows = data_raw['Low'].ffill(); vols = data_raw['Volume'].ffill(); opens = data_raw['Open'].ffill()

# ---------------------------------------------------------------------
# 🕒 【時光機關鍵邏輯】抹除「未來」數據
# ---------------------------------------------------------------------
if SIMULATE_DAYS_AGO > 0:
    print(f"⏰ [時光機] 正在抹除最近 {SIMULATE_DAYS_AGO} 天數據，回溯中...")
    closes = closes.iloc[:-SIMULATE_DAYS_AGO]
    highs = highs.iloc[:-SIMULATE_DAYS_AGO]
    lows = lows.iloc[:-SIMULATE_DAYS_AGO]
    vols = vols.iloc[:-SIMULATE_DAYS_AGO]
    opens = opens.iloc[:-SIMULATE_DAYS_AGO]
# ---------------------------------------------------------------------

# 基於模擬日期計算指標
today_str = closes.index[-1].strftime('%Y-%m-%d')
print(f"📅 [UAT] 模擬今日日期：{today_str}")

vix_c = closes['^VIX'].ffill()
spy_c = closes['SPY'].ffill(); spy_200 = spy_c.rolling(200).mean()
n225_c = closes['^N225'].ffill(); n225_200 = n225_c.rolling(200).mean()
rs_rank = (closes / closes.shift(252) - 1).rank(axis=1, pct=True) * 99 + 1

# =============================================================================
# MODULE 3 — 戰績自動結算系統
# =============================================================================
current_prices = closes.iloc[-1].to_dict() 
closed_this_run = []

for trade in trade_history:
    if trade['status'] == 'OPEN':
        tk = trade['tk']
        if tk in current_prices and not pd.isna(current_prices[tk]):
            now_px = round(float(current_prices[tk]), 2)
            trade['last_px'] = now_px
            if now_px >= trade['tp']:
                trade['status'] = '✅ TAKE PROFIT'
                trade['close_date'] = today_str
                closed_this_run.append(trade)
            elif now_px <= trade['sl']:
                trade['status'] = '❌ STOP LOSS'
                trade['close_date'] = today_str
                closed_this_run.append(trade)

# =============================================================================
# MODULE 4 & 5 — 雙策略判定引擎
# =============================================================================
print(f"⏳ [4-6/7] 正在按 {today_str} 視角進行策略演算...")

swing_results = []
short_term_results = []

for ticker in [t for t in ALL_TICKERS if t not in ['SPY','^VIX','^N225']]:
    try:
        c = closes[ticker]; h = highs[ticker]; l = lows[ticker]; v = vols[ticker]; op = opens[ticker]
        if len(c.dropna()) < 200: continue
        
        avg_dollar_vol = (c.tail(20) * v.tail(20)).mean()
        min_liq = 300_000_000 if ticker.endswith('.T') else 5_000_000
        if avg_dollar_vol < min_liq: continue
        
        is_jp = ticker.endswith('.T')
        sma20 = c.rolling(20).mean(); sma50 = c.rolling(50).mean(); sma200 = c.rolling(200).mean()
        atr = (h-l).rolling(14).mean(); cp = float(c.iloc[-1]); catr = float(atr.iloc[-1])
        rs = rs_rank[ticker].iloc[-1]
        
        std20 = c.rolling(20).std(); bb_lower = sma20 - (2 * std20); bb_width = (4 * std20) / sma20
        delta = c.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        bench_200 = n225_200.iloc[-1] if is_jp else spy_200.iloc[-1]
        bench_c = n225_c.iloc[-1] if is_jp else spy_c.iloc[-1]
        is_bull = bench_c > bench_200

        sources = TICKER_MAP.get(ticker, ["動態掃描"])

        # 策略 A: Swing
        base_dd = (c.rolling(60).max() - c.rolling(60).min()) / c.rolling(60).max()
        rec_volat = (c.rolling(10).max() - c.rolling(10).min()) / c.rolling(10).max()
        is_vcp = (base_dd <= 0.35) and (rec_volat <= 0.06) and (v.iloc[-1] < v.rolling(50).mean().iloc[-1])
        is_bb_sqz = (bb_width.iloc[-1] <= bb_width.rolling(120).min().iloc[-1] * 1.1)

        if is_bull and rs >= PQR_SWING_MIN and (is_vcp or is_bb_sqz):
            tag_name = "🏆 VCP 突破" if is_vcp else "💥 BB 擠壓"
            sl_p = round(cp - 2.5 * catr, 2); tp_p = round(cp + 4.5 * catr, 2)
            swing_results.append({'tk': ticker, 'pqr': round(rs, 0), 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'tag': tag_name, 'type': 'SWING', 'sources': sources})
            send_discord_alert(ticker, tag_name, round(cp, 2), sl_p, tp_p, True, sources)
            if not any(t['tk'] == ticker and t['status'] == 'OPEN' for t in trade_history):
                trade_history.append({'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SWING'})

        # 策略 B: Short
        gap_pct = (op.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
        is_gap_up = (gap_pct >= 0.03) and (v.iloc[-1] > v.rolling(20).mean().iloc[-1] * 2)
        is_oversold = (rsi.iloc[-1] < 28) and (cp < bb_lower.iloc[-1])

        if is_gap_up or is_oversold:
            strategy_tag = "⚡ 缺口動能" if is_gap_up else "📉 極度超賣"
            sl_price = round(cp * 0.95, 2); tp_price = round(cp * 1.05, 2)
            short_term_results.append({'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'tag': strategy_tag, 'type': 'SHORT', 'sources': sources})
            send_discord_alert(ticker, strategy_tag, round(cp, 2), sl_price, tp_price, True, sources)
            if not any(t['tk'] == ticker and t['status'] == 'OPEN' for t in trade_history):
                trade_history.append({'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SHORT'})
    except: pass

# =============================================================================
# MODULE 6 — 存檔
# =============================================================================
def calculate_stats(history):
    closed = [t for t in history if '✅' in t['status'] or '❌' in t['status']]
    if not closed: return 0, 0, 0
    wins = [t for t in closed if '✅' in t['status']]
    return len(closed), len(wins), round(len(wins)/len(closed)*100, 1)

total_closed, wins, win_rate = calculate_stats(trade_history)

# 如果今日有單結案，發送戰績結算卡片到 Discord
if DISCORD_SUMMARY_WEBHOOK and closed_this_run:
    payload = {
        "embeds": [{
            "title": "📊 系統戰績結算摘要", "color": 10181046,
            "fields": [
                {"name": "總結案筆數", "value": f"{total_closed}", "inline": True},
                {"name": "獲利筆數", "value": f"{wins}", "inline": True},
                {"name": "歷史勝率", "value": f"**{win_rate}%**", "inline": True}
            ],
            "footer": {"text": f"今日新增結案: {len(closed_this_run)} 筆"}
        }]
    }
    try: requests.post(DISCORD_SUMMARY_WEBHOOK, json=payload)
    except: pass

# 確保 JSON 檔案只保留最近 100 筆，避免網頁載入過慢
# 這能確保 JSON 檔案體積精簡，加快 GitHub Pages 的加載速度，同時保留足夠的樣本計算勝率。
with open(HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(trade_history[-100:], f, indent=4)

# =============================================================================
# MODULE 7 — 整合式 Dashboard 生成 (HTML + JavaScript)
# =============================================================================
print("⏳ [7/7] 正在生成雙策略整合儀表板...")

html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8"><script src="https://cdn.tailwindcss.com"></script>
    <title>V1 QUANT MASTER</title>
</head>
<body class="bg-[#020617] text-slate-300 p-8 font-sans">
    <header class="mb-10 text-center">
        <h1 class="text-5xl font-black text-white italic tracking-tighter">QUANT HUB <span class="text-indigo-500">V1</span></h1>
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
                        <div class="flex flex-wrap justify-end gap-1">
                            {" ".join([f'<span class="text-[8px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">{s}</span>' for s in d['sources']])}
                        </div>
                    </div>
                    <div class="flex justify-between text-xs mb-4 text-slate-400">
                        <span>PQR: {d['pqr']}</span>
                        <span>止損: <b class="text-red-400">${d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-400">${d['tp']}</b></span>
                    </div>
                    <div class="text-center font-black text-xl text-white bg-black/40 py-2 rounded-xl border border-slate-800">${d['px']}</div>
                </div>
                ''' for d in swing_results]) if swing_results else '<p class="text-slate-600 italic">目前無波段訊號</p>'}
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
                ''' for d in short_term_results]) if short_term_results else '<p class="text-slate-600 italic">目前無短線訊號</p>'}
            </div>
        </div>
    </div>

    <section class="max-w-7xl mx-auto mt-16">
        <h2 class="text-2xl font-black text-emerald-400 border-b-2 border-emerald-500/30 pb-2 mb-6 flex justify-between items-end">
            <span>📜 歷史追蹤與勝率統計</span>
            <span class="text-sm text-slate-400 font-normal">總結案: {total_closed} 筆 | 勝率: <span class="text-emerald-400 font-bold">{win_rate}%</span></span>
        </h2>
        <div class="overflow-x-auto bg-slate-900 rounded-2xl border border-slate-800 shadow-xl">
            <table class="w-full text-left text-sm">
                <thead class="bg-black/60 text-slate-400 uppercase font-black text-[10px] tracking-wider">
                    <tr>
                        <th class="p-4">建議日期</th>
                        <th class="p-4">代號</th>
                        <th class="p-4">買入價</th>
                        <th class="p-4">結案價 (現價)</th>
                        <th class="p-4">狀態</th>
                    </tr>
                </thead>
                <tbody id="history-table-body">
                    </tbody>
            </table>
        </div>
    </section>

    <footer class="mt-20 pb-10 text-center text-slate-600 text-[10px] uppercase tracking-widest">
        Quant System V1 | 自動結算與推送 | 僅供學術研究使用
    </footer>

    <script>
    // 自動讀取 trade_history.json 並渲染表格
    fetch('trade_history.json')
      .then(response => response.json())
      .then(data => {{
        const tbody = document.getElementById('history-table-body');
        if(data.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="5" class="p-6 text-center text-slate-500">尚無歷史交易紀錄</td></tr>';
            return;
        }}
        // 將資料反轉，顯示最新 15 筆紀錄
        data.reverse().slice(0, 15).forEach(t => {{ 
          const isWin = t.status.includes('✅');
          const isLoss = t.status.includes('❌');
          const statusColor = isWin ? 'text-emerald-400 bg-emerald-500/10' : (isLoss ? 'text-red-400 bg-red-500/10' : 'text-slate-300 bg-slate-700/50');
          
          const row = `
            <tr class="border-t border-slate-800 hover:bg-slate-800/50 transition">
              <td class="p-4 text-slate-400 text-xs">${{t.date}}</td>
              <td class="p-4 font-black text-white flex items-center gap-2">
                ${{t.tk}} <span class="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-500">${{t.type}}</span>
              </td>
              <td class="p-4 text-slate-300">$${{t.px}}</td>
              <td class="p-4 font-bold ${{isWin ? 'text-emerald-400' : (isLoss ? 'text-red-400' : 'text-white')}}">$${{t.last_px}}</td>
              <td class="p-4">
                <span class="px-2 py-1 rounded text-xs font-bold ${{statusColor}}">${{t.status}}</span>
              </td>
            </tr>`;
          tbody.innerHTML += row;
        }});
      }})
      .catch(e => console.log('尚未建立歷史檔案:', e));
    </script>
</body>
</html>"""

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f: f.write(html)
print(f"\n🎉 V1 戰績自動結算版建置完成！")
