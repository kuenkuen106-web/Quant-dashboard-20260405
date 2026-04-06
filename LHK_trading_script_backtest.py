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
OUTPUT_DIR = "docs/UAT" 
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
    if not DISCORD_WEBHOOK_URL: 
        print(f"⚠️ 未設定 Webhook URL，跳過發送 {ticker}") # 加呢行等你知道係咪讀唔到 URL
        return
    
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
    try: 
        res = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed_data]})
        if res.status_code == 429:
            print(f"⚠️ Discord 拒絕接收 (429 Rate Limit) - 傳送太快！")
        
        # 👇 核心：強制定程式停 0.5 秒，防止被 Discord Ban
        time.sleep(0.5) 
        
    except Exception as e: 
        print(f"⚠️ Discord 連線錯誤: {e}")

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
LOOKBACK_YEARS = 5
PQR_SWING_MIN = 10
raw_days = os.environ.get("UAT_DAYS_AGO", "10")
SIMULATE_DAYS_AGO = int(raw_days)

# =============================================================================
# MODULE 1 & 2 — 數據引擎與時光機截斷
# =============================================================================
print(f"⏳ [1-3/7] 正在構建股票池與抓取歷史數據...")

def build_dynamic_watchlist():
    print("⏳ [1/7] 正在構建全球動態股票池...")
    ticker_sources = {} # 修正：這裡必須是字典 {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    def add_to_map(tickers, source_label):
        for t in tickers:
            if not isinstance(t, str) or len(t) < 1: continue
            
            # 【修正】只針對沒有 .T 的美股處理點號
            clean_t = t.strip()
            if not clean_t.endswith('.T'):
                clean_t = clean_t.replace('.', '-')
                
            if clean_t not in ticker_sources:
                ticker_sources[clean_t] = []
            if source_label not in ticker_sources[clean_t]:
                ticker_sources[clean_t].append(source_label)
    # ---------------------------------------------------------
    # 1. 獲取標普 500 全名單 ((穩定版：DataHub CSV)) - 用作全面回測基礎
    # ---------------------------------------------------------
    try:
        csv_url = "https://raw.githubusercontent.com/datasets/s-p-500-companies/master/data/constituents.csv"
        df_sp = pd.read_csv(csv_url, timeout=10)
        add_to_map(df_sp['Symbol'].tolist(), "S&P500")
        print(f"  ✅ 成功從 DataHub 載入 S&P 500")
    except Exception as e:
        print(f"  ⚠️ S&P 500 載入失敗，嘗試 Fallback 機制")
        # 如果 fail，可以手動加入2026/04/05 list
        sp500_full_list = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "BRK-B", "TSLA", "UNH",
        "JPM", "XOM", "V", "MA", "AVGO", "PG", "HD", "JNJ", "LLY", "COST",
        "CVX", "MRK", "ABBV", "PEP", "KO", "TMO", "PFE", "BAC", "ORCL", "MCD",
        "CSCO", "CRM", "ABT", "ACN", "LIN", "NFLX", "AMD", "DIS", "WMT", "TXN",
        "DHR", "PM", "NKE", "NEE", "VZ", "RTX", "UPS", "HON", "QCOM", "AMGN",
        "LOW", "SPGI", "IBM", "INTU", "CAT", "UNP", "COP", "SBUX", "DE", "GS",
        "PLD", "MS", "BLK", "ELV", "GILD", "ISRG", "TJX", "LMT", "SYK", "ADP",
        "MDT", "VRTX", "MMC", "AMT", "GE", "CI", "CB", "NOW", "ADI", "LRCX",
        "MDLZ", "T", "ETN", "REGN", "ZTS", "BSX", "MU", "PANW", "PGR", "FI",
        "SNPS", "C", "KLAC", "VLO", "CDNS", "WM", "EOG", "SHW", "MAR", "MCK",
        "CVS", "MO", "PH", "GD", "ORLY", "APH", "SLB", "ITW", "USB", "FDX",
        "ECL", "ROP", "PXD", "TGT", "BDX", "NXPI", "CMG", "MNST", "MPC", "MCO",
        "CTAS", "AIG", "NSC", "PSX", "ADSK", "AON", "EMR", "MET", "D", "KMB",
        "SRE", "MSI", "MCHP", "AJG", "HCA", "AZO", "F", "WELL", "EW", "DRE",
        "O", "PCAR", "GPN", "ADP", "FIS", "HUM", "PAYX", "TEL", "DOW", "BKR",
        "ADM", "KDP", "STZ", "CNC", "JCI", "SYY", "CTSH", "CARR", "DXCM", "EIX",
        "IDXX", "VRSK", "DLR", "IQV", "A", "GWW", "COR", "ED", "NEM", "CHTR",
        "YUM", "OXY", "MSCI", "KHC", "WFC", "TFC", "PNC", "COF", "DFS", "SYF",
        "KEY", "RF", "HBAN", "FITB", "CFG", "STT", "NTRS", "MTB", "BK", "AMP",
        "IVZ", "BEN", "TROW", "GL", "L", "AIZ", "RE", "TRV", "CBRE", "HST",
        "SPG", "AVB", "EQR", "VTR", "PEAK", "BXP", "MAA", "CPT", "UDR", "ESS",
        "ARE", "VICI", "PSA", "EXR", "SBAC", "CCI", "AWK", "NI", "PNW", "ATO",
        "LNT", "ES", "WEC", "CMS", "XEL", "ETR", "FE", "AEE", "AEP", "PEG",
        "DTE", "PPL", "DUK", "SO", "CNP", "VST", "PARA", "WBD", "NWSA", "NWS",
        "FOXA", "FOX", "LYV", "MTCH", "GOOG", "GOOGL", "NFLX", "DIS", "EA",
        "TTWO", "OMC", "IPG", "CHTR", "VZ", "T", "TMUS", "LUMN", "FYBR", "AMX",
        "TSLA", "AMZN", "HD", "LOW", "MCD", "SBUX", "NKE", "TGT", "TJX", "ORLY",
        "AZO", "ROST", "MAR", "HLT", "YUM", "CMG", "DHI", "LEN", "PHM", "NVR",
        "GRMN", "F", "GM", "BBY", "EBAY", "ETSY", "RVTY", "POOL", "HAS", "MAT",
        "WMT", "COST", "PG", "KO", "PEP", "PM", "MO", "EL", "CL", "KMB",
        "MDLZ", "K", "GIS", "CPB", "HRL", "SJM", "ADM", "STZ", "TAP", "MNST",
        "SYY", "KR", "WBA", "TGT", "DLTR", "DG", "XOM", "CVX", "COP", "SLB",
        "HAL", "BKR", "MPC", "PSX", "VLO", "EOG", "PXD", "OXY", "HES", "DVN",
        "FANG", "MRO", "APA", "CTRA", "OKE", "TRGP", "KMI", "WMB", "JPM", "BAC",
        "WFC", "C", "MS", "GS", "BLK", "AMP", "TROW", "BEN", "IVZ", "STT",
        "NTRS", "BK", "SCHW", "RJF", "LPLA", "AXP", "V", "MA", "DFS", "COF",
        "SYF", "PYPL", "GPN", "FIS", "FISV", "JKHY", "AON", "MMC", "AJG", "WTW",
        "MET", "PRU", "AFL", "TRV", "CB", "PGR", "ALL", "HIG", "L", "CINF",
        "RE", "AIZ", "GL", "SPGI", "MCO", "MSCI", "NDAQ", "CME", "ICE", "BLK",
        "UNH", "ELV", "CI", "HUM", "CNC", "CVS", "JNJ", "LLY", "ABBV", "MRK",
        "PFE", "GILD", "VRTX", "REGN", "AMGN", "BMY", "ZTS", "IDXX", "EW", "BSX",
        "MDT", "ABT", "SYK", "BDX", "ISRG", "DXCM", "STE", "TMO", "DHR", "A",
        "WAT", "MTD", "IQV", "CRL", "RMD", "BA", "LMT", "RTX", "GD", "NOC",
        "TDG", "HWM", "TXT", "GE", "HON", "MMM", "EMR", "ITW", "ETN", "PH",
        "AME", "ROK", "DOV", "XYL", "GWW", "FAST", "CTAS", "ADP", "PAYX", "RSG",
        "WM", "UNP", "NSC", "CSX", "FDX", "UPS", "CPT", "INVH", "AMH", "SBAC",
        "CCI", "AMT", "PLD", "PSA", "EXR", "VICI", "DLR", "EQIX", "NVDA", "AVGO",
        "AMD", "INTC", "QCOM", "TXN", "ADI", "MU", "AMAT", "LRCX", "KLAC", "SNPS",
        "CDNS", "ADSK", "ANSS", "ORCL", "CRM", "SAP", "NOW", "PANW", "FTNT", "IBM",
        "ACN", "CTSH", "TEL", "APH", "MSI", "STX", "WDC", "HPQ", "DELL", "NTAP"
        # 但將本 List 作為 "If fail then use this" 的 Fallback。
        ]
        # 執行合併
        add_to_map(sp500_full_list, "S&P500")

    # ---------------------------------------------------------
    # 2. 獲取 Finviz 異動股 (Unusual Volume & Top Gainers)
    # ---------------------------------------------------------
    # 呢度係捕捉「當日最熱門」標的關鍵
    finviz_urls = [
        ("https://finviz.com/screener.ashx?v=111&s=ta_topgainers", "Finviz升幅"),
        ("https://finviz.com/screener.ashx?v=111&s=ta_unusualvolume", "Finviz異動")
    ]
    for url, label in finviz_urls:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            tables = pd.read_html(res.text)
            # Finviz 的股票代號通常在最後幾個表格中，且長度為 1-5 字符
            for df in tables[-3:]: 
                if 1 in df.columns:
                    found = [str(t) for t in df[1].tolist() if str(t).isupper() and 1 <= len(str(t)) <= 5]
                    if found:
                        add_to_map(found, label)
                        print(f"  🔥 捕捉到 {label}: {len(found)} 隻")
                        break
        except:
            print(f"  ⚠️ {label} 抓取略過")

    # ---------------------------------------------------------
    # 3. 獲取日股動態名單 (Nikkei 225 + 當日熱門)
    # ---------------------------------------------------------
    try:
        n225_url = 'https://en.wikipedia.org/wiki/Nikkei_225'
        res = requests.get(n225_url, headers=headers, timeout=10)
        all_tables = pd.read_html(res.text)
        n225_table = max(all_tables, key=len) # 取行數最多的表格
        
        import re
        found_nk = []
        target_col = None
        
        # 優先方法：搵明確嘅標題 (Wikipedia 通常叫 'Code' 或 'Ticker')
        for col in n225_table.columns:
            col_name = str(col).lower()
            if 'code' in col_name or 'ticker' in col_name or 'symbol' in col_name:
                target_col = col
                break
                
        # 後備方法：如果標題改咗名，用「數值特徵」去估
        if target_col is None:
            for col in n225_table.columns:
                # 攞頭 5 個有效數值測試
                sample_vals = n225_table[col].dropna().astype(str).tolist()[:5]
                # 如果全部都係 4 位數...
                if sample_vals and all(re.match(r'^\d{4}$', str(x)) for x in sample_vals):
                    # 並且有數字大於 3000 (證明肯定唔係年份)
                    if any(int(x) > 3000 for x in sample_vals if str(x).isdigit()):
                        target_col = col
                        break

        # 如果成功定位到正確欄位，就開始提取
        if target_col is not None:
            found_nk = [f"{str(x)}.T" for x in n225_table[target_col] if re.match(r'^\d{4}$', str(x))]
            found_nk = list(dict.fromkeys(found_nk)) # 去重
            
        if len(found_nk) > 0:
            add_to_map(found_nk, "NK225")
            print(f"  ✅ 成功從 Wikipedia 精確載入 NK225 (共 {len(found_nk)} 隻)")
        else:
            raise ValueError("找不到股票代號欄位 (可能被誤認為年份)")
    except Exception as e:
        print(f"  ⚠️ 日股名單載入失敗: {e}")
        # 如果 fail, 手動加入2026/04/05 list
        nk225_tickers = [
        "1332.T", "1605.T", "1721.T", "1801.T", "1802.T", "1803.T", "1812.T", "1925.T", "1928.T", "1963.T",
        "2002.T", "2267.T", "2282.T", "2413.T", "2432.T", "2501.T", "2502.T", "2503.T", "2531.T", "2768.T",
        "2801.T", "2802.T", "2871.T", "2914.T", "3086.T", "3099.T", "3101.T", "3103.T", "3289.T", "3382.T",
        "3401.T", "3402.T", "3405.T", "3407.T", "3436.T", "3659.T", "3861.T", "3863.T", "4004.T", "4005.T",
        "4021.T", "4042.T", "4043.T", "4061.T", "4063.T", "4151.T", "4183.T", "4188.T", "4208.T", "4324.T",
        "4452.T", "4502.T", "4503.T", "4506.T", "4507.T", "4519.T", "4523.T", "4543.T", "4568.T", "4578.T",
        "4661.T", "4689.T", "4704.T", "4751.T", "4755.T", "4901.T", "4911.T", "5019.T", "5020.T", "5101.T",
        "5108.T", "5201.T", "5202.T", "5214.T", "5232.T", "5233.T", "5301.T", "5332.T", "5333.T", "5401.T",
        "5406.T", "5411.T", "5541.T", "5631.T", "5703.T", "5706.T", "5707.T", "5711.T", "5713.T", "5801.T",
        "5802.T", "5803.T", "5901.T", "6098.T", "6103.T", "6113.T", "6178.T", "6301.T", "6302.T", "6305.T",
        "6326.T", "6361.T", "6367.T", "6471.T", "6472.T", "6473.T", "6501.T", "6503.T", "6504.T", "6506.T",
        "6645.T", "6674.T", "6701.T", "6702.T", "6703.T", "6723.T", "6724.T", "6752.T", "6753.T", "6758.T",
        "6762.T", "6770.T", "6841.T", "6857.T", "6902.T", "6920.T", "6952.T", "6954.T", "6971.T", "6976.T",
        "6981.T", "6988.T", "7011.T", "7012.T", "7013.T", "7186.T", "7201.T", "7202.T", "7203.T", "7205.T",
        "7211.T", "7261.T", "7267.T", "7269.T", "7270.T", "7272.T", "7731.T", "7733.T", "7735.T", "7741.T",
        "7751.T", "7752.T", "7832.T", "7911.T", "7912.T", "7951.T", "8001.T", "8002.T", "8015.T", "8031.T",
        "8035.T", "8053.T", "8058.T", "8233.T", "8252.T", "8253.T", "8267.T", "8304.T", "8306.T", "8308.T",
        "8309.T", "8316.T", "8331.T", "8354.T", "8411.T", "8601.T", "8604.T", "8628.T", "8630.T", "8697.T",
        "8725.T", "8750.T", "8766.T", "8795.T", "8801.T", "8802.T", "8804.T", "8830.T", "9001.T", "9005.T",
        "9007.T", "9008.T", "9009.T", "9020.T", "9021.T", "9022.T", "9041.T", "9042.T", "9062.T", "9064.T",
        "9101.T", "9104.T", "9107.T", "9201.T", "9202.T", "9301.T", "9412.T", "9432.T", "9433.T", "9434.T",
        "9501.T", "9502.T", "9503.T", "9531.T", "9532.T", "9602.T", "9613.T", "9681.T", "9735.T", "9766.T",
        "9843.T", "9983.T", "9984.T"
        ]
        # 執行合併
        add_to_map(nk225_tickers, "NK225")

    # B. 捕捉 JP Trending (保持不變)
    try:
        jp_trending_url = "https://query1.finance.yahoo.com/v1/finance/trending/JP?count=20"
        res_jp = requests.get(jp_trending_url, headers=headers, timeout=5)
        # 加入 len 檢查，防止 list index out of range
        if res_jp.status_code == 200 and len(res_jp.json().get('finance', {}).get('result', [])) > 0:
            jp_trending = [q['symbol'] for q in res_jp.json()['finance']['result'][0]['quotes']]
            add_to_map(jp_trending, "JP熱門")
            print(f"  🔥 捕捉到日股當日焦點: {len(jp_trending)} 隻")
    except Exception as e:
        print(f"  ⚠️ JP Trending 略過: API 未返回數據")

    add_to_map(['SPY', '^VIX', '^N225'], "基準指數")
    return ticker_sources

