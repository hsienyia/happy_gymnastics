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

# ====================== 0. 富果 API 與 全域設定 ======================
# 請務必填入你的 API Key
FUGLE_API_KEY = "NWJlNDQ4Y2QtZGZiMC00MmNkLTllNzgtZjIzZDMwNDc3OGMwIGZhZTI2MzYwLWZiZDEtNGRjYS05NGI2LWYyNThjNjFmYTE5Yw=="

# ====================== 1. 核心資料抓取與快取 ======================

@st.cache_data(ttl=86400)
def get_reliable_name_map():
    backup_names = {
        "2330": "台積電", "2317": "鴻海", "2382": "廣達", "3231": "緯創", "6669": "緯穎",
        "3017": "奇鋐", "3324": "雙鴻", "3653": "健策", "2421": "建準", "2376": "技嘉",
        "2454": "聯發科", "3711": "日月光投控", "3661": "世芯-KY", "3443": "創意",
        "3131": "弘塑", "3583": "辛耘", "3680": "家登", "1560": "中砂", "6187": "萬潤"
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    for u in ["2", "4"]:
        try:
            res = requests.get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={u}", headers=headers, timeout=10)
            res.encoding = 'big5'
            soup = BeautifulSoup(res.text, 'html.parser')
            for row in soup.find_all('tr'):
                tds = row.find_all('td')
                if tds and '　' in tds[0].get_text():
                    text = tds[0].get_text()
                    code_name = text.split('　') if '　' in text else text.split(' ')
                    if len(code_name) >= 2:
                        code, name = code_name[0].strip(), code_name[1].strip()
                        if len(code) == 4: backup_names[code] = name
        except: continue
    return backup_names

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

# 防止 Yahoo Finance 過度掃描的快取機制
@st.cache_data(ttl=3600)
def get_ticker_info_safe(code):
    try:
        t = yf.Ticker(f"{code}.TW")
        return t.info
    except: return {}

# ====================== 2. 核心分析邏輯 ======================
def analyze_stock_full(info, df, mode, eps_threshold, code, is_manual=False, backtest_days=0):
    if backtest_days > 0: df = df.iloc[:-backtest_days]
    elif mode == "盤後定型分析" and len(df) > 1: df = df.iloc[:-1]
    if len(df) < 40: return None
    
    c, l, h, o, v = df['Close'], df['Low'], df['High'], df['Open'], df['Volume']
    theme_label, theme_boost = "", 0.0
    if is_manual: theme_label = "手動"; theme_boost = 10.0 
    
    # 題材判定
    try:
        summary = (info.get('longBusinessSummary', '') + info.get('industry', '')).lower()
        if any(k in summary for k in ['cowos', 'advanced packaging']): theme_label, theme_boost = "CoWoS/先進封裝", 35.0
        elif any(k in summary for k in ['photonics', 'cpo', 'optical']): theme_label, theme_boost = "CPO 矽光子", 30.0
        elif any(k in summary for k in ['robot', 'automation']): theme_label, theme_boost = "機器人系統", 25.0
        elif any(k in summary for k in ['liquid cooling', 'thermal']): theme_label, theme_boost = "GB200 水冷散熱", 25.0
        elif any(k in summary for k in ['semiconductor', 'asic']): theme_label, theme_boost = "ASIC/設計", 20.0
    except: pass

    # EPS 邏輯
    try:
        fwd_eps = float(info.get('forwardEps', 0) or 0)
        trail_eps = float(info.get('trailingEps', 0) or 0)
        growth_ratio = (fwd_eps / trail_eps) if (trail_eps > 0) else 0.0
        if not is_manual and theme_boost == 0:
            if not (growth_ratio >= float(eps_threshold)): return None
        
        fair_range = f"{round(fwd_eps*20,1)}-{round(fwd_eps*25,1)}" if fwd_eps > 0 else "N/A"
        status = "低估" if (fwd_eps > 0 and c.iloc[-1] < fwd_eps * 25) else "高估"
    except: return None

    # 技術形態
    has_down_gap = any(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-5, -1))
    is_up_gap = float(df['Low'].iloc[-1]) > float(df['High'].iloc[-2])
    ma5, ma10, ma20 = c.rolling(5).mean().iloc[-1], c.rolling(10).mean().iloc[-1], c.rolling(20).mean().iloc[-1]
    is_engulfing = (c.iloc[-1] > o.iloc[-1]) and (c.iloc[-1] > o.iloc[-2]) and (c.iloc[-1] > ma5)
    
    pattern, p_score = "趨勢追蹤", 0.0
    if has_down_gap and is_up_gap: pattern, p_score = "🏝️ 島狀反轉", 90.0
    elif is_engulfing: pattern, p_score = "🧱 底部吞噬", 45.0

    ret_5d = round(((c.iloc[-1]/c.iloc[-6])-1)*100, 2)
    ret_15d = round(((c.iloc[-1]/c.iloc[-16])-1)*100, 2)
    
    # 風險燈號判斷
    risk = "⚪ 一般波動"
    if ("島狀" in pattern) and ret_15d < 12: risk = "🟢 優先關注"
    elif ret_15d > 35: risk = "🔴 警戒避開"
    elif ret_15d <= 2 and "吞噬" in pattern: risk = "🟡 築底觀察"

    total_score = p_score + (ret_5d * 2.5) + theme_boost
    return pattern, 50.0, ret_5d, ret_15d, risk, total_score, round(c.iloc[-1], 2), fwd_eps, trail_eps, fair_range, status, "N/A", theme_label

