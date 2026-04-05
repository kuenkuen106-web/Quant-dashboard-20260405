# =============================================================================
# ⚙️ V1 PRO QUANT DUAL-STRATEGY (The Ultimate Edition)
# 核心功能：波段與短線雙引擎 / 雙市場監控 / Discord 實時推送 / 自動戰績覆盤系統
# =============================================================================

import pandas as pd, numpy as np, yfinance as yf, matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt, matplotlib.dates as mdates, concurrent.futures
import warnings, os, datetime, json, logging, webbrowser, time
import requests

# 關閉不必要嘅警告，保持 Terminal 乾淨
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')
plt.style.use('dark_background')
plt.ioff()

# =============================================================================
# 系統環境設定 (路徑與 Webhook)
# =============================================================================
OUTPUT_DIR = "docs" # GitHub Pages 預設讀取嘅資料夾
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# 讀取 GitHub Secrets (保護私隱，避免 URL 外洩)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_SUMMARY_WEBHOOK = os.environ.get("DISCORD_SUMMARY_WEBHOOK", "")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "trade_history.json")

# =============================================================================
# 功能函數區 (Helper Functions)
# =============================================================================
def send_discord_alert(ticker, strategy_name, price, sl, tp, is_bullish):
    """【實時警報】將觸發嘅買賣訊號，以精美卡片形式推送到 Discord 手機 App"""
    if not DISCORD_WEBHOOK_URL or "你的專屬碼" in DISCORD_WEBHOOK_URL: return
    color = 65280 if is_bullish else 16711680 # 綠色代表做多，紅色代表做空
    embed_data = {
        "title": f"🚨 系統異動觸發: {ticker}",
        "description": f"**{strategy_name}** 條件已達成！",
        "color": color,
        "fields": [
            {"name": "💵 當前現價", "value": f"${price}", "inline": True},
            {"name": "🛑 嚴格止損", "value": f"${sl}", "inline": True},
            {"name": "🎯 目標止盈", "value": f"${tp}", "inline": True}
        ],
        "footer": {"text": "V1 Quant Master 實時監控系統"}
    }
    try: requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed_data]})
    except Exception as e: print(f"⚠️ Discord 連線錯誤: {e}")

