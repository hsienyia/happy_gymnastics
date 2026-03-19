import streamlit as st
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
import requests
from datetime import datetime

# ====================== 1. 股票名稱與供應鏈資料 ======================
@st.cache_data(ttl=86400)
def get_reliable_name_map():
    backup_names = {
        "2330": "台積電", "2317": "鴻海", "2382": "廣達", "3231": "緯創", "6669": "緯穎",
        "3017": "奇鋐", "3324": "雙鴻", "3653": "健策", "2421": "建準", "2376": "技嘉",
        "2454": "聯發科", "3711": "日月光投控", "3661": "世芯-KY", "3443": "創意",
        "3131": "弘塑", "3583": "辛耘", "3680": "家登", "1560": "中砂", "6187": "萬潤",
        "3035": "智原", "6643": "M31", "6462": "神盾", "6533": "晶心科",
        "2337": "旺宏", "2344": "華邦電", "2408": "南亞科", "3260": "威剛", "5289": "宜鼎",
        "2049": "上銀", "1590": "亞德客-KY", "2395": "研華", "6166": "橫河/凌華", "4576": "大銀微"
    }
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

# ====================== 2. 核心分析邏輯 ======================
def analyze_stock_full(ticker_obj, df, mode, eps_threshold, code, is_manual=False):
    if mode == "盤後定型分析" and len(df) > 1: df = df.iloc[:-1]
    if len(df) < 40: return None
    c, l, h, o, v = df['Close'], df['Low'], df['High'], df['Open'], df['Volume']
    
    theme_label, theme_boost = "", 0.0
    if is_manual: theme_label = "(手動分析)"; theme_boost = 10.0 
    
    try:
        info = ticker_obj.info
        industry = info.get('industry', '').lower()
        summary = info.get('longBusinessSummary', '').lower()
        if any(k in industry or k in summary for k in ['semiconductor', 'asic', 'design house']):
            theme_label = "(ASIC+30)"; theme_boost = 30.0
        elif any(k in industry or k in summary for k in ['robot', 'automation', 'machinery']):
            theme_label = "(Robot+25)"; theme_boost = 25.0
        elif any(k in industry or k in summary for k in ['power', 'liquid cooling', 'thermal']):
            theme_label = "(Cooling+20)"; theme_boost = 20.0
    except: pass

    fwd_eps, trail_eps, growth_boost = 0.0, 0.0, 0.0
    fair_low, fair_high, value_status = 0.0, 0.0, "N/A"
    try:
        fwd_eps = float(info.get('forwardEps', 0) or 0)
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

    # 技術形態與數據計算
    has_down_gap = any(df['High'].iloc[i] < df['Low'].iloc[i-1] for i in range(-5, -1))
    is_up_gap = float(df['Low'].iloc[-1]) > float(df['High'].iloc[-2])
    
    # 均線計算
    ma5_all = c.rolling(5).mean()
    ma10_all = c.rolling(10).mean()
    ma20_all = c.rolling(20).mean()
    ma5, ma10, ma20 = ma5_all.iloc[-1], ma10_all.iloc[-1], ma20_all.iloc[-1]
    
    is_engulfing = (c.iloc[-1] > o.iloc[-1]) and (c.iloc[-1] > o.iloc[-2]) and (c.iloc[-1] > ma5)
    
    high_20d = h.iloc[-20:-1].max()
    is_pullback_stop = (high_20d > c.iloc[-1] * 1.05) and (c.iloc[-1] > ma5) and (c.iloc[-1] > high_20d * 0.90)
    
    v_avg5 = v.rolling(5).mean().iloc[-2]
    is_vol_burst = v.iloc[-1] > (v_avg5 * (1.2 if mode == "盤中即時偵測" else 1.5))
    is_breakthrough = (c.iloc[-1] > ma20) and (c.iloc[-1] >= h.iloc[-20:].max())

    avg_v_20 = v.rolling(20).mean().iloc[-1]
    is_volume_dry = v.iloc[-1] < (avg_v_20 * 0.5) 
    is_price_tight = (h.iloc[-5:].max() - l.iloc[-5:].min()) / c.iloc[-1] < 0.04 

    pattern, p_score = "趨勢追蹤", 0.0
    if has_down_gap and is_up_gap: pattern, p_score = "🏝️ 島狀反轉", 90.0
    elif is_pullback_stop: pattern, p_score = "🚀 準備續攻", 75.0 
    elif is_engulfing: pattern, p_score = "🧱 底部吞噬", 45.0
    
    extra_boost = 25.0 if (is_vol_burst and is_breakthrough) else 0.0
    if extra_boost: pattern = "🔥 動能突破" if pattern == "趨勢追蹤" else f"{pattern}+🔥"
    
    if is_volume_dry and is_price_tight:
        pattern += " 💤"
    
    if growth_boost > 10: pattern += "💰"
    if value_status == "低估": pattern += "🎯"
    
    final_pattern = f"{pattern} {theme_label}" if theme_label else pattern
    
    # 吸籌力優化計算
    v_smooth_avg = (v.rolling(5).mean().iloc[-1] + v.rolling(21).mean().iloc[-1]) / 2
    v_ratio = float(v.iloc[-1]) / v_smooth_avg
    trend_bonus = 10.0 if (ma5 > ma10 > ma20) else 0.0
    close_pos_score = ((float(c.iloc[-1])-float(l.iloc[-1]))/(float(h.iloc[-1])-float(l.iloc[-1]))*15.0 if (float(h.iloc[-1])-float(l.iloc[-1]))>0 else 7.0)
    w_raw = (v_ratio * 15.0) + close_pos_score + trend_bonus
    price_factor = 1.2 if c.iloc[-1] > 2000 else 1.0
    w_score = round(w_raw * price_factor, 1)
    
    ret_5d, ret_15d = round(((c.iloc[-1]/c.iloc[-6])-1)*100, 2), round(((c.iloc[-1]/c.iloc[-16])-1)*100, 2)
    total_score = round(float(p_score) + float(w_score) + (float(ret_5d) * 2.5) + float(extra_boost) + float(growth_boost) + float(theme_boost), 1)
    
    risk = "⚪ 一般波動"
    if is_volume_dry and is_price_tight and ret_5d < 3: risk = "🟣 潛力突襲"
    elif ("島狀" in pattern or "突破" in pattern) and ret_15d < 12: risk = "🟢 優先關注"
    elif "續攻" in pattern and ret_5d < 5: risk = "🔵 準備續攻"
    elif ret_15d > 35 or (ret_5d > 15 and ret_15d > 25): risk = "🔴 警戒避開"
    elif ret_15d <= 2 and "吞噬" in pattern: risk = "🟡 築底觀察"
    
    ly_range = "N/A"
    try:
        ly = datetime.now().year - 1
        hly = ticker_obj.history(start=f"{ly}-01-01", end=f"{ly}-12-31")
        if not hly.empty: ly_range = f"{round(hly['Low'].min(), 1)} - {round(hly['High'].max(), 1)}"
    except: pass

    return final_pattern, w_score, ret_5d, ret_15d, risk, total_score, round(c.iloc[-1], 2), round(fwd_eps, 2), round(trail_eps, 2), f"{round(fair_low,1)}-{round(fair_high,1)}", value_status, ly_range

