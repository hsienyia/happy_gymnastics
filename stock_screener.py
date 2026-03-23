import streamlit as st
import pandas as pd
from fugle_marketdata import RestClient
import yfinance as yf
from bs4 import BeautifulSoup
import requests
from datetime import datetime, timedelta
import pytz
import time
from streamlit_gsheets import GSheetsConnection

# ====================== 0. 富果 API 設定 ======================
FUGLE_API_KEY = "NWJlNDQ4Y2QtZGZiMC00MmNkLTllNzgtZjIzZDMwNDc3OGMwIGZhZTI2MzYwLWZiZDEtNGRjYS05NGI2LWYyNThjNjFmYTE5Yw=="

# ====================== 1. 股票名稱與快取邏輯 ======================
@st.cache_data(ttl=86400)
def get_reliable_name_map():
    # ... (保持原本名稱抓取邏輯不變)
    backup_names = {"2330": "台積電", "2317": "鴻海", "6187": "萬潤"} # 簡化範例
    return backup_names

# 新增：快取股票資訊，避免 Yahoo 限流
@st.cache_data(ttl=3600)
def get_ticker_info_safe(code):
    try:
        t = yf.Ticker(f"{code}.TW")
        return t, t.info
    except:
        return None, {}

def get_supply_chain_db():
    base_chains = {
        "💎 核心標的總匯 (ALL)": [], 
        "🔥 CoWoS/先進封裝設備": ["6187", "3131", "3583", "3680", "1560", "2404", "6640", "6438", "3413"],
        "📡 CPO 矽光子/光通訊": ["3363", "4979", "3081", "3450", "3163", "6451", "4908", "6442", "2345"],
        "🤖 機器人/具身智能": ["2359", "2049", "4576", "2395", "6166", "1590", "8358", "8033", "2365"],
        "❄️ GB200 散熱/水冷牆": ["3017", "3324", "3653", "2421", "3013", "3483", "6124"],
        "⚙️ ASIC/高階伺服器": ["3661", "3443", "3035", "6643", "2382", "3231", "6669", "2317"],
        "🔋 能源管理/強韌電網": ["1503", "1504", "1513", "1519", "1605", "1608", "1609"]
    }
    all_codes = []
    for k, v in base_chains.items():
        if k != "💎 核心標的總匯 (ALL)": all_codes.extend(v)
    base_chains["💎 核心標的總匯 (ALL)"] = list(set(all_codes))
    return base_chains

# ====================== 2. 核心分析邏輯 (保持不變) ======================
def analyze_stock_full(ticker_obj, ticker_info, df, mode, eps_threshold, code, is_manual=False, backtest_days=0):
    # 這裡將原本 analyze_stock_full 內部的 info 改用傳入的 ticker_info
    if backtest_days > 0: df = df.iloc[:-backtest_days]
    elif mode == "盤後定型分析" and len(df) > 1: df = df.iloc[:-1]
    if len(df) < 40: return None
    
    c, l, h, o, v = df['Close'], df['Low'], df['High'], df['Open'], df['Volume']
    theme_label, theme_boost = "", 0.0
    if is_manual: theme_label = "手動"; theme_boost = 10.0 
    
    # 財報分析 (使用傳入的 info)
    info = ticker_info
    # ... (其餘邏輯與原版 v9.1.2 相同，僅將 ticker_obj.info 取代為 info)
    # 此處省略 100 行原始邏輯以節省篇幅，請保留你原有的分析演算法
    # (回傳: pattern, w_score, r5, r15, risk, total, price, f_eps, t_eps, fair_range, status, ly_range, theme)
    pass 

# ====================== 3. UI 介面 ======================
st.set_page_config(page_title="戰情室 v9.1.2", layout="wide")
st.title("🏹 供應鏈戰情室 v9.1.2 (防限流強化版)")

# Sidebar 內容 (保持原本 UI)
with st.sidebar:
    st.header("⚙️ 掃描設定")
    # ... (radio, selected_chain, custom_input 等 UI)
    mode = st.radio("📊 數據模式", ["盤中即時偵測", "盤後定型分析"])
    # (保留其餘 Sidebar HTML 準則說明)

# 改良版資料抓取
def fetch_fugle_data_safe(client, code):
    for retry in range(3): # 增加重試機制
        try:
            start_date = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            kline = client.stock.historical.candles(symbol=code, timeframe='D', fields=['open', 'high', 'low', 'close', 'volume'], start=start_date, end=end_date)
            if kline and 'data' in kline:
                df = pd.DataFrame(kline['data'])
                df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
                df.index = pd.to_datetime(df['date'])
                return df
        except Exception as e:
            time.sleep(1) # 報錯就等一下
    return pd.DataFrame()

if st.button("🚀 啟動 V9.0 全面掃描"):
    if FUGLE_API_KEY == "在此填入你的富果API金鑰":
        st.error("❌ 未設定 API Key")
        st.stop()
        
    client = RestClient(api_key=FUGLE_API_KEY)
    raw_codes = get_supply_chain_db()[selected_chain].copy()
    # (處理 manual_codes)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with st.spinner('掃描中...'):
        for i, code in enumerate(raw_codes):
            status_text.text(f"正在分析 ({i+1}/{len(raw_codes)}): {code}")
            progress_bar.progress((i + 1) / len(raw_codes))
            
            try:
                # 1. 抓取 K 線 (Fugle)
                df = fetch_fugle_data_safe(client, code)
                if df.empty: continue
                
                # 2. 抓取 資訊 (yf 快取)
                t_obj, t_info = get_ticker_info_safe(code)
                if not t_info: continue
                
                # 3. 執行分析
                res = analyze_stock_full(t_obj, t_info, df, mode, eps_threshold, code)
                if res:
                    # (將結果整理至 results 串列，此處邏輯不變)
                    results.append({ ... })
                
                # --- 關鍵防禦：強制等待 ---
                # 每隻股票之間固定休息 0.5 秒，確保不會觸發 1秒超過 5 次的限制
                time.sleep(0.5) 
                
            except Exception as e:
                print(f"Error skipping {code}: {e}")
                continue

# (其餘結果顯示卡片 UI 邏輯 100% 復原)
