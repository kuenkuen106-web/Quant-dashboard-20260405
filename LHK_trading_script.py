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
    """【實時警報】確保接收並顯示來源標籤"""
    if not DISCORD_WEBHOOK_URL or "你的專屬碼" in DISCORD_WEBHOOK_URL: return
    
    source_str = " | ".join(sources) if sources else "動態掃描"
    color = 65280 if is_bullish else 16711680 
    
    embed_data = {
        "title": f"🚨 系統異動觸發: {ticker}",
        "description": f"**{strategy_name}** 條件已達成！\n🔍 來源: `{source_str}`",
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
            if not isinstance(t, str): continue
            if t not in ticker_sources:
                ticker_sources[t] = []
            if source_label not in ticker_sources[t]:
                ticker_sources[t].append(source_label)
    # ---------------------------------------------------------
    # 1. 獲取標普 500 全名單 ((穩定版：DataHub CSV)) - 用作全面回測基礎
    # ---------------------------------------------------------
    try:
        # 這是 DataHub 維護的 S&P 500 CSV
        csv_url = "https://raw.githubusercontent.com/datasets/s-p-500-companies/master/data/constituents.csv"
        df_sp = pd.read_csv(csv_url)
        sp500_tickers = df_sp['Symbol'].str.replace('.', '-').tolist()
        add_to_map(sp500_tickers, "S&P500")
        print(f"  ✅ 成功從 DataHub 載入 S&P 500 (共 {len(sp500_tickers)} 隻)")
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
            response = requests.get(url, headers=headers)
            found_tickers = pd.read_html(response.text)[-2][1].tolist()
            found_tickers = [t for t in found_tickers if isinstance(t, str) and t.isupper() and len(t) <= 5]
            add_to_map(found_tickers, label)
            print(f"  🔥 捕捉到 {label} 標的: {len(found_tickers)} 隻")
        except:
            print(f"  ⚠️ {label} 抓取略過")

    # ---------------------------------------------------------
    # 3. 獲取日股動態名單 (Nikkei 225 + 當日熱門)
    # ---------------------------------------------------------
    try:
        # A. 核心名單：日經 225
        n225_url = 'https://en.wikipedia.org/wiki/Nikkei_225'
        response = requests.get(n225_url, headers=headers, timeout=10)
        n225_table = pd.read_html(response.text, match='Company')[0]
        n225_tickers = (n225_table.iloc[:, 1].astype(str) + '.T').tolist()
        add_to_map(n225_tickers, "NK225")
        
        # B. 🔥 捕捉日股當日熱門搜尋 (Trending in Japan)
        # 透過 Yahoo Finance API 獲取日本市場熱門標的
        jp_trending_url = "https://query1.finance.yahoo.com/v1/finance/trending/JP?count=20"
        res_jp = requests.get(jp_trending_url, headers=headers)
        if res_jp.status_code == 200:
            jp_trending = [q['symbol'] for q in res_jp.json()['finance']['result'][0]['quotes']]
            add_to_map(jp_trending, "JP熱門")
            print(f"  🔥 捕捉到日股當日焦點: {len(jp_trending)} 隻")
        print(f"  ✅ 成功構建日股動態池")
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

    
    # ---------------------------------------------------------
    # 4. 終極去重與輸出
    # ---------------------------------------------------------
    add_to_map(['SPY', '^VIX', '^N225'], "基準指數")
    print(f"🎯 股票池構建完成，總計 {len(ticker_sources)} 隻標的！")
    return ticker_sources

# 將原本的 ALL_TICKERS 替換為調用這個函數
TICKER_MAP = build_dynamic_watchlist()
ALL_TICKERS = list(TICKER_MAP.keys())

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
        
        # 策略需要計算 200天線 (SMA200) 和 一年 RS Rank
        # 如果歷史數據少於 200 筆，計算結果會全是空值，必須過濾。
        if len(c.dropna()) < 200:
            print(f"⚠️ {ticker} 數據不足 200 筆，已跳過")
            continue
        
        # 動態過濾：日股門檻 3億日圓 / 美股門檻 500萬美金
        avg_dollar_vol = (c.tail(20) * v.tail(20)).mean()
        min_liq = 300_000_000 if ticker.endswith('.T') else 5_000_000
        if avg_dollar_vol < min_liq: continue
        
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
        # 擠壓判定標準為「當前寬度 < 過去半年最小值 * 1.1」。這捕捉了波動率極度壓抑後的爆發前兆。
        is_bb_sqz = (bb_width.iloc[-1] <= bb_width.rolling(120).min().iloc[-1] * 1.1)

        # 獲取該股票嘅來源標籤
        sources = TICKER_MAP.get(ticker, ["動態掃描"])

        if is_bull and rs >= PQR_SWING_MIN and (is_vcp or is_bb_sqz):
            tag_name = "🏆 VCP 突破" if is_vcp else "💥 BB 擠壓"
            sl_p = round(cp - 2.5 * catr, 2)
            tp_p = round(cp + 4.5 * catr, 2)
            
            swing_results.append({
                'tk': ticker, 
                'pqr': round(rs, 0), 
                'px': round(cp, 2), 
                'sl': sl_p, 
                'tp': tp_p, 
                'tag': tag_name, 
                'type': 'SWING',
                'sources': sources # 確保傳入列表供 HTML 使用
            })
            
            # 【修復】加入波段策略嘅 Discord 推送
            send_discord_alert(ticker, tag_name, round(cp, 2), sl_p, tp_p, True, sources)
            
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
            sl_price = round(cp * 0.95, 2)
            tp_price = round(cp * 1.05, 2)
            
            short_term_results.append({
                'tk': ticker, 'px': round(cp, 2), 'sl': sl_price, 'tp': tp_price, 
                'tag': strategy_tag, 'type': 'SHORT', 'sources': sources
            })
            
            send_discord_alert(ticker, strategy_tag, round(cp, 2), sl_price, tp_price, True, sources)

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
