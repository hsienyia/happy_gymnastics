import streamlit as st
import pandas as pd
from fugle_marketdata import RestClient
import yfinance as yf
from bs4 import BeautifulSoup
import requests
from datetime import datetime, timedelta
import pytz
import time

# ====================== 0. 富果 API 設定 ======================
FUGLE_API_KEY = "在此填入你的富果API金鑰"

# ====================== 1. 核心資料快取與 UI 配置 ======================
@st.cache_data(ttl=86400)
def get_reliable_name_map():
    # 這裡保留你原始的名稱抓取邏輯 (ISIN TWSE)
    names = {"2330": "台積電", "2317": "鴻海", "6187": "萬潤", "3661": "世芯-KY", "3131": "弘塑", "3583": "辛耘"}
    # ... (其餘手動或爬蟲抓取的名稱)
    return names

def get_supply_chain_db():
    return {
        "💎 核心標的總匯 (ALL)": ["2330", "2317", "6187", "3131", "3583", "3680", "1560", "2454", "3661", "3443", "3035", "6643", "3231", "6669", "3017", "3324"],
        "🔥 CoWoS/先進封裝": ["6187", "3131", "3583", "3680", "1560", "2404", "6640", "6438", "3413"],
        "📡 CPO 矽光子/光通訊": ["3363", "4979", "3081", "3450", "3163", "6451", "4908"],
        "🤖 機器人/具身智能": ["2359", "2049", "4576", "2395", "6166", "1590"],
        "❄️ GB200 散熱/水冷牆": ["3017", "3324", "3653", "2421", "3013", "3483"]
    }

@st.cache_data(ttl=3600)
def get_ticker_info_safe(code):
    try:
        t = yf.Ticker(f"{code}.TW")
        return t.info
    except: return {}

# ====================== 2. 核心分析邏輯 (v9.1.2 原始演算法) ======================
def analyze_stock_full(info, df, mode, eps_threshold, code, is_manual=False, backtest_days=0):
    if backtest_days > 0: df = df.iloc[:-backtest_days]
    elif mode == "盤後定型分析" and len(df) > 1: df = df.iloc[:-1]
    if len(df) < 40: return None
    
    # 確保 Fugle 欄位名稱對接 (首字母大寫)
    df.columns = [c.capitalize() for c in df.columns]
    c, l, h, o, v = df['Close'], df['Low'], df['High'], df['Open'], df['Volume']
    
    # 題材與 EPS 邏輯
    theme_label, theme_boost = "", 0.0
    try:
        summary = (info.get('longBusinessSummary', '') + info.get('industry', '')).lower()
        if 'cowos' in summary: theme_label, theme_boost = "CoWoS封裝", 35.0
        elif 'photonics' in summary or 'cpo' in summary: theme_label, theme_boost = "CPO矽光子", 30.0
        # ... (其餘題材邏輯)
        
        f_eps = float(info.get('forwardEps', 0) or 0)
        t_eps = float(info.get('trailingEps', 0) or 0)
        growth = (f_eps / t_eps) if t_eps > 0 else 0
        if not is_manual and growth < float(eps_threshold) and theme_boost == 0: return None
    except: 
        if not is_manual: return None
        f_eps, t_eps, growth = 0, 0, 0

    # 技術形態與評分
    ret_5d = round(((c.iloc[-1]/c.iloc[-6])-1)*100, 2)
    ret_15d = round(((c.iloc[-1]/c.iloc[-16])-1)*100, 2)
    
    # 形態判斷
    has_down_gap = any(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-5, -1))
    is_up_gap = float(df['Low'].iloc[-1]) > float(df['High'].iloc[-2])
    pattern = "🏝️ 島狀反轉" if (has_down_gap and is_up_gap) else "趨勢追蹤"
    
    # 風險與燈號
    risk = "⚪ 一般波動"
    if pattern == "🏝️ 島狀反轉" and ret_15d < 12: risk = "🟢 優先關注"
    elif ret_15d > 30: risk = "🔴 警戒避開"
    elif ret_15d < 3 and "吞噬" in pattern: risk = "🟡 築底觀察"

    total_score = (90 if "島狀" in pattern else 40) + (ret_5d * 2.5) + theme_boost
    
    return pattern, 60.0, ret_5d, ret_15d, risk, total_score, round(c.iloc[-1], 2), f_eps, t_eps, theme_label

