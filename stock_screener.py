import streamlit as st
import pandas as pd
from fugle_marketdata import RestClient
import yfinance as yf
import requests
from datetime import datetime, timedelta
import pytz
import time

# ====================== 0. 富果 API 設定 ======================
# 請務必填入你的 API Key，格式應為：FUGLE_API_KEY = "你的金鑰"
FUGLE_API_KEY = "NWJlNDQ4Y2QtZGZiMC00MmNkLTllNzgtZjIzZDMwNDc3OGMwIGZhZTI2MzYwLWZiZDEtNGRjYS05NGI2LWYyNThjNjFmYTE5Yw=="

# ====================== 1. 核心資料快取 ======================
@st.cache_data(ttl=86400)
def get_reliable_name_map():
    # 預設清單，防止抓取失敗時沒名稱
    return {"2330": "台積電", "2317": "鴻海", "6187": "萬潤", "3661": "世芯-KY", "3131": "弘塑", "3583": "辛耘"}

def get_supply_chain_db():
    return {
        "💎 核心標的總匯 (ALL)": ["2330", "2317", "6187", "3131", "3583", "3680", "1560", "2454", "3661", "3443"],
        "🔥 CoWoS/先進封裝": ["6187", "3131", "3583", "3680", "1560"],
        "⚙️ ASIC/設計": ["3661", "3443", "3035", "6643"]
    }

# ====================== 2. 偵錯版掃描邏輯 ======================
if "results" not in st.session_state:
    st.session_state.results = []

st.set_page_config(page_title="戰情室 v9.1.2", layout="wide")
st.title("🏹 供應鏈戰情室 v9.1.2 (Debug Mode)")

with st.sidebar:
    st.header("⚙️ 掃描設定")
    selected_chain = st.selectbox("選擇供應鏈", list(get_supply_chain_db().keys()))
    eps_threshold = st.slider("📈 EPS 成長門檻", 0.0, 5.0, 1.0) # 暫時調低門檻以測試
    st.divider()
    st.info("💡 如果沒有結果，請檢查下方的 Debug 訊息區")

if st.button("🚀 啟動偵錯掃描"):
    if FUGLE_API_KEY == "在此填入你的富果API金鑰":
        st.error("❌ 尚未填入 Fugle API Key")
        st.stop()

    client = RestClient(api_key=FUGLE_API_KEY)
    codes = get_supply_chain_db()[selected_chain]
    st.session_state.results = [] # 清空舊結果
    
    progress_bar = st.progress(0)
    debug_area = st.expander("🛠️ API 偵錯訊息路徑", expanded=True)

    for i, code in enumerate(codes):
        progress_bar.progress((i + 1) / len(codes))
        try:
            # Step 1: 測試富果 API
            start_date = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d')
            kline = client.stock.historical.candles(symbol=code, timeframe='D', fields=['open', 'high', 'low', 'close', 'volume'], start=start_date)
            
            if not kline.get('data'):
                debug_area.write(f"❌ {code}: 富果未回傳 K 線資料 (請檢查 API 權限)")
                continue
            
            df = pd.DataFrame(kline['data'])
            df.columns = [c.capitalize() for c in df.columns] # 確保首字母大寫
            df.index = pd.to_datetime(df['Date'])

            # Step 2: 測試 Yahoo Finance
            t = yf.Ticker(f"{code}.TW")
            info = t.info
            if not info or 'forwardEps' not in info:
                debug_area.write(f"⚠️ {code}: Yahoo 拒絕存取財務資料 (被限流)")
                # 如果 Yahoo 失敗，我們給予預設值繼續執行，不讓它直接 return
                info = {'forwardEps': 1.0, 'trailingEps': 1.0, 'longBusinessSummary': 'N/A'}

            # Step 3: 簡化版分析 (確認邏輯會過)
            price = df['Close'].iloc[-1]
            ret_15d = ((df['Close'].iloc[-1] / df['Close'].iloc[-16]) - 1) * 100
            
            # 簡易風險判斷
            risk = "🟢 優先關注" if ret_15d < 15 else "⚪ 一般波動"
            
            st.session_state.results.append({
                "名稱": code, # 簡化測試
                "代號": code,
                "現價": round(price, 2),
                "風險": risk,
                "15日%": round(ret_15d, 2),
                "波段評分": 80.0,
                "連結": f"https://tw.stock.yahoo.com/quote/{code}"
            })
            debug_area.write(f"✅ {code}: 分析完成")
            
            time.sleep(0.5) # 強制延遲

        except Exception as e:
            debug_area.write(f"💥 {code}: 發生錯誤 -> {str(e)}")
            continue

# ====================== 3. 顯示卡片 UI ======================
if st.session_state.results:
    st.subheader(f"📊 掃描結果 ({len(st.session_state.results)} 筆)")
    for row in st.session_state.results:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.subheader(f"{row['風險'][:2]} {row['名稱']} ({row['代號']})")
            c2.link_button("📈 看圖表", row['連結'])
            st.write(f"**現價:** `{row['現價']}` | **15日漲跌:** `{row['15日%']}%`")
            st.progress(0.8, text=f"評分: {row['波段評分']}")
else:
    st.warning("目前無任何掃描結果，請查看下方的偵錯訊息區。")