def load_history():
    """【記憶讀取】開機時讀取過去嘅交易紀錄，用嚟做今日嘅勝負結算"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

trade_history = load_history()

# =============================================================================
# 核心策略參數 (Hyperparameters)
# =============================================================================
LOOKBACK_YEARS = 3       # 索取過去 3 年數據計 200天線
PQR_SWING_MIN = 75       # 波段策略要求相對強度 (RS) 必須高於市場 75% 的股票

# =============================================================================
# MODULE 1 & 2 — 雙市場數據引擎 (Data Fetching)
# =============================================================================
print("⏳ [1-3/7] 正在抓取美日雙市場數據 (V1 雙策略引擎)...")

_US_STOCKS = ['AAPL','MSFT','NVDA','GOOGL','AMZN','META','TSLA','AVGO','LLY','JPM','V','MA','UNH','XOM','PG','COST','CRM','ADBE','NFLX','AMD']
_JP_STOCKS = ['7203.T','8306.T','8058.T','9984.T','6861.T','9432.T','8031.T','6758.T','8001.T','8316.T','7974.T','4063.T','6920.T','8002.T']
ALL_TICKERS = list(dict.fromkeys(_US_STOCKS + _JP_STOCKS + ['SPY', '^VIX', '^N225']))

# 批量下載並處理缺失值 (Forward Fill)
data_raw = yf.download(ALL_TICKERS, period=f"{LOOKBACK_YEARS}y", progress=False)
closes = data_raw['Close'].ffill(); highs = data_raw['High'].ffill(); lows = data_raw['Low'].ffill(); vols = data_raw['Volume'].ffill(); opens = data_raw['Open'].ffill()

# 確立大盤基準 (用作牛熊過濾器)
vix_c = closes['^VIX'].ffill()
spy_c = closes['SPY'].ffill(); spy_200 = spy_c.rolling(200).mean()
n225_c = closes['^N225'].ffill(); n225_200 = n225_c.rolling(200).mean()

# 計算基礎指標：過去一年的相對強度排名
rs_rank = (closes / closes.shift(252) - 1).rank(axis=1, pct=True) * 99 + 1

# =============================================================================
# MODULE 3 — 戰績自動結算系統 (Auto-Replay & Settlement)
# =============================================================================
current_prices = closes.iloc[-1].to_dict() # 擷取今日最新收市價
closed_this_run = []                       # 紀錄今日中咗止盈/止損嘅單
today_str = datetime.datetime.now().strftime('%Y-%m-%d')

for trade in trade_history:
    if trade['status'] == 'OPEN':
        tk = trade['tk']
        if tk in current_prices and not pd.isna(current_prices[tk]):
            now_px = round(current_prices[tk], 2)
            trade['last_px'] = now_px
            
            # 結算邏輯：升穿目標價 (Take Profit) 或 跌穿止損價 (Stop Loss)
            if now_px >= trade['tp']:
                trade['status'] = '✅ TAKE PROFIT'
                trade['close_date'] = today_str
                closed_this_run.append(trade)
            elif now_px <= trade['sl']:
                trade['status'] = '❌ STOP LOSS'
                trade['close_date'] = today_str
                closed_this_run.append(trade)

# =============================================================================
# MODULE 4 & 5 — 雙策略判定引擎 (Core Logic)
# =============================================================================
print("⏳ [4-6/7] 正在分開演算：波段 VCP 策略 vs 短線游擊策略...")

swing_results = []
short_term_results = []

for ticker in [t for t in ALL_TICKERS if t not in ['SPY','^VIX','^N225']]:
    try:
        c = closes[ticker]; h = highs[ticker]; l = lows[ticker]; v = vols[ticker]; op = opens[ticker]
        is_jp = ticker.endswith('.T')
        
        # 計算技術指標
        sma20 = c.rolling(20).mean(); sma50 = c.rolling(50).mean(); sma200 = c.rolling(200).mean()
        atr = (h-l).rolling(14).mean(); cp = float(c.iloc[-1]); catr = float(atr.iloc[-1])
        rs = rs_rank[ticker].iloc[-1]
        
        # 保力加通道與 RSI 計算
        std20 = c.rolling(20).std(); bb_lower = sma20 - (2 * std20); bb_width = (4 * std20) / sma20
        delta = c.diff(); gain = (delta.where(delta > 0, 0)).rolling(14).mean(); loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        # 大盤牛熊過濾 (日股睇 N225，美股睇 SPY)
        bench_200 = n225_200.iloc[-1] if is_jp else spy_200.iloc[-1]
        bench_c = n225_c.iloc[-1] if is_jp else spy_c.iloc[-1]
        is_bull = bench_c > bench_200

        # ---------------------------------------------------------------------
        # 策略 A: 波段 VCP 邏輯 (預期持有 1-4 週)
        # ---------------------------------------------------------------------
        base_dd = (c.rolling(60).max() - c.rolling(60).min()) / c.rolling(60).max() # 基地深度
        rec_volat = (c.rolling(10).max() - c.rolling(10).min()) / c.rolling(10).max() # 波動收縮
        
        is_vcp = (base_dd <= 0.35) and (rec_volat <= 0.06) and (v.iloc[-1] < v.rolling(50).mean().iloc[-1])
        is_bb_sqz = (bb_width.iloc[-1] <= bb_width.rolling(120).min().iloc[-1] * 1.1)

        if is_bull and rs >= PQR_SWING_MIN and (is_vcp or is_bb_sqz):
            tag_name = "🏆 VCP 突破" if is_vcp else "💥 BB 擠壓"
            sl_p = round(cp - 2.5 * catr, 2)
            tp_p = round(cp + 4.5 * catr, 2)
            
            swing_results.append({'tk': ticker, 'pqr': round(rs, 0), 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'tag': tag_name, 'type': 'SWING'})
            
            # 【修復】加入波段策略嘅 Discord 推送
            send_discord_alert(ticker, tag_name, round(cp, 2), sl_p, tp_p, True)
            
            # 寫入歷史庫 (防止重複寫入)
            if not any(t['tk'] == ticker and t['status'] == 'OPEN' for t in trade_history):
                trade_history.append({'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SWING'})

        # ---------------------------------------------------------------------
        # 策略 B: 短線游擊邏輯 (預期持有 1-3 日)
        # ---------------------------------------------------------------------
        gap_pct = (op.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
        is_gap_up = (gap_pct >= 0.03) and (v.iloc[-1] > v.rolling(20).mean().iloc[-1] * 2) # 缺口動能
        is_oversold = (rsi.iloc[-1] < 28) and (cp < bb_lower.iloc[-1])                     # 極度超賣

        if is_gap_up or is_oversold:
            strategy_tag = "⚡ 缺口動能" if is_gap_up else "📉 極度超賣"
            sl_price = round(cp * 0.95, 2) # 短線止損 5%
            tp_price = round(cp * 1.05, 2) # 短線止盈 5%
            
            short_term_results.append({'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'tag': strategy_tag, 'type': 'SHORT'})
            send_discord_alert(ticker, strategy_tag, round(cp, 2), sl_price, tp_price, True)

            # 寫入歷史庫
            if not any(t['tk'] == ticker and t['status'] == 'OPEN' for t in trade_history):
                trade_history.append({'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SHORT'})
    except: pass

# =============================================================================
# MODULE 6 — 總結算與數據持久化 (Stats & JSON Dump)
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
                        <span class="text-[10px] font-bold px-2 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded">{d['tag']}</span>
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
