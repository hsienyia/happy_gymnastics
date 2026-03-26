import streamlit as st
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
import requests
from datetime import datetime
import pytz  # 用於修正時區
from streamlit_gsheets import GSheetsConnection

# ====================== 1. 股票名稱與供應鏈資料 ======================
@st.cache_data(ttl=86400)
def get_reliable_name_map():
    backup_names = {
        # --- 原有標的 ---
        "2330": "台積電", "2317": "鴻海", "2382": "廣達", "3231": "緯創", "6669": "緯穎",
        "3017": "奇鋐", "3324": "雙鴻", "3653": "健策", "2421": "建準", "2376": "技嘉",
        "2454": "聯發科", "3711": "日月光投控", "3661": "世芯-KY", "3443": "創意",
        "3131": "弘塑", "3583": "辛耘", "3680": "家登", "1560": "中砂", "6187": "萬潤",
        "3035": "智原", "6643": "M31", "6462": "神盾", "6533": "晶心科",
        "2049": "上銀", "1590": "亞德客-KY", "2395": "研華", "6166": "橫河/凌華", "4576": "大銀微",
        # --- ASIC 與 高速傳輸 新增 ---
        "4966": "譜瑞-KY", "5269": "祥碩", "6756": "威鋒電子",
        # --- AI 記憶體 (HBM/旺宏) ---
        "2337": "旺宏", "2344": "華邦電", "2408": "南亞科", "3260": "威剛", "8299": "群聯", "6239": "力成", "5289": "宜鼎", "8271": "宇瞻",
        # --- 實體 AI (機器人/具身) 新增 ---
        "1536": "和大", "2356": "英業達", "1504": "東元", "2308": "台達電",
        # --- TSMC 大聯盟 新增 ---
        "6438": "迅得", "3413": "京鼎", "8027": "鈦昇", "6515": "穎崴", "2404": "漢唐", "1717": "長興", "4755": "三福化",
        # --- MAGMA / 衛星通訊 新增 ---
        "2345": "智邦", "6274": "台燿", "2368": "金像電", "2383": "台光電", "3037": "欣興", "8046": "南電", "3515": "華擎",
        "2313": "華通", "3491": "昇達科", "2314": "台揚", "6285": "啟碁", "3380": "明泰", "6684": "安格", "8103": "瀚荃", "3152": "璟德", "6213": "聯茂"
    }
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    for u in ["2", "4"]:
        try:
            res = requests.get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={u}", headers=headers, timeout=15)
            res.encoding = 'big5'
            soup = BeautifulSoup(res.text, 'html.parser')
            for row in soup.find_all('tr'):
                tds = row.find_all('td')
                if tds and '　' in tds[0].get_text():
                    parts = tds[0].get_text().split('　', 1)
                    if len(parts) == 2:
                        code, name = parts
                        if len(code) == 4: backup_names[code] = name.strip()
        except: continue
    return backup_names

def get_supply_chain_db():
    base_chains = {
        "💎 核心標的總匯 (ALL)": [], 
        "📡 低軌衛星 (LEO)": ["2313", "3491", "2314", "6285", "3380", "6684", "8103", "3152", "6213", "2383"],
        "🚀 TSMC 大聯盟/先進封裝": ["3131", "3583", "3680", "1560", "6187", "6438", "3413", "8027", "6515", "2404", "1717", "4755"],
        "⚙️ ASIC/高速傳輸/NVIDIA": ["3661", "3443", "3035", "6643", "6533", "6462", "4966", "5269", "6756", "2330", "2317", "2382", "3231", "6669", "2376", "2454", "3711"],
        "🤖 實體 AI (機器人/具身)": ["2317", "2049", "4576", "2395", "6166", "1590", "1536", "8033", "2356", "1504", "2308"],
        "🧠 AI 記憶體 (HBM/旺宏)": ["2337", "2344", "2408", "3260", "8299", "6239", "5289", "8271"],
        "❄️ GB200 散熱/水冷牆": ["3017", "3324", "3653", "2421", "3013", "3483", "6124"],
        "☁️ MAGMA 雲端巨頭鏈": ["2345", "6274", "2368", "2383", "3037", "8046", "3515", "4966", "2308", "6515"],
        "🔋 能源管理/強韌電網": ["1503", "1504", "1513", "1519", "1605", "1608", "1609"]
    }
    all_codes = []
    for k, v in base_chains.items():
        if k != "💎 核心標的總匯 (ALL)": all_codes.extend(v)
    base_chains["💎 核心標的總匯 (ALL)"] = list(set(all_codes))
    return base_chains