# ====================== 3. UI 介面 ======================
st.set_page_config(page_title="戰情室 v8.5.9", layout="wide")
st.title("🏹 供應鏈主力大戶決策戰情室 v8.5.9 (介面優化版)")

name_map = get_reliable_name_map()
chains = get_supply_chain_db()
results = [] 

with st.sidebar:
    st.header("⚙️ 掃描設定")
    mode = st.radio("📊 數據模式", ["盤中即時偵測", "盤後定型分析"])
    selected_chain = st.selectbox("選擇預設供應鏈", list(chains.keys()))
    custom_input = st.text_input("➕ 手動新增標的 (直接分析)", placeholder="例如: 3661, 2308")
    st.divider()
    st.header("💡 15% 波段實戰準則")
    st.markdown("""
    - <font color='#28a745'>**🟢 綠燈 (優先關注)**</font>: 符合強勢形態且 15 日漲幅小。
    - <font color='#6f42c1'>**🟣 紫燈 (潛力突襲)**</font>: 成交量極縮+橫盤，預防暴風雨前寧靜。
    - <font color='#007bff'>**🔵 藍燈 (準備續攻)**</font>: 回檔止跌標的。
    - <font color='#ffc107'>**🟡 黃燈 (築底觀察)**</font>: 剛出現起漲訊號。
    - <font color='#dc3545'>**🔴 紅燈 (警戒避開)**</font>: 避免追高。
    - <font color='#17a2b8'>**🔥 圖示 (動能突破)**</font>: 短期爆發力強。
    - <font color='#6f42c1'>**💰 圖示 (成長加分)**</font>: EPS 成長強勁。
    - <font color='#ff4b4b'>**🎯 圖示 (價值區間)**</font>: 低估區。
    - <font color='#ffffff'>**💤 圖示 (窒息量能)**</font>: 盤整等待變盤。
    """, unsafe_allow_html=True)
    st.divider()
    min_whale = st.slider("主力吸籌門檻 (🐋)", 0, 100, 40); bottom_only = st.checkbox("僅顯示形態確立股", value=True)
    eps_threshold = st.slider("📈 EPS 成長倍數門檻", 1.0, 5.0, 1.7, 0.1)

