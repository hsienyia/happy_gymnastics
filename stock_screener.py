import streamlit as st
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
import requests
from datetime import datetime
import pytz
from streamlit_gsheets import GSheetsConnection

# ====================== 1. 基礎資料設定 ======================
@st.cache_data(ttl=86400)
def get_reliable_name_map():
    backup_names = {"2330": "台積電", "2317": "鴻海", "2382": "廣達", "3231": "緯創", "6669": "緯穎"}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for u in ["2", "4"]:
        try:
            res = requests.get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={u}", headers=headers, timeout=15)
            res.encoding = 'big5'
            soup = BeautifulSoup(res.text, 'html.parser')
            for row in soup.find_all('tr'):
                tds = row.find_all('td')
                if tds and '　' in tds[0].get_text():
                    code, name = tds[0].get_text().split('　', 1)
                    if len(code) == 4: backup_names[code] = name.strip()
        except: continue
    return backup_names

def get_supply_chain_db():
    base_chains = {
        "ASIC 與 高速傳輸": ["3661", "3443", "3035", "6643", "6533", "6462", "4966", "5269", "6756"],
        "AI 記憶體 (HBM/旺宏)": ["2337", "2344", "2408", "3260", "8299", "6239", "5289", "8271"],
        "實體 AI (機器人/具身)": ["2317", "2049", "4576", "2395", "6166", "1590", "1536", "8033", "2356", "1504", "2308"],
        "輝達 (NVIDIA) 供應鏈": ["2330", "2317", "2382", "3231", "6669", "3017", "3324", "3653", "2421", "2376", "2454", "3711", "3661", "3443"],
        "台積電 (TSMC) 大聯盟": ["3131", "3583", "3680", "1560", "6187", "6438", "3413", "8027", "6515", "2404", "1717", "4755"],
        "美股四大巨頭 (MAGMA)": ["2345", "6274", "2368", "2383", "3037", "8046", "3515", "4966", "2308", "6515"]
    }
    all_codes = []
    for codes in base_chains.values(): all_codes.extend(codes)
    return {"💎 核心標的總匯 (ALL)": list(set(all_codes)), **base_chains}

# ====================== 2. 分析核心 ======================
def analyze_stock_full(ticker_obj, df, mode, eps_threshold, code, is_manual=False):
    if len(df) < 40: return None
    c, l, h, o, v = df['Close'], df['Low'], df['High'], df['Open'], df['Volume']
    
    theme_label, theme_boost = "", 0.0
    try:
        info = ticker_obj.info
        summary = info.get('longBusinessSummary', '').lower()
        if 'semiconductor' in summary: theme_label = "半導體"; theme_boost = 20.0
        elif 'robot' in summary: theme_label = "機器人"; theme_boost = 20.0
    except: pass

    fwd_eps = 0.0
    try:
        fwd_eps = float(info.get('forwardEps', 0) or 0)
    except: pass

    ma5, ma20 = c.rolling(5).mean().iloc[-1], c.rolling(20).mean().iloc[-1]
    ret_5d = round(((c.iloc[-1]/c.iloc[-6])-1)*100, 2)
    ret_15d = round(((c.iloc[-1]/c.iloc[-16])-1)*100, 2)
    
    pattern = "趨勢追蹤"
    if c.iloc[-1] > ma5: pattern = "🧱 底部支撐"
    
    risk = "⚪ 一般波動"
    if ret_15d > 30: risk = "🔴 警戒避開"
    elif ret_15d < 10: risk = "🟢 優先關注"

    total_score = 50.0 + ret_5d + theme_boost
    
    return pattern, 50.0, ret_5d, ret_15d, risk, total_score, round(c.iloc[-1], 2), fwd_eps, theme_label

# ====================== 3. UI 與 雲端邏輯 ======================
st.set_page_config(page_title="戰情室 v9.1", layout="wide")
st.title("🏹 供應鏈戰情室 v9.1 (不覆寫修正版)")

name_map = get_reliable_name_map()
chains = get_supply_chain_db()

conn = st.connection("gsheets", type=GSheetsConnection)

with st.sidebar:
    selected_chain = st.selectbox("選擇預設供應鏈", list(chains.keys()))
    mode = st.radio("📊 數據模式", ["盤中即時偵測", "盤後定型分析"])
    view_mode = st.radio("📱 顯示模式", ["手機卡片 (直式)", "傳統表格 (橫式)"])

if st.button("🚀 啟動掃描並存檔"):
    raw_codes = chains[selected_chain]
    tw_tz = pytz.timezone('Asia/Taipei')
    current_time_str = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")
    
    new_results = []
    with st.spinner('正在分析並同步雲端...'):
        for code in raw_codes:
            try:
                full_code = f"{code}.TW"
                t_obj = yf.Ticker(full_code)
                df = t_obj.history(period="60d")
                if df.empty:
                    full_code = f"{code}.TWO"
                    t_obj = yf.Ticker(full_code)
                    df = t_obj.history(period="60d")
                if df.empty: continue

                res = analyze_stock_full(t_obj, df, mode, 1.7, code)
                if res:
                    new_results.append({
                        "時間": current_time_str,
                        "名稱": name_map.get(code, code), "代號": code, "現價": res[6], 
                        "風險": res[4], "形態": res[0], "波段評分": res[5], "題材": res[8]
                    })
            except: continue

    if new_results:
        df_new = pd.DataFrame(new_results)
        
        # --- 核心修正：強制合併舊資料 ---
        try:
            # 1. 嘗試讀取雲端現有資料
            existing_df = conn.read()
            if existing_df is not None and not existing_df.empty:
                # 2. 將新資料貼在舊資料「下面」
                # 用 ignore_index=True 重新編號，確保不會打結
                combined_df = pd.concat([existing_df, df_new], ignore_index=True)
            else:
                combined_df = df_new
            
            # 3. 預防重複：如果 同時間+同代號 才刪除
            combined_df = combined_df.drop_duplicates(subset=['時間', '代號'], keep='last')
            
            # 4. 寫回雲端 (這會複寫整個 Sheet，但因為我們已經包含舊資料，所以結果是 Append)
            conn.update(data=combined_df)
            st.success(f"☁️ 成功存入雲端！目前總筆數：{len(combined_df)}")
        except Exception as e:
            st.error(f"雲端寫入失敗：{e}")
            st.dataframe(df_new) # 失敗時至少顯示在螢幕上

        # 顯示當次結果
        st.subheader(f"本次掃描結果 ({current_time_str})")
        st.dataframe(df_new, use_container_width=True)