# ====================== 2. 核心分析邏輯 ======================
def analyze_stock_full(ticker_obj, df, mode, eps_threshold, code, is_manual=False, backtest_days=0, gsheets_data=None):
    # 優化：處理盤中數據缺失
    df = df.dropna(subset=['Close', 'High', 'Low', 'Open'])
    
    if backtest_days > 0:
        df = df.iloc[:-backtest_days]
    elif mode == "盤後定型分析" and len(df) > 1: 
        df = df.iloc[:-1]
        
    if len(df) < 40: return None
    
    # 強制轉換數值，避免 yfinance 回傳物件型態導致計算錯誤
    c = df['Close'].astype(float)
    l = df['Low'].astype(float)
    h = df['High'].astype(float)
    o = df['Open'].astype(float)
    v = df['Volume'].astype(float)
    
    theme_label, theme_boost = "", 0.0
    if is_manual: theme_label = "手動"; theme_boost = 10.0 
    
    info = {}
    try:
        info = ticker_obj.info
    except: pass

    try:
        industry = str(info.get('industry', '')).lower()
        summary = str(info.get('longBusinessSummary', '')).lower()
        
        # 題材識別邏輯更新
        if any(k in summary or k in industry for k in ['cowos', 'advanced packaging']):
            theme_label = "CoWoS/先進封裝"; theme_boost = 35.0
        elif any(k in summary or k in industry for k in ['satellite', 'leo', 'starlink', 'ground station']):
            theme_label = "低軌衛星 (LEO)"; theme_boost = 30.0 # 新增自動識別
        elif any(k in summary or k in industry for k in ['photonics', 'cpo', 'optical communication']):
            theme_label = "CPO 矽光子"; theme_boost = 30.0
        elif any(k in summary or k in industry for k in ['robot', 'automation', 'machinery']):
            theme_label = "機器人系統"; theme_boost = 25.0
        elif any(k in summary or k in industry for k in ['liquid cooling', 'thermal', 'power']):
            theme_label = "GB200 水冷散熱"; theme_boost = 25.0
        elif any(k in summary or k in industry for k in ['semiconductor', 'asic', 'design house']):
            theme_label = "ASIC/設計"; theme_boost = 20.0
        elif any(k in summary or k in industry for k in ['ai server', 'high performance hpc']):
            theme_label = "AI 伺服器"; theme_boost = 20.0
    except: pass

    fwd_eps, trail_eps, growth_boost = 0.0, 0.0, 0.0
    fair_low, fair_high, value_status = 0.0, 0.0, "N/A"
    
    try:
        fwd_eps = float(info.get('forwardEps', 0) or 0)
        if fwd_eps == 0 and gsheets_data is not None and not gsheets_data.empty:
            match = gsheets_data[gsheets_data['代號'].astype(str) == str(code)]
            if not match.empty:
                fwd_eps = float(match.iloc[0].get('預估 EPS', 0))
        
        trail_eps = float(info.get('trailingEps', 0) or 0)
        growth_ratio = (fwd_eps / trail_eps) if (trail_eps > 0 and fwd_eps > 0) else 0.0
        
        if not is_manual and theme_boost == 0:
            if not ((trail_eps <= 0 and fwd_eps > 0) or growth_ratio >= float(eps_threshold)):
                return None
            
        if fwd_eps > 0:
            fair_low, fair_high = fwd_eps * 20.0, fwd_eps * 25.0
            value_status = "低估" if c.iloc[-1] < fair_high else "高估"
            growth_boost = min(40.0, (growth_ratio - 1) * 30) if growth_ratio > 1 else 35.0
    except: 
        if not is_manual: return None

    # --- 技術面判斷 (加入盤中容錯) ---
    has_down_gap = any(h.iloc[i] < l.iloc[i-1] for i in range(-5, -1))
    is_up_gap = float(l.iloc[-1]) > float(h.iloc[-2])
    
    # 移動平均線
    ma5_series = c.rolling(5).mean()
    ma10_series = c.rolling(10).mean()
    ma20_series = c.rolling(20).mean()
    ma5, ma10, ma20 = ma5_series.iloc[-1], ma10_series.iloc[-1], ma20_series.iloc[-1]
    
    # 形態判斷
    is_engulfing = (c.iloc[-1] > o.iloc[-1]) and (c.iloc[-1] > o.iloc[-2]) and (c.iloc[-1] > ma5)
    high_20d = h.iloc[-21:-1].max() # 排除當天價格
    is_pullback_stop = (high_20d > c.iloc[-1] * 1.05) and (c.iloc[-1] > ma5) and (c.iloc[-1] > high_20d * 0.85)
    
    # 量能與突破
    v_avg5 = v.rolling(5).mean().iloc[-2]
    is_vol_burst = v.iloc[-1] > (v_avg5 * (1.1 if mode == "盤中即時偵測" else 1.5))
    is_breakthrough = (c.iloc[-1] > ma20) and (c.iloc[-1] >= h.iloc[-20:].max())
    is_volume_dry = v.iloc[-1] < (v.rolling(20).mean().iloc[-1] * 0.6) 
    is_price_tight = (h.iloc[-5:].max() - l.iloc[-5:].min()) / c.iloc[-1] < 0.05 

    pattern, p_score = "趨勢追蹤", 0.0
    if has_down_gap and is_up_gap: pattern, p_score = "🏝️ 島狀反轉", 90.0
    elif is_pullback_stop: pattern, p_score = "🚀 準備續攻", 75.0 
    elif is_engulfing: pattern, p_score = "🧱 底部吞噬", 45.0
    
    extra_boost = 25.0 if (is_vol_burst and is_breakthrough) else 0.0
    if extra_boost: pattern = "🔥 動能突破" if pattern == "趨勢追蹤" else f"{pattern}+🔥"
    if is_volume_dry and is_price_tight: pattern += " 💤"
    if growth_boost > 10: pattern += "💰"
    if value_status == "低估": pattern += "🎯"
    
    v_ratio = float(v.iloc[-1]) / ((v.rolling(5).mean().iloc[-1] + v.rolling(21).mean().iloc[-1]) / 2)
    w_raw = (v_ratio * 15.0) + ((float(c.iloc[-1])-float(l.iloc[-1]))/(float(h.iloc[-1])-float(l.iloc[-1]))*15.0 if (float(h.iloc[-1])-float(l.iloc[-1]))>0 else 7.0) + (10.0 if (ma5 > ma10 > ma20) else 0.0)
    w_score = round(w_raw * (1.2 if c.iloc[-1] > 2000 else 1.0), 1)
    
    # 漲幅計算 (防呆處理)
    try:
        ret_5d = round(((c.iloc[-1]/c.iloc[-6])-1)*100, 2)
        ret_15d = round(((c.iloc[-1]/c.iloc[-16])-1)*100, 2)
    except: ret_5d, ret_15d = 0.0, 0.0
        
    total_score = round(float(p_score) + float(w_score) + (float(ret_5d) * 2.5) + float(extra_boost) + float(growth_boost) + float(theme_boost), 1)
    
    risk = "⚪ 一般波動"
    if is_volume_dry and is_price_tight and ret_5d < 3: risk = "🟣 潛力突襲"
    elif ("島狀" in pattern or "突破" in pattern) and ret_15d < 15: risk = "🟢 優先關注"
    elif "續攻" in pattern and ret_5d < 5: risk = "🔵 準備續攻"
    elif ret_15d > 35 or (ret_5d > 18 and ret_15d > 28): risk = "🔴 警戒避開"
    elif ret_15d <= 3 and "吞噬" in pattern: risk = "🟡 築底觀察"
    
    ly_range = "N/A"
    try:
        current_year = datetime.now(tw_tz).year
        last_year = current_year - 1
        start_date = f"{last_year}-01-01"
        end_date = f"{last_year}-12-31"
        
        # 使用 yfinance 下載去年整年的數據
        hly = ticker_obj.history(start=start_date, end=end_date)
        
        if not hly.empty:
            ly_min = round(hly['Low'].min(), 1)
            ly_max = round(hly['High'].max(), 1)
            ly_range = f"{ly_min} - {ly_max}"
    except Exception as e:
        ly_range = f"資料擷取失敗"

    return pattern, w_score, ret_5d, ret_15d, risk, total_score, round(c.iloc[-1], 2), round(fwd_eps, 2), round(trail_eps, 2), f"{round(fair_low,1)}-{round(fair_high,1)}", value_status, ly_range, theme_label