# ====================== 3. Streamlit UI ======================
st.set_page_config(page_title="戰情室 v9.1.2", layout="wide")
st.title("🏹 供應鏈戰情室 v9.1.2")

name_map = get_reliable_name_map()
chains = get_supply_chain_db()

with st.sidebar:
    st.header("⚙️ 掃描設定")
    mode = st.radio("📊 數據模式", ["盤中即時偵測", "盤後定型分析"])
    backtest_days = st.number_input("🔢 手動回溯交易日", 0, 30, 0)
    selected_chain = st.selectbox("選擇預設供應鏈", list(chains.keys())) # 確保 selected_chain 在按鈕前定義
    custom_input = st.text_input("➕ 手動新增標的", placeholder="3661, 2308")
    st.divider()
    view_mode = st.radio("📱 顯示模式", ["手機卡片 (直式)", "傳統表格 (橫式)"])
    st.divider()
    st.header("💡 15% 波段實戰準則")
    st.markdown("<font color='#28a745'>**🟢 綠燈 (優先關注)**</font>", unsafe_allow_html=True)
    st.markdown("<font color='#6f42c1'>**🟣 紫燈 (潛力突襲)**</font>", unsafe_allow_html=True)
    st.markdown("<font color='#ffc107'>**🟡 黃燈 (築底觀察)**</font>", unsafe_allow_html=True)
    st.markdown("<font color='#dc3545'>**🔴 紅燈 (警戒避開)**</font>", unsafe_allow_html=True)
    eps_threshold = st.slider("📈 EPS 成長門檻", 1.0, 5.0, 1.7)

results = []
if st.button("🚀 啟動 V9.0 全面掃描"):
    if FUGLE_API_KEY == "在此填入你的富果API金鑰":
        st.error("❌ 請填入 API Key"); st.stop()
    
    client = RestClient(api_key=FUGLE_API_KEY)
    codes = list(set(chains[selected_chain] + [c.strip() for c in custom_input.split(',') if c.strip()]))
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, code in enumerate(codes):
        status_text.text(f"掃描中 ({i+1}/{len(codes)}): {code}")
        progress_bar.progress((i + 1) / len(codes))
        try:
            # 富果 K 線抓取
            kline = client.stock.historical.candles(symbol=code, timeframe='D', fields=['open', 'high', 'low', 'close', 'volume'], start=(datetime.now()-timedelta(days=120)).strftime('%Y-%m-%d'))
            if not kline.get('data'): continue
            df = pd.DataFrame(kline['data']).rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
            
            # yf 快取抓取
            info = get_ticker_info_safe(code)
            
            # 執行分析
            res = analyze_stock_full(info, df, mode, eps_threshold, code)
            if res:
                p, w, r5, r15, rsk, tot, prc, fe, te, fr, stt, ly, thm = res
                results.append({"名稱": name_map.get(code, code), "代號": code, "現價": prc, "風險": rsk, "形態": p, "5日%": r5, "15日%": r15, "波段評分": tot, "題材": thm, "連結": f"https://tw.stock.yahoo.com/quote/{code}", "評價": stt, "預估 EPS": fe, "合理價": fr, "前一EPS": te})
            
            time.sleep(0.5) # 防限流關鍵：每秒最多 2 隻
        except: continue

# ====================== 4. 結果顯示 (完全回復卡片 UI) ======================
if results:
    df_res = pd.DataFrame(results).sort_values("波段評分", ascending=False)
    tabs = st.tabs(["🟢 優先", "🟡 築底", "🔴 警戒", "⭐ 全部"])
    for i, cat in enumerate(["🟢 優先關注", "🟡 築底觀察", "🔴 警戒避開", "全部"]):
        with tabs[i]:
            display_df = df_res if cat == "全部" else df_res[df_res["風險"] == cat]
            if display_df.empty: st.write("無符合標的"); continue
            
            for idx, row in display_df.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([2, 1])
                    c1.subheader(f"{row['風險'][:2]} {row['名稱']} ({row['代號']})")
                    c2.link_button("📈 看圖表", row['連結'], use_container_width=True)
                    
                    l, r = st.columns(2)
                    l.write(f"**現價:** `{row['現價']}` | **5日:** `{row['5日%']}%`")
                    r.write(f"**評價:** `{row['評價']}` | **形態:** {row['形態']}")
                    
                    st.write(f"**波段綜合評分:**")
                    st.progress(min(max(int(row['波段評分']), 0)/200, 1.0), text=f"{row['波段評分']}")
                    
                    with st.expander("🔍 財報建議"):
                        st.write(f"合理價: {row['合理價']} | 題材: {row['題材']}")
                        if "🟢" in row['風險']: st.success("🎯 核心買點，建議佈局 40-50% 資金。")
else: st.info("請按下按鈕開始掃描。")