TICKER_MAP = build_dynamic_watchlist()
ALL_TICKERS = list(TICKER_MAP.keys())
print(f"此run觀察名單: {ALL_TICKERS}")

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
    if trade.get('status') == 'OPEN':
        tk = trade.get('tk')
        if tk in current_prices and not pd.isna(current_prices[tk]):
            now_px = round(float(current_prices[tk]), 2)
            trade['last_px'] = now_px
            
            # 使用 .get() 提取，防止 KeyError
            tp = trade.get('tp')
            sl = trade.get('sl')
            
            if tp is not None and now_px >= tp:
                trade['status'] = '✅ TAKE PROFIT'
                trade['close_date'] = today_str
                closed_this_run.append(trade)
            elif sl is not None and now_px <= sl:
                trade['status'] = '❌ STOP LOSS'
                trade['close_date'] = today_str
                closed_this_run.append(trade)

# =============================================================================
# MODULE 4 & 5 — 雙策略判定引擎 (優化架構版)
# =============================================================================
print(f"⏳ [4-6/7] 正在按 {today_str} 視角進行策略演算...")

swing_results = []
short_term_results = []
funnel = {"total": 0, "data_nan": 0, "liq_fail": 0, "market_fail": 0, "rs_fail": 0, "vcp_fail": 0, "ok": 0}