# ====================== 3. UI 介面 ======================
st.set_page_config(page_title="戰情室 v9.1.2 Final", layout="wide")
st.title("🏹 供應鏈戰情室 v9.1.2 (盤中數據修正版)")

name_map = get_reliable_name_map()
chains = get_supply_chain_db()
results = [] 

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except:
    conn = None

with st.sidebar:
    st.header("⚙️ 掃描設定")
    mode = st.radio("📊 數據模式", ["盤中即時偵測", "盤後定型分析"])
    backtest_days = st.number_input("🔢 手動回溯交易日 (0為最新)", min_value=0, max_value=30, value=0, step=1)
    selected_chain = st.selectbox("選擇預設供應鏈", list(chains.keys()))
    custom_input = st.text_input("➕ 手動新增標的", placeholder="例如: 3661, 2308")
    st.divider()
    view_mode = st.radio("📱 顯示模式", ["手機卡片 (直式)", "傳統表格 (橫式)"])
    st.divider()
    st.header("💡 15% 波段實戰準則")
    st.markdown("""
    - <font color='#ffffff'>**🟣 試單佈局 → 🟡 築底加碼 → 🟢 優先重倉 → 🔵 藍燈續攻 → ⚪ 波動觀望→ 🔴 紅燈收割**</font>
    - <font color='#28a745'>**🟢 綠燈 (優先關注)**</font>: 符合強勢形態且 15 日漲幅小，風險低。
    - <font color='#6f42c1'>**🟣 紫燈 (潛力突襲)**</font>: 成交量極縮+橫盤，變盤前夕。
    - <font color='#007bff'>**🔵 藍燈 (準備續攻)**</font>: 回檔止跌、準備二次發動。
    - <font color='#ffc107'>**🟡 黃燈 (築底觀察)**</font>: 15日漲幅近0%，剛現底部吞噬。
    - <font color='#dc3545'>**🔴 紅燈 (警戒避開)**</font>: 15日漲幅過高(>30%)，防追高。
    - <font color='#17a2b8'>**🔥 (動能突破)**</font> / <font color='#6f42c1'>**💰 (成長加分)**</font>
    - <font color='#ff4b4b'>**🎯 (價值區間)**</font> / <font color='#ffffff'>**💤 (窒息量能)**</font>
    """, unsafe_allow_html=True)
    st.divider()
    min_whale = st.slider("主力吸籌門檻 (🐋)", 0, 100, 40)
    bottom_only = st.checkbox("僅顯示形態確立股", value=True)
    eps_threshold = st.slider("📈 EPS 成長門檻", 1.0, 5.0, 1.7, 0.1)