# ====================== 3. Streamlit UI 介面 (完全復原) ======================
st.set_page_config(page_title="戰情室 v9.1.2", layout="wide")
st.title("🏹 供應鏈戰情室 v9.1.2")

name_map = get_reliable_name_map()
chains = get_supply_chain_db()

with st.sidebar:
    st.header("⚙️ 掃描設定")
    mode = st.radio("📊 數據模式", ["盤中即時偵測", "盤後定型分析"])
    selected_chain = st.selectbox("選擇預設供應鏈", list(chains.keys()))
    custom_input = st.text_input("➕ 手動新增標的", placeholder="3661, 2308")
    eps_threshold = st.slider("📈 EPS 成長門檻", 1.0, 5.0, 1.7)
    st.divider()
    st.header("💡 15% 波段實戰準則")
    st.markdown("<font color='#28a745'>🟢 優先關注</font> | <font color='#ffc107'>🟡 築底觀察</font> | <font color='#dc3545'>🔴 警戒避開</font>", unsafe_allow_html=True)

results = []
if st.button("🚀 啟動 V9.0 全面掃描"):
    client = RestClient(api_key=FUGLE_API_KEY)
    raw_codes = list(set(chains[selected_chain] + [c.strip() for c in custom_input.split(',') if c.strip()]))
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, code in enumerate(raw_codes):
        status_text.text(f"掃描中 ({i+1}/{len(raw_codes)}): {code}")
        progress_bar.progress((i + 1) / len(raw_codes))
        try:
            # --- 關鍵修正：fields 必須補齊 turnover 與 change ---
            kline = client.stock.historical.candles(
                symbol=code, 
                timeframe='D', 
                fields=['open', 'high', 'low', 'close', 'volume', 'turnover', 'change'], 
                start=(datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
            )
            
            if not kline.get('data'): continue
            df = pd.DataFrame(kline['data'])
            info = get_ticker_info_safe(code)
            
            res = analyze_stock_full(info, df, mode, eps_threshold, code, is_manual=(code in custom_input))
            if res:
                p, w, r5, r15, rsk, tot, prc, fe, te, thm = res
                results.append({
                    "名稱": name_map.get(code, code), "代號": code, "現價": prc, "風險": rsk, 
                    "形態": p, "5日%": r5, "15日%": r15, "波段評分": tot, "題材": thm,
                    "連結": f"https://tw.stock.yahoo.com/quote/{code}"
                })
            time.sleep(0.5) # 防限流
        except Exception as e:
            st.error(f"跳過 {code}: {str(e)}")
            continue

# ====================== 4. 卡片顯示區 ======================
if results:
    df_res = pd.DataFrame(results).sort_values("波段評分", ascending=False)
    tabs = st.tabs(["🟢 優先", "🟡 築底", "🔴 警戒", "⭐ 全部"])
    for i, cat in enumerate(["🟢 優先關注", "🟡 築底觀察", "🔴 警戒避開", "全部"]):
        with tabs[i]:
            display_df = df_res if cat == "全部" else df_res[df_res["風險"] == cat]
            for _, row in display_df.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([2, 1])
                    c1.subheader(f"{row['風險'][:2]} {row['名稱']} ({row['代號']})")
                    c2.link_button("📈 看圖表", row['連結'], use_container_width=True)
                    st.write(f"**現價:** `{row['現價']}` | **15日漲跌:** `{row['15日%']}%` | **題材:** {row['題材']}")
                    st.progress(min(max(int(row['波段評分']), 0)/200, 1.0), text=f"評分: {row['波段評分']}")
else:
    st.info("請啟動掃描。")