for ticker in [t for t in ALL_TICKERS if t not in ['SPY','^VIX','^N225']]:
    funnel["total"] += 1
    try:
        # --- 第一層：數據完整性 ---
        c_raw = closes[ticker].dropna()
        if len(c_raw) < 252 + 200: # 確保足夠計 RS 同 SMA200
            funnel["data_nan"] += 1
            continue
        
        # 定義基礎數據
        c = closes[ticker]; h = highs[ticker]; l = lows[ticker]; v = vols[ticker]; op = opens[ticker]
        cp = float(c.iloc[-1])
        
        # --- 第二層：流動性過濾 ---
        avg_dollar_vol = (c.tail(20) * v.tail(20)).mean()
        min_liq = 300_000_000 if ticker.endswith('.T') else 5_000_000
        if avg_dollar_vol < min_liq:
            funnel["liq_fail"] += 1
            continue
            
        # --- 第三層：大盤趨勢 (is_bull) ---
        is_jp = ticker.endswith('.T')
        bench_c = n225_c.iloc[-1] if is_jp else spy_c.iloc[-1]
        bench_200 = n225_200.iloc[-1] if is_jp else spy_200.iloc[-1]
        is_bull = bench_c > bench_200
        
        if not is_bull:
            funnel["market_fail"] += 1
            # 注意：如果大盤唔好，Swing 可能唔行，但 Short Term (超賣) 可能想行
            # 呢度假設你兩個策略都要大盤好先做，所以 continue
            continue

        # --- 第四層：相對強度 (RS) ---
        rs = rs_rank[ticker].iloc[-1]
        if pd.isna(rs) or rs < PQR_SWING_MIN:
            funnel["rs_fail"] += 1
            continue

        # --- 第五層：計算技術指標 (只針對過咗上面幾關嘅股票) ---
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_lower = sma20 - (2 * std20)
        bb_width = (4 * std20) / sma20
        atr = (h-l).rolling(14).mean(); catr = float(atr.iloc[-1])
        
        # RSI
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        sources = TICKER_MAP.get(ticker, ["動態掃描"])
        triggered = False

        # ---------------------------------------------------------------------
        # 策略 A: Swing (VCP / BB Sqz)
        # ---------------------------------------------------------------------
        base_dd = (c.rolling(60).max() - c.rolling(60).min()) / c.rolling(60).max()
        rec_volat = (c.rolling(10).max() - c.rolling(10).min()) / c.rolling(10).max()
        is_vcp = (base_dd.iloc[-1] <= 0.35) and (rec_volat.iloc[-1] <= 0.06) and (v.iloc[-1] < v.rolling(50).mean().iloc[-1])
        is_bb_sqz = (bb_width.iloc[-1] <= bb_width.rolling(120).min().iloc[-1] * 1.1)

        trade_info = None # 準備一個變數裝要 save 嘅資料

        if is_vcp or is_bb_sqz:
            tag_name = "🏆 VCP 突破" if is_vcp else "💥 BB 擠壓"
            sl_p = round(cp - 2.5 * catr, 2); tp_p = round(cp + 4.5 * catr, 2)
            swing_results.append({'tk': ticker, 'pqr': round(rs, 0), 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'tag': tag_name, 'type': 'SWING', 'sources': sources})
            send_discord_alert(ticker, tag_name, round(cp, 2), sl_p, tp_p, True, sources)
            # 【修正】完整記錄所需資料
            trade_info = {'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SWING'}

        # ---------------------------------------------------------------------
        # 策略 B: Short Term (Gap / Oversold) - 只有當 Swing 冇中嗰陣先行
        # ---------------------------------------------------------------------
        if not trade_info: 
            gap_pct = (op.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
            is_gap_up = (gap_pct >= 0.03) and (v.iloc[-1] > v.rolling(20).mean().iloc[-1] * 2)
            is_oversold = (rsi.iloc[-1] < 28) and (cp < bb_lower.iloc[-1])

            if is_gap_up or is_oversold:
                strategy_tag = "⚡ 缺口動能" if is_gap_up else "📉 極度超賣"
                sl_price = round(cp * 0.95, 2); tp_price = round(cp * 1.05, 2)
                short_term_results.append({'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'tag': strategy_tag, 'type': 'SHORT', 'sources': sources})
                send_discord_alert(ticker, strategy_tag, round(cp, 2), sl_price, tp_price, True, sources)
                # 【修正】完整記錄所需資料
                trade_info = {'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SHORT'}

        # ---------------------------------------------------------------------
        # 寫入歷史庫 (如果有任何一個策略觸發)
        # ---------------------------------------------------------------------
        if trade_info:
            funnel["ok"] += 1
            # 檢查係咪已經有未平倉嘅單
            if not any(t.get('tk') == ticker and t.get('status') == 'OPEN' for t in trade_history):
                 trade_history.append(trade_info)
        else:
            funnel["vcp_fail"] += 1

    except Exception as e:
        funnel["data_nan"] += 1

# 循環完咗之後 Print 報告
print(f"\n📊 --- UAT 策略漏斗報告 ({today_str}) ---")
print(f"總掃描數: {funnel['total']}")
print(f"❌ 數據不足/報錯: {funnel['data_nan']}")
print(f"❌ 成交量不足: {funnel['liq_fail']}")
print(f"❌ 大盤走勢差: {funnel['market_fail']}")
print(f"❌ RS 排名不足: {funnel['rs_fail']}")
print(f"❌ 形態未收縮: {funnel['vcp_fail']}")
print(f"✅ 符合條件: {funnel['ok']}")
print("------------------------------------------\n")

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
    # 建立今日結案明細字串
    detail_lines = []
    for t in closed_this_run:
        icon = "🎯" if "TAKE PROFIT" in t['status'] else "🛑"
        # 計算盈虧金額 (USD 基準)
        shares = 10000 / t['px']
        pnl = shares * (t['last_px'] - t['px'])
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        detail_lines.append(f"{icon} **{t['tk']}**: {t['status']} ({pnl_str})")
    
    details_text = "\n".join(detail_lines)

    payload = {
        "embeds": [{
            "title": "📊 系統戰績結算摘要",
            "description": f"**今日結案清單:**\n{details_text}",
            "color": 10181046,
            "fields": [
                {"name": "總結案筆數", "value": f"{total_closed}", "inline": True},
                {"name": "獲利筆數", "value": f"{wins}", "inline": True},
                {"name": "歷史勝率", "value": f"**{win_rate}%**", "inline": True}
            ],
            "footer": {"text": f"模擬日期: {today_str} | 每單本金 $10,000 USD"}
        }]
    }
    try: requests.post(DISCORD_SUMMARY_WEBHOOK, json=payload)
    except: pass

# 確保 JSON 檔案只保留最近 100 筆，避免網頁載入過慢
# 這能確保 JSON 檔案體積精簡，加快 GitHub Pages 的加載速度，同時保留足夠的樣本計算勝率。
with open(HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(trade_history[-100:], f, indent=4)

# =============================================================================
# MODULE 7 — 整合式 Dashboard 生成 (緊湊版 + 多幣種)
# =============================================================================
print("⏳ [7/7] 正在生成緊湊型雙策略儀表板...")

def get_unit(tk): return "¥" if tk.endswith(".T") else "$"

html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8"><script src="https://cdn.tailwindcss.com"></script>
    <title>V1 QUANT MASTER</title>
</head>
<body class="bg-[#020617] text-slate-300 p-6 font-sans">
    <header class="mb-6 text-center">
        <h1 class="text-4xl font-black text-white italic tracking-tighter">UAT <span class="text-indigo-500">V1</span></h1>
        <p class="text-slate-500 font-bold uppercase tracking-widest text-[10px]">每單固定 $10,000 USD 盈虧計算</p>
    </header>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-7xl mx-auto mb-10">
        <div class="space-y-3">
            <h2 class="text-xl font-black text-indigo-400 border-b border-indigo-500/30 pb-1 flex items-center gap-2">🏆 波段推介</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {"".join([f'''
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 hover:border-indigo-500/50 transition shadow-md">
                    <div class="flex justify-between items-start mb-1">
                        <a href="https://www.tradingview.com/chart/?symbol={'TSE:'+d['tk'].replace('.T','') if d['tk'].endswith('.T') else d['tk']}" target="_blank" class="text-lg font-black text-white hover:text-indigo-400 leading-none">{d['tk']}</a>
                        <span class="text-[8px] px-1 rounded bg-slate-800 text-slate-500 border border-slate-700">{d['sources'][0] if d['sources'] else 'SCAN'}</span>
                    </div>
                    <div class="flex justify-between text-[10px] text-slate-500 mb-2">
                        <span>止損: <b class="text-red-500/80">{get_unit(d['tk'])}{d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-500/80">{get_unit(d['tk'])}{d['tp']}</b></span>
                    </div>
                    <div class="text-center font-bold text-lg text-white bg-white/5 py-1 rounded-lg border border-white/5">{get_unit(d['tk'])}{d['px']}</div>
                </div>
                ''' for d in swing_results]) if swing_results else '<p class="text-slate-600 italic text-xs">無訊號</p>'}
            </div>
        </div>

        <div class="space-y-3">
            <h2 class="text-xl font-black text-amber-400 border-b border-amber-500/30 pb-1 flex items-center gap-2">⚡ 短線推介</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {"".join([f'''
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 hover:border-amber-500/50 transition shadow-md">
                    <div class="flex justify-between items-start mb-1">
                        <a href="https://www.tradingview.com/chart/?symbol={'TSE:'+d['tk'].replace('.T','') if d['tk'].endswith('.T') else d['tk']}" target="_blank" class="text-lg font-black text-white hover:text-amber-400 leading-none">{d['tk']}</a>
                        <span class="text-[9px] font-bold text-amber-500/80">{d['tag']}</span>
                    </div>
                    <div class="flex justify-between text-[10px] text-slate-500 mb-2">
                        <span>止損: <b class="text-red-500/80">{get_unit(d['tk'])}{d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-500/80">{get_unit(d['tk'])}{d['tp']}</b></span>
                    </div>
                    <div class="text-center font-bold text-lg text-white bg-white/5 py-1 rounded-lg border border-white/5">{get_unit(d['tk'])}{d['px']}</div>
                </div>
                ''' for d in short_term_results]) if short_term_results else '<p class="text-slate-600 italic text-xs">無訊號</p>'}
            </div>
        </div>
    </div>

    <section class="max-w-7xl mx-auto mb-8">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="bg-slate-900/50 border border-slate-800 rounded-2xl p-4 shadow-xl">
                <h3 class="text-sm font-black text-blue-400 mb-3 flex items-center gap-2">📊 階段盈虧結算 (USD)</h3>
                <table class="w-full text-xs text-center">
                    <thead class="text-slate-500 uppercase text-[9px] border-b border-slate-800">
                        <tr><th class="pb-2">範圍</th><th class="pb-2">單數</th><th class="pb-2">勝率</th><th class="pb-2 text-right">總利潤</th></tr>
                    </thead>
                    <tbody id="summary-table-body"></tbody>
                </table>
            </div>
            <div class="bg-slate-900/50 border border-slate-800 rounded-2xl p-4 shadow-xl">
                <h3 class="text-sm font-black text-emerald-400 mb-3 flex items-center gap-2">📜 最近結案紀錄</h3>
                <table class="w-full text-xs text-left">
                    <thead class="text-slate-500 uppercase text-[9px] border-b border-slate-800">
                        <tr><th class="pb-2">日期</th><th class="pb-2">代號</th><th class="pb-2">狀態</th><th class="pb-2 text-right">P&L</th></tr>
                    </thead>
                    <tbody id="history-table-body"></tbody>
                </table>
            </div>
        </div>
    </section>

    <script>
    fetch('uat_trade_history.json')
      .then(res => res.json())
      .then(data => {{
        const histBody = document.getElementById('history-table-body');
        const sumBody = document.getElementById('summary-table-body');
        const sorted = [...data].reverse();

        // 歷史表 (顯示最近 8 筆)
        sorted.slice(0, 8).forEach(t => {{
            if (!t.status.includes('OPEN')) {{
                const shares = 10000 / t.px;
                const pnl = shares * (t.last_px - t.px);
                const pnlColor = pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
                histBody.innerHTML += `
                <tr class="border-b border-white/5">
                    <td class="py-2 text-[10px] text-slate-500">${{t.date.slice(5)}}</td>
                    <td class="py-2 font-bold text-white">${{t.tk}}</td>
                    <td class="py-2 text-[9px]">${{t.status.split(' ')[1]}}</td>
                    <td class="py-2 text-right font-mono ${{pnlColor}}">${{pnl >=0 ? '+':''}}${{pnl.toFixed(0)}}</td>
                </tr>`;
            }}
        }});

        // 結算表
        const closed = sorted.filter(t => !t.status.includes('OPEN'));
        [10, 20, 50, 100].forEach(n => {{
            const slice = closed.slice(0, n);
            if(slice.length > 0) {{
                let wins = 0, totalPnl = 0;
                slice.forEach(t => {{
                    if(t.status.includes('✅')) wins++;
                    totalPnl += (10000 / t.px) * (t.last_px - t.px);
                }});
                sumBody.innerHTML += `
                <tr class="border-b border-white/5">
                    <td class="py-2 text-slate-400">最近 ${{n}}</td>
                    <td class="py-2 text-white">${{slice.length}}</td>
                    <td class="py-2 text-indigo-400">${{((wins/slice.length)*100).toFixed(0)}}%</td>
                    <td class="py-2 text-right font-black ${{totalPnl>=0?'text-emerald-400':'text-red-400'}}">${{totalPnl>=0?'+':''}}${{totalPnl.toFixed(0)}}</td>
                </tr>`;
            }}
        }});
      }});
    </script>
</body>
</html>"""

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f: f.write(html)
print(f"\n🎉 V1 戰績自動結算版建置完成！")