if st.button("🚀 啟動 V8.5.9 全面掃描"):
    raw_codes = chains[selected_chain].copy()
    manual_codes = []
    if custom_input:
        manual_codes = [c.strip() for c in custom_input.replace('，', ',').split(',') if c.strip().isdigit()]
        raw_codes = list(set(raw_codes + manual_codes)) 
    
    with st.spinner('正在分析標的與突襲偵測...'):
        update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"🕒 更新時間：{update_time}")
        for code in raw_codes:
            try:
                is_manual_stock = code in manual_codes
                full_code = code + (".TW" if int(code) < 5000 else ".TWO")
                t_obj = yf.Ticker(full_code)
                df = t_obj.history(period="60d")
                if df.empty: continue
                res = analyze_stock_full(t_obj, df, mode, eps_threshold, code, is_manual=is_manual_stock)
                if not res: continue
                pattern, w_score, r5, r15, risk, total, price, f_eps, t_eps, fair_range, status, ly_range = res
                if not is_manual_stock:
                    if bottom_only and "趨勢追蹤" in pattern and "潛力突襲" not in risk: continue
                    if w_score < min_whale and "潛力突襲" not in risk: continue
                results.append({
                    "名稱": name_map.get(code, code), 
                    "🔗 連結": f"https://tw.stock.yahoo.com/quote/{code}", 
                    "代號": code,
                    "現價": price, "去年(曆年)區間": ly_range, "合理區間(20-25)": fair_range, 
                    "評價": status, "前一年 EPS": t_eps, "預估 EPS": f_eps, "風險": risk, "形態": pattern, 
                    "吸籌力 🐋": w_score, "5日%": r5, "15日%": r15, "波段評分": total
                })
            except: continue

if results:
    df_res = pd.DataFrame(results)
    # 重新排列欄位順序，讓連結緊跟在名稱後面
    cols = ["名稱", "🔗 連結", "現價", "去年(曆年)區間", "合理區間(20-25)", "評價", "前一年 EPS", "預估 EPS", "風險", "形態", "吸籌力 🐋", "5日%", "15日%", "波段評分"]
    df_res = df_res[cols]
    
    tabs = st.tabs(["🟢 優先關注", "🟣 潛力突襲", "🔵 準備續攻", "🟡 築底觀察", "⚪ 一般波動", "🔴 警戒避開", "⭐ 全部標的"])
    for i, cat in enumerate(["🟢 優先關注", "🟣 潛力突襲", "🔵 準備續攻", "🟡 築底觀察", "⚪ 一般波動", "🔴 警戒避開", "全部"]):
        with tabs[i]:
            display_df = df_res.sort_values("波段評分", ascending=False) if cat == "全部" else df_res[df_res["風險"] == cat].sort_values("波段評分", ascending=False)
            if not display_df.empty:
                st.dataframe(display_df, column_config={
                    "🔗 連結": st.column_config.LinkColumn("代號", display_text=r"(\d+)"), # 用正則表達式或預存的代號顯示
                    "現價": st.column_config.NumberColumn(format="%.2f"), 
                    "波段評分": st.column_config.ProgressColumn(min_value=0, max_value=400), 
                }, use_container_width=True, hide_index=True)
            else: st.write(f"目前無 {cat} 標的。")
else: st.write("請啟動掃描。")
