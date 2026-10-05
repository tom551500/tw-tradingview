import json

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="台股 TradingView 看盤", page_icon="📈", layout="wide")

# ---------------------------------------------------------------
# 常用清單（可自行增減）
# ---------------------------------------------------------------
POPULAR = {
    "台積電 2330": ("TWSE", "2330"),
    "鴻海 2317": ("TWSE", "2317"),
    "聯發科 2454": ("TWSE", "2454"),
    "廣達 2382": ("TWSE", "2382"),
    "元大台灣50 0050": ("TWSE", "0050"),
    "元大高股息 0056": ("TWSE", "0056"),
    "國泰永續高股息 00878": ("TWSE", "00878"),
    "加權指數 TAIEX": ("TWSE", "TAIEX"),
    "（自行輸入）": (None, None),
}

INTERVALS = {
    "5 分": "5",
    "15 分": "15",
    "60 分": "60",
    "日 K": "D",
    "週 K": "W",
    "月 K": "M",
}

INDICATORS = {
    "成交量": "Volume@tv-basicstudies",
    "均線 SMA": "MASimple@tv-basicstudies",
    "均線 EMA": "MAExp@tv-basicstudies",
    "布林通道": "BB@tv-basicstudies",
    "KD 隨機指標": "Stochastic@tv-basicstudies",
    "MACD": "MACD@tv-basicstudies",
    "RSI": "RSI@tv-basicstudies",
}

# ---------------------------------------------------------------
# 側邊欄
# ---------------------------------------------------------------
with st.sidebar:
    st.header("看盤設定")

    pick = st.selectbox("常用標的", list(POPULAR.keys()), index=0)
    ex_default, code_default = POPULAR[pick]

    if ex_default is None:
        market = st.radio("市場", ["上市 (TWSE)", "上櫃 (TPEX)"], horizontal=True)
        exchange = "TWSE" if "TWSE" in market else "TPEX"
        code = st.text_input(
            "股票代號", value="2330", help="例如 2330、0050、6488；也可輸入完整格式如 TWSE:2330"
        ).strip().upper()
    else:
        exchange, code = ex_default, code_default
        st.caption(f"目前：{exchange}:{code}")

    interval_label = st.selectbox("週期", list(INTERVALS.keys()), index=3)
    interval = INTERVALS[interval_label]

    chosen = st.multiselect(
        "預設指標", list(INDICATORS.keys()), default=["成交量", "均線 SMA"]
    )

    theme = st.radio("主題", ["dark", "light"], horizontal=True)
    tw_color = st.checkbox("紅漲綠跌（台股習慣）", value=True)
    height = st.slider("圖表高度 (px)", 500, 1100, 760, 20)

    st.divider()
    st.caption(
        "圖表與資料皆由 TradingView 官方嵌入元件提供，"
        "報價可能有延遲，實際以圖表顯示為準。圖上可直接使用畫線工具、"
        "加指標、換週期與搜尋其他標的。"
    )

# ---------------------------------------------------------------
# 組合代號
# ---------------------------------------------------------------
if ":" in code:
    symbol = code
else:
    symbol = f"{exchange}:{code}"

# ---------------------------------------------------------------
# TradingView Widget 設定
# ---------------------------------------------------------------
overrides = {}
if tw_color:
    up, down = "#ef5350", "#26a69a"
    # 台股：紅漲綠跌 → 上漲用紅、下跌用綠
    up, down = "#f23645", "#089981"
    overrides = {
        "mainSeriesProperties.candleStyle.upColor": up,
        "mainSeriesProperties.candleStyle.downColor": down,
        "mainSeriesProperties.candleStyle.borderUpColor": up,
        "mainSeriesProperties.candleStyle.borderDownColor": down,
        "mainSeriesProperties.candleStyle.wickUpColor": up,
        "mainSeriesProperties.candleStyle.wickDownColor": down,
    }

cfg = {
    "autosize": True,
    "symbol": symbol,
    "interval": interval,
    "timezone": "Asia/Taipei",
    "theme": theme,
    "style": "1",
    "locale": "zh_TW",
    "toolbar_bg": "#131722" if theme == "dark" else "#f1f3f6",
    "enable_publishing": False,
    "allow_symbol_change": True,
    "hide_side_toolbar": False,
    "withdateranges": True,
    "details": True,
    "hotlist": False,
    "calendar": False,
    "studies": [INDICATORS[k] for k in chosen],
    "overrides": overrides,
    "container_id": "tv_chart",
}

html = """
<div class="tradingview-widget-container" style="height:__H__px;width:100%;">
  <div id="tv_chart" style="height:__H__px;width:100%;"></div>
</div>
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script type="text/javascript">
  new TradingView.widget(__CFG__);
</script>
""".replace("__H__", str(height)).replace("__CFG__", json.dumps(cfg))

st.title("📈 台股 TradingView 看盤")
st.caption(f"目前標的：{symbol}　週期：{interval_label}")

components.html(html, height=height + 10, scrolling=False)
