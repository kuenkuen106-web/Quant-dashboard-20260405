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
def send_discord_alert(ticker, strategy_name, price, sl, tp, is_bullish, sources):
    """【實時警報】加入 UAT 標記與來源顯示"""
    if not DISCORD_WEBHOOK_URL: 
        print(f"⚠️ 未設定 Webhook URL，跳過發送 {ticker}") # 加呢行等你知道係咪讀唔到 URL
        return
    
    # 👇 自動判定幣種符號
    unit = "¥" if ticker.endswith(".T") else "$"

    source_str = " | ".join(sources) if sources else "動態掃描"
    color = 65280 if is_bullish else 16711680 
    
    embed_data = {
        "title": f"🚨 系統異動觸發: {ticker}",
        "description": f"**{strategy_name}** 條件已達成！\n🔍 來源: `{source_str}`",
        "color": color,
        "fields": [
            {"name": "💵 當前現價", "value": f"{unit}{price}", "inline": True},
            {"name": "🛑 嚴格止損", "value": f"{unit}{sl}", "inline": True},
            {"name": "🎯 目標止盈", "value": f"{unit}{tp}", "inline": True}
        ],
        "footer": {"text": "V1 Quant Master 實時監控系統"}
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
# 此參數定義了「強者恆強」的門檻。根據 Minervini 統計，大牛股在爆發前，其相對強度排名通常已處於市場前 25%。

# =============================================================================
# MODULE 1 & 2 — 雙市場數據引擎 (Data Fetching)
# =============================================================================
print("⏳ [1-3/7] 正在抓取美日雙市場數據 (V1 雙策略引擎)...")

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

# 將原本的 ALL_TICKERS 替換為調用這個函數
TICKER_MAP = build_dynamic_watchlist()
ALL_TICKERS = list(TICKER_MAP.keys())
print(f"此run觀察名單: {ALL_TICKERS}")

# [Commentary] 加入 threads=True 以加速 800 隻股票的下載
# 加入 timeout=20 防止個別股票卡死導致 GitHub Actions 超時
data_raw = yf.download(ALL_TICKERS, period=f"{LOOKBACK_YEARS}y", progress=False, threads=True, timeout=30, group_by='column')
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

            # 使用 .get() 提取，防止 KeyError
            tp = trade.get('tp')
            sl = trade.get('sl')
            
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
# MODULE 4 & 5 — 雙策略判定引擎 (優化架構版)
# =============================================================================
print(f"⏳ [4-6/7] 正在按 {today_str} 視角進行策略演算...")

swing_results = []
short_term_results = []
funnel = {"total": 0, "data_nan": 0, "liq_fail": 0, "market_fail": 0, "rs_fail": 0, "vcp_fail": 0, "ok": 0}

for ticker in [t for t in ALL_TICKERS if t not in ['SPY','^VIX','^N225']]:
    funnel["total"] += 1
    try:
        c_raw = closes[ticker].dropna()
        if len(c_raw) < 252 + 200: 
            funnel["data_nan"] += 1
            continue
        
        c = closes[ticker]; h = highs[ticker]; l = lows[ticker]; v = vols[ticker]; op = opens[ticker]
        cp = float(c.iloc[-1])
        
        avg_dollar_vol = (c.tail(20) * v.tail(20)).mean()
        min_liq = 300_000_000 if ticker.endswith('.T') else 5_000_000
        if avg_dollar_vol < min_liq:
            funnel["liq_fail"] += 1
            continue
            
        is_jp = ticker.endswith('.T')
        bench_c = n225_c.iloc[-1] if is_jp else spy_c.iloc[-1]
        bench_200 = n225_200.iloc[-1] if is_jp else spy_200.iloc[-1]
        is_bull = bench_c > bench_200
        
        if not is_bull:
            funnel["market_fail"] += 1
            continue

        rs = rs_rank[ticker].iloc[-1]
        if pd.isna(rs) or rs < PQR_SWING_MIN:
            funnel["rs_fail"] += 1
            continue

        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_lower = sma20 - (2 * std20)
        bb_width = (4 * std20) / sma20
        atr = (h-l).rolling(14).mean(); catr = float(atr.iloc[-1])
        
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        
        sources = TICKER_MAP.get(ticker, ["動態掃描"])

        base_dd = (c.rolling(60).max() - c.rolling(60).min()) / c.rolling(60).max()
        rec_volat = (c.rolling(10).max() - c.rolling(10).min()) / c.rolling(10).max()
        is_vcp = (base_dd.iloc[-1] <= 0.35) and (rec_volat.iloc[-1] <= 0.06) and (v.iloc[-1] < v.rolling(50).mean().iloc[-1])
        is_bb_sqz = (bb_width.iloc[-1] <= bb_width.rolling(120).min().iloc[-1] * 1.1)

        trade_info = None 

        # ---------------------------------------------------------------------
        # 策略 A: Swing (VCP / BB Sqz)
        # ---------------------------------------------------------------------
        if is_vcp or is_bb_sqz:
            tag_name = "🏆 VCP 突破" if is_vcp else "💥 BB 擠壓"
            sl_p = round(cp - 2.5 * catr, 2); tp_p = round(cp + 4.5 * catr, 2)
            # 即時獲取板塊資訊
            try: sector = yf.Ticker(ticker).info.get('sector', 'N/A')
            except: sector = 'N/A'
            
            swing_results.append({'tk': ticker, 'pqr': round(rs, 0), 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'tag': tag_name, 'type': 'SWING', 'sector': sector, 'sources': sources})
            send_discord_alert(ticker, tag_name, round(cp, 2), sl_p, tp_p, True, sources)
            # 【重要】將 tag 同 sector 寫入歷史庫，方便日後分組結算
            trade_info = {'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_p, 'tp': tp_p, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SWING', 'tag': tag_name, 'sector': sector}

        # ---------------------------------------------------------------------
        # 策略 B: Short Term (Gap / Oversold)
        # ---------------------------------------------------------------------
        if not trade_info: 
            gap_pct = (op.iloc[-1] - c.iloc[-2]) / c.iloc[-2]
            is_gap_up = (gap_pct >= 0.03) and (v.iloc[-1] > v.rolling(20).mean().iloc[-1] * 2)
            is_oversold = (rsi.iloc[-1] < 28) and (cp < bb_lower.iloc[-1])

            if is_gap_up or is_oversold:
                strategy_tag = "⚡ 缺口動能" if is_gap_up else "📉 極度超賣"
                sl_price = round(cp * 0.95, 2); tp_price = round(cp * 1.05, 2)
                try: sector = yf.Ticker(ticker).info.get('sector', 'N/A')
                except: sector = 'N/A'

                short_term_results.append({'tk': ticker, 'pqr': round(rs, 0), 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'tag': strategy_tag, 'type': 'SHORT', 'sector': sector, 'sources': sources})
                send_discord_alert(ticker, strategy_tag, round(cp, 2), sl_price, tp_price, True, sources)
                trade_info = {'date': today_str, 'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 'last_px': round(cp, 2), 'status': 'OPEN', 'type': 'SHORT', 'tag': strategy_tag, 'sector': sector}

        if trade_info:
            funnel["ok"] += 1
            if not any(t.get('tk') == ticker and t.get('status') == 'OPEN' for t in trade_history):
                 trade_history.append(trade_info)
        else:
            funnel["vcp_fail"] += 1

    except Exception as e:
        funnel["data_nan"] += 1

# 【重點升級】依據 PQR (相對強度) 從強到弱排序，確保最佳標的排在最前
swing_results.sort(key=lambda x: x['pqr'], reverse=True)
short_term_results.sort(key=lambda x: x['pqr'], reverse=True)

print(f"\n📊 --- 策略漏斗報告 ({today_str}) ---")
print(f"總掃描數: {funnel['total']} | ❌ 數據/報錯: {funnel['data_nan']} | ❌ 流動性: {funnel['liq_fail']} | ❌ 大盤: {funnel['market_fail']} | ❌ RS不足: {funnel['rs_fail']} | ❌ 無形態: {funnel['vcp_fail']} | ✅ 觸發: {funnel['ok']}")

# =============================================================================
# MODULE 6 — 總結算與數據持久化 (Stats & JSON Dump)
# =============================================================================
def calculate_stats(history):
    closed = [t for t in history if '✅' in t['status'] or '❌' in t['status']]
    if not closed: return 0, 0, 0
    wins = [t for t in closed if '✅' in t['status']]
    return len(closed), len(wins), round(len(wins)/len(closed)*100, 1)

total_closed, wins, win_rate = calculate_stats(trade_history)

if DISCORD_SUMMARY_WEBHOOK:
    # 1. 今日結案明細
    detail_lines = []
    if closed_this_run:
        for t in closed_this_run:
            icon = "🎯" if "TAKE PROFIT" in t['status'] else "🛑"
            shares = 10000 / t['px']
            pnl = shares * (t['last_px'] - t['px'])
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            detail_lines.append(f"{icon} **{t['tk']}** ({t.get('tag', 'N/A')}): {pnl_str}")
    details_text = "\n".join(detail_lines) if detail_lines else "今日無新結案交易。"

    # 2. 目前持倉浮盈
    open_trades = [t for t in trade_history if t.get('status') == 'OPEN']
    floating_pnl = sum([(10000 / t['px']) * (t['last_px'] - t['px']) for t in open_trades])
    floating_str = f"+${floating_pnl:.2f}" if floating_pnl >= 0 else f"-${abs(floating_pnl):.2f}"
    floating_color = 65280 if floating_pnl >= 0 else 16711680

    # 3. 細分策略 P&L 結算 (歷史總計)
    strategy_stats = {}
    for t in [x for x in trade_history if '✅' in x['status'] or '❌' in x['status']]:
        tag = t.get('tag', '未分類')
        if tag not in strategy_stats: strategy_stats[tag] = {'wins': 0, 'total': 0, 'pnl': 0}
        strategy_stats[tag]['total'] += 1
        if '✅' in t['status']: strategy_stats[tag]['wins'] += 1
        strategy_stats[tag]['pnl'] += (10000 / t['px']) * (t['last_px'] - t['px'])
    
    # 組裝細分報告字串
    breakdown_lines = []
    for tag, st in strategy_stats.items():
        w_rate = round((st['wins'] / st['total']) * 100, 1) if st['total'] > 0 else 0
        pnl_s = f"+${st['pnl']:.0f}" if st['pnl'] >= 0 else f"-${abs(st['pnl']):.0f}"
        breakdown_lines.append(f"**{tag}**: {w_rate}% 勝率 | P&L: {pnl_s} ({st['total']}單)")
    breakdown_text = "\n".join(breakdown_lines) if breakdown_lines else "尚無足夠結案數據。"

    payload = {
        "embeds": [{
            "title": f"📊 系統戰績結算摘要 ({today_str})", 
            "description": f"**今日結案動態:**\n{details_text}\n\n**🔍 各策略歷史表現:**\n{breakdown_text}",
            "color": floating_color,
            "fields": [
                {"name": "📂 目前持倉", "value": f"{len(open_trades)} 隻", "inline": True},
                {"name": "🌊 總浮動盈虧", "value": f"**{floating_str}**", "inline": True},
                {"name": "📈 總勝率", "value": f"{win_rate}% ({wins}/{total_closed})", "inline": False}
            ],
            "footer": {"text": f"每單本金 $10,000 USD"}
        }]
    }
    try: requests.post(DISCORD_SUMMARY_WEBHOOK, json=payload)
    except: pass

with open(HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(trade_history[-150:], f, indent=4)

# =============================================================================
# MODULE 7 — 整合式 Dashboard 生成 (加入持倉與浮盈)
# =============================================================================
print("⏳ [7/7] 正在生成完整型雙策略儀表板...")

def get_unit(tk): return "¥" if tk.endswith(".T") else "$"

html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8"><script src="https://cdn.tailwindcss.com"></script>
    <title>V1 QUANT MASTER</title>
</head>
<body class="bg-[#020617] text-slate-300 p-6 font-sans">
    <header class="mb-6 text-center">
        <h1 class="text-4xl font-black text-white italic tracking-tighter"> 黎克特制 <span class="text-indigo-500">QUANT</span></h1>
        <p class="text-slate-500 font-bold uppercase tracking-widest text-[10px]">每單固定 $10,000 USD 盈虧計算 | 按 RS 強度排序</p>
    </header>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-7xl mx-auto mb-10">
        <div class="space-y-3">
            <h2 class="text-xl font-black text-indigo-400 border-b border-indigo-500/30 pb-1 flex items-center gap-2">🏆 波段推介 (今日)</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {"".join([f'''
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 hover:border-indigo-500/50 transition shadow-md">
                    <div class="flex justify-between items-start mb-1">
                        <a href="https://www.tradingview.com/chart/?symbol={'TSE:'+d['tk'].replace('.T','') if d['tk'].endswith('.T') else d['tk']}" target="_blank" class="text-lg font-black text-white hover:text-indigo-400 leading-none">{d['tk']}</a>
                        <span class="text-[9px] font-bold text-indigo-400 bg-indigo-500/10 px-1.5 py-0.5 rounded border border-indigo-500/20">{d['tag']}</span>
                    </div>
                    <div class="text-[9px] text-slate-500 mb-2 flex items-center gap-2">
                        <span class="bg-slate-800 px-1.5 py-0.5 rounded">{d.get('sector', 'N/A')}</span>
                        <span>RS: <span class="text-white">{d['pqr']}</span></span>
                    </div>
                    <div class="flex justify-between text-[10px] text-slate-400 mb-2">
                        <span>止損: <b class="text-red-500/80">{get_unit(d['tk'])}{d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-500/80">{get_unit(d['tk'])}{d['tp']}</b></span>
                    </div>
                    <div class="text-center font-bold text-lg text-white bg-white/5 py-1 rounded-lg border border-white/5">{get_unit(d['tk'])}{d['px']}</div>
                </div>
                ''' for d in swing_results]) if swing_results else '<p class="text-slate-600 italic text-xs">今日無訊號</p>'}
            </div>
        </div>

        <div class="space-y-3">
            <h2 class="text-xl font-black text-amber-400 border-b border-amber-500/30 pb-1 flex items-center gap-2">⚡ 短線推介 (今日)</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {"".join([f'''
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-3 hover:border-amber-500/50 transition shadow-md">
                    <div class="flex justify-between items-start mb-1">
                        <a href="https://www.tradingview.com/chart/?symbol={'TSE:'+d['tk'].replace('.T','') if d['tk'].endswith('.T') else d['tk']}" target="_blank" class="text-lg font-black text-white hover:text-amber-400 leading-none">{d['tk']}</a>
                        <span class="text-[9px] font-bold text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">{d['tag']}</span>
                    </div>
                    <div class="text-[9px] text-slate-500 mb-2 flex items-center gap-2">
                        <span class="bg-slate-800 px-1.5 py-0.5 rounded">{d.get('sector', 'N/A')}</span>
                        <span>RS: <span class="text-white">{d['pqr']}</span></span>
                    </div>
                    <div class="flex justify-between text-[10px] text-slate-400 mb-2">
                        <span>止損: <b class="text-red-500/80">{get_unit(d['tk'])}{d['sl']}</b></span>
                        <span>目標: <b class="text-emerald-500/80">{get_unit(d['tk'])}{d['tp']}</b></span>
                    </div>
                    <div class="text-center font-bold text-lg text-white bg-white/5 py-1 rounded-lg border border-white/5">{get_unit(d['tk'])}{d['px']}</div>
                </div>
                ''' for d in short_term_results]) if short_term_results else '<p class="text-slate-600 italic text-xs">今日無訊號</p>'}
            </div>
        </div>
    </div>

    <section class="max-w-7xl mx-auto mb-10">
        <h2 class="text-xl font-black text-cyan-400 border-b border-cyan-500/30 pb-1 mb-4 flex justify-between items-end">
            <span>📂 目前持倉 (Open Positions)</span>
            <span id="total-floating-header" class="text-sm">總浮盈: 載入中...</span>
        </h2>
        <div class="overflow-x-auto bg-slate-900/80 rounded-2xl border border-slate-800 shadow-xl">
            <table class="w-full text-sm text-left">
                <thead class="text-slate-500 uppercase text-[10px] border-b border-slate-800 bg-black/40">
                    <tr><th class="p-3">日期</th><th class="p-3">代號</th><th class="p-3">標籤</th><th class="p-3">買入</th><th class="p-3">現價</th><th class="p-3">進度</th><th class="p-3 text-right">P&L (USD)</th></tr>
                </thead>
                <tbody id="open-table-body"></tbody>
            </table>
        </div>
    </section>

    <section class="max-w-7xl mx-auto mb-8">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="bg-slate-900/50 border border-slate-800 rounded-2xl p-4 shadow-xl">
                <h3 class="text-sm font-black text-fuchsia-400 mb-3 flex items-center gap-2">🎯 各策略獨立表現 (USD)</h3>
                <table class="w-full text-xs text-center">
                    <thead class="text-slate-500 uppercase text-[9px] border-b border-slate-800">
                        <tr><th class="pb-2 text-left">策略標籤</th><th class="pb-2">單數</th><th class="pb-2">勝率</th><th class="pb-2 text-right">總利潤</th></tr>
                    </thead>
                    <tbody id="strategy-table-body"></tbody>
                </table>
            </div>
            
            <div class="bg-slate-900/50 border border-slate-800 rounded-2xl p-4 shadow-xl">
                <h3 class="text-sm font-black text-blue-400 mb-3 flex items-center gap-2">📊 歷史階段盈虧總計 (USD)</h3>
                <table class="w-full text-xs text-center">
                    <thead class="text-slate-500 uppercase text-[9px] border-b border-slate-800">
                        <tr><th class="pb-2 text-left">範圍</th><th class="pb-2">單數</th><th class="pb-2">勝率</th><th class="pb-2 text-right">總利潤</th></tr>
                    </thead>
                    <tbody id="summary-table-body"></tbody>
                </table>
            </div>
        </div>
    </section>

    <script>
    fetch('{os.path.basename(HISTORY_FILE)}')
      .then(res => res.json())
      .then(data => {{
        const openBody = document.getElementById('open-table-body');
        const sumBody = document.getElementById('summary-table-body');
        const stratBody = document.getElementById('strategy-table-body');
        const totalFloatingHeader = document.getElementById('total-floating-header');
        
        const sorted = [...data].reverse();

        // 1. 處理「目前持倉」表格
        const openTrades = sorted.filter(t => t.status === 'OPEN');
        let totalFloating = 0;
        
        if (openTrades.length === 0) {{
            openBody.innerHTML = '<tr><td colspan="7" class="p-6 text-center text-slate-500">目前空倉</td></tr>';
            totalFloatingHeader.innerHTML = '總浮盈: <span class="text-slate-500">$0.00</span>';
        }} else {{
            openTrades.forEach(t => {{
                const shares = 10000 / t.px;
                const pnl = shares * (t.last_px - t.px);
                totalFloating += pnl;
                
                const isJp = t.tk.endsWith('.T');
                const tvUrl = `https://www.tradingview.com/chart/?symbol=${{isJp ? 'TSE:' + t.tk.replace('.T', '') : t.tk}}`;
                const pnlColor = pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
                
                let progress = 50;
                if(t.sl && t.tp) {{
                    const totalRange = t.tp - t.sl;
                    progress = Math.max(0, Math.min(100, ((t.last_px - t.sl) / totalRange) * 100));
                }}
                
                openBody.innerHTML += `
                <tr class="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
                    <td class="p-3 text-[10px] text-slate-400">${{t.date}}</td>
                    <td class="p-3 font-bold text-white"><a href="${{tvUrl}}" target="_blank" class="hover:text-cyan-400">${{t.tk}}</a></td>
                    <td class="p-3"><span class="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">${{t.tag || t.type}}</span></td>
                    <td class="p-3 text-slate-300">${{isJp?'¥':'$'}}${{t.px}}</td>
                    <td class="p-3 font-bold text-white">${{isJp?'¥':'$'}}${{t.last_px}}</td>
                    <td class="p-3"><div class="w-full bg-slate-800 rounded-full h-1.5 mt-1"><div class="${{pnl >= 0 ? 'bg-emerald-500' : 'bg-red-500'}} h-1.5 rounded-full" style="width: ${{progress}}%"></div></div></td>
                    <td class="p-3 text-right font-mono font-bold ${{pnlColor}}">${{pnl >= 0 ? '+$' : '-$'}}${{Math.abs(pnl).toFixed(2)}}</td>
                </tr>`;
            }});
            totalFloatingHeader.innerHTML = `總浮盈: <span class="font-black ${{totalFloating >= 0 ? 'text-emerald-400' : 'text-red-400'}}">${{totalFloating >= 0 ? '+$' : '-$'}}${{Math.abs(totalFloating).toFixed(2)}}</span>`;
        }}

        // 2. 處理「各策略獨立表現」
        const closed = sorted.filter(t => t.status !== 'OPEN');
        const strategyStats = {{}};
        closed.forEach(t => {{
            const tag = t.tag || t.type || '未分類';
            if(!strategyStats[tag]) strategyStats[tag] = {{ wins: 0, total: 0, pnl: 0 }};
            strategyStats[tag].total++;
            if(t.status.includes('✅')) strategyStats[tag].wins++;
            strategyStats[tag].pnl += (10000 / t.px) * (t.last_px - t.px);
        }});
        
        if(Object.keys(strategyStats).length === 0) {{
             stratBody.innerHTML = '<tr><td colspan="4" class="p-4 text-slate-500 text-center">尚無數據</td></tr>';
        }} else {{
            Object.keys(strategyStats).forEach(tag => {{
                const st = strategyStats[tag];
                const pnlColor = st.pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
                stratBody.innerHTML += `
                <tr class="border-b border-white/5">
                    <td class="py-2 text-left font-bold text-slate-300">${{tag}}</td>
                    <td class="py-2 text-slate-400">${{st.total}}</td>
                    <td class="py-2 text-fuchsia-400">${{((st.wins/st.total)*100).toFixed(0)}}%</td>
                    <td class="py-2 text-right font-black ${{pnlColor}}">${{st.pnl>=0?'+':''}}${{st.pnl.toFixed(0)}}</td>
                </tr>`;
            }});
        }}

        // 3. 處理「階段結算」
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
                    <td class="py-2 text-left text-slate-400">最近 ${{n}} 筆</td>
                    <td class="py-2 text-white">${{slice.length}}</td>
                    <td class="py-2 text-indigo-400">${{((wins/slice.length)*100).toFixed(0)}}%</td>
                    <td class="py-2 text-right font-black ${{totalPnl>=0?'text-emerald-400':'text-red-400'}}">${{totalPnl>=0?'+':''}}${{totalPnl.toFixed(0)}}</td>
                </tr>`;
            }}
        }});
      }})
      .catch(e => console.log('讀取 JSON 發生錯誤:', e));
    </script>
</body>
</html>"""

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f: f.write(html)
print(f"\n🎉 黎克特制戰績自動結算版建置完成！")