if st.button("🚀 啟動 V9.0 全面掃描"):
    raw_codes = chains[selected_chain].copy()
    manual_codes = [c.strip() for c in custom_input.replace('，', ',').split(',') if c.strip().isdigit()] if custom_input else []
    raw_codes = list(set(raw_codes + manual_codes)) 
    
    tw_tz = pytz.timezone('Asia/Taipei')
    current_time_str = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")

    gsheets_data = None
    if conn:
        try:
            gsheets_data = conn.read(ttl="10m")
        except: pass

    with st.spinner('同步最新盤中數據...'):
        tickers_list = []
        for c in raw_codes:
            tickers_list.append(f"{c}.TW")
            tickers_list.append(f"{c}.TWO")
        
        # 下載 90 天數據確保指標計算完整
        all_data = yf.download(tickers_list, period="90d", group_by='ticker', threads=True, progress=False)

        for code in raw_codes:
            try:
                df = all_data[f"{code}.TW"]
                full_code_used = f"{code}.TW"
                if df.empty or df['Close'].isnull().all():
                    df = all_data[f"{code}.TWO"]
                    full_code_used = f"{code}.TWO"
                
                if df.empty: continue
                
                t_obj = yf.Ticker(full_code_used)

                res = analyze_stock_full(t_obj, df, mode, eps_threshold, code, is_manual=(code in manual_codes), backtest_days=backtest_days, gsheets_data=gsheets_data)
                if not res: continue
                pattern, w_score, r5, r15, risk, total, price, f_eps, t_eps, fair_range, status, ly_range, theme = res
                
                if code not in manual_codes:
                    if bottom_only and "趨勢追蹤" in pattern and "潛力突襲" not in risk: continue
                    if w_score < min_whale and "潛力突襲" not in risk: continue
                
                results.append({
                    "時間": current_time_str,
                    "名稱": name_map.get(code, code), "代號": code, "現價": price, "風險": risk, "形態": pattern, 
                    "吸籌力 🐋": w_score, "5日%": r5, "15日%": r15, "波段評分": total, "題材": theme,
                    "連結": f"https://tw.stock.yahoo.com/quote/{code}", "評價": status, "預估 EPS": f_eps,
                    "合理價": fair_range, "前一EPS": t_eps, "歷年區間": ly_range
                })
            except: continue

if results:
    df_new = pd.DataFrame(results)
    
    if conn:
        try:
            existing_df = conn.read(ttl=0) 
            if existing_df is not None and not existing_df.empty:
                updated_df = pd.concat([existing_df, df_new], ignore_index=True)
                updated_df = updated_df.drop_duplicates(subset=['時間', '代號'], keep='last')
            else:
                updated_df = df_new
            conn.update(data=updated_df)
            st.success(f"☁️ 雲端同步完成！目前紀錄筆數：{len(updated_df)}")
        except Exception as e:
            st.warning(f"⚠️ 雲端同步失敗: {e}")

    df_res = df_new.sort_values("波段評分", ascending=False)
    top_medals = {0: "🏆 冠軍", 1: "🥈 亞軍", 2: "🥉 季軍"}
    
    tabs = st.tabs(["🟣 突襲", "🟡 築底", "🟢 優先", "🔵 續攻", "⚪ 一般", "🔴 警戒", "⭐ 全部"])
    for i, cat in enumerate(["🟣 潛力突襲", "🟡 築底觀察", "🟢 優先關注", "🔵 準備續攻", "⚪ 一般波動", "🔴 警戒避開", "全部"]):
        with tabs[i]:
            display_df = df_res if cat == "全部" else df_res[df_res["風險"] == cat]
            if display_df.empty:
                st.write(f"目前無 {cat} 標的。"); continue

            if view_mode == "傳統表格 (橫式)":
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                for idx, row in display_df.reset_index(drop=True).iterrows():
                    medal = top_medals.get(idx, "") if cat == "全部" else ""
                    theme_tag = f"【{row['題材']}】" if row['題材'] else ""
                    with st.container(border=True):
                        c1, c2 = st.columns([2, 1])
                        c1.subheader(f"{row['風險'][:2]} {row['名稱']} ({row['代號']})")
                        if medal: c1.caption(f"{medal} {theme_tag}")
                        elif theme_tag: c1.caption(theme_tag)
                        c2.link_button("📈 看圖表", row['連結'], use_container_width=True)
                        
                        col_l, col_r = st.columns(2)
                        with col_l:
                            st.write(f"**現價:** `{row['現價']}`")
                            st.write(f"**吸籌力:** `{row['吸籌力 🐋']}`")
                            st.markdown(f"**5日漲跌:** <font color='{'#ff4b4b' if row['5日%'] > 0 else '#28a745'}'>{row['5日%']}%</font>", unsafe_allow_html=True)
                        with col_r:
                            st.write(f"**評價:** `{row['評價']}`")
                            st.write(f"**形態:** {row['形態']}")
                            st.markdown(f"**15日漲跌:** <font color='{'#ff4b4b' if row['15日%'] > 0 else '#28a745'}'>{row['15日%']}%</font>", unsafe_allow_html=True)
                        
                        st.write(f"**波段綜合評分:**")
                        st.progress(min(max(int(row['波段評分']), 0)/400, 1.0), text=f"{row['波段評分']}")
                        
                        with st.expander("🔍 財報與價值評估詳情"):
                            st.write(f"**合理價:** {row['合理價']} | **預估 EPS:** {row['預估 EPS']}")
                            st.write(f"**前一 EPS:** {row['前一EPS']} | **歷年區間:** {row['歷年區間']}")
                            
                            st.divider()
                            st.markdown("### 🏹 實戰操作建議")
                            r_type = row['風險']
                            if "🟢" in r_type:
                                st.success("**進場：** 🏆 核心買點。建議佈局 **40-50%** 資金。")
                                st.info("**防守點：** 跳空缺口下緣 或 5日均線 (MA5)。")
                            elif "🟣" in r_type:
                                st.write("🔮 **進場：** 底部潛伏。建議小量試單 **10-15%** 資金。")
                                st.info("**防守點：** 近 5 日盤整區最低點。")
                            elif "🔵" in r_type:
                                st.info("**進場：** 回檔二抽。建議加碼或補票 **20-30%** 資金。")
                                st.info("**防守點：** 10日均線 (MA10) 支撐位。")
                            elif "🟡" in r_type:
                                st.warning("**進場：** 築底期。建議分批建立基本持股 **15-20%**。")
                                st.info("**防守點：** 底部吞噬紅棒的開盤價位置。")
                            elif "🔴" in r_type:
                                st.error("🛑 **注意：** 漲幅已過大，建議獲利了結，**不宜開新倉**。")
                            else:
                                st.write("⚪ **建議：** 趨勢不明，觀望為主。若有 🔥 標籤可考慮極短線小量參與。")

else: st.write("請啟動掃描。")
