import json

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="台股看盤 (TradingView 風格)", page_icon="📈", layout="wide")

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

POPULAR = {
    "（自行輸入）": "",
    "台積電 2330": "2330",
    "鴻海 2317": "2317",
    "聯發科 2454": "2454",
    "廣達 2382": "2382",
    "元大台灣50 0050": "0050",
    "元大高股息 0056": "0056",
    "國泰永續高股息 00878": "00878",
}

PERIODS = {"日 K": "D", "週 K": "W", "月 K": "M"}

# 主圖疊加指標 / 副圖指標（KLineChart 內建名稱）
MAIN_INDICATORS = {"均線 MA": "MA", "均線 EMA": "EMA", "布林通道": "BOLL"}
SUB_INDICATORS = {"成交量": "VOL", "KD (KDJ)": "KDJ", "MACD": "MACD", "RSI": "RSI"}

try:
    DEFAULT_TOKEN = st.secrets.get("FINMIND_TOKEN", "")
except Exception:
    DEFAULT_TOKEN = ""


# ---------------------------------------------------------------
# 資料
# ---------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="讀取 FinMind 資料中…")
def load_price(code: str, start: str, token: str) -> pd.DataFrame:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = {"dataset": "TaiwanStockPrice", "data_id": code, "start_date": start}
    r = requests.get(FINMIND_URL, params=params, headers=headers, timeout=30)
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(j.get("msg", "FinMind 回傳錯誤"))
    df = pd.DataFrame(j.get("data", []))
    if df.empty:
        return df
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["open"] > 0) & (df["close"] > 0)]  # 排除停牌日
    df["volume"] = df["volume"] / 1000  # 股 → 張
    return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=86400)
def load_name(code: str, token: str) -> str:
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        params = {"dataset": "TaiwanStockInfo", "data_id": code}
        j = requests.get(FINMIND_URL, params=params, headers=headers, timeout=20).json()
        rows = j.get("data", [])
        return rows[0].get("stock_name", "") if rows else ""
    except Exception:
        return ""


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule == "D" or df.empty:
        return df
    key = df["date"].dt.to_period("W-FRI" if rule == "W" else "M")
    return (
        df.groupby(key)
        .agg(
            date=("date", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------
# 側邊欄
# ---------------------------------------------------------------
with st.sidebar:
    st.header("看盤設定")

    pick = st.selectbox("常用標的", list(POPULAR.keys()))
    code = st.text_input(
        "股票代號",
        value=POPULAR[pick] or "2330",
        help="上市、上櫃都直接輸入代號，例如 2330、0050、6488",
    ).strip()

    period_label = st.selectbox("週期", list(PERIODS.keys()), index=0)
    years = st.slider("資料年數", 1, 10, 3)

    main_sel = st.multiselect("主圖指標", list(MAIN_INDICATORS.keys()), default=["均線 MA"])
    sub_sel = st.multiselect("副圖指標", list(SUB_INDICATORS.keys()), default=["成交量", "KD (KDJ)"])

    theme = st.radio("主題", ["dark", "light"], horizontal=True)
    tw_color = st.checkbox("紅漲綠跌（台股習慣）", value=True)
    height = st.slider("圖表高度 (px)", 500, 1100, 760, 20)

    token = st.text_input(
        "FinMind Token（選填）",
        value=DEFAULT_TOKEN,
        type="password",
        help="不填也能用，但每小時請求次數較少。也可放在 Streamlit secrets：FINMIND_TOKEN",
    ).strip()

# ---------------------------------------------------------------
# 取資料
# ---------------------------------------------------------------
if not code:
    st.info("請在左側輸入股票代號。")
    st.stop()

start = (pd.Timestamp.today() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")

try:
    daily = load_price(code, start, token)
except Exception as e:
    st.error(f"讀取 {code} 失敗：{e}")
    st.stop()

if daily.empty:
    st.warning(f"查無 {code} 的資料，請確認代號是否正確。")
    st.stop()

name = load_name(code, token)
df = resample(daily, PERIODS[period_label])

# 標題與最新報價
st.title(f"{code} {name}".strip())
last, prev = daily.iloc[-1], daily.iloc[-2] if len(daily) > 1 else daily.iloc[-1]
chg = last["close"] - prev["close"]
pct = chg / prev["close"] * 100 if prev["close"] else 0
c1, c2, c3, c4 = st.columns(4)
c1.metric("收盤", f"{last['close']:.2f}", f"{chg:+.2f} ({pct:+.2f}%)", delta_color="inverse" if tw_color else "normal")
c2.metric("最高 / 最低", f"{last['high']:.2f} / {last['low']:.2f}")
c3.metric("成交量 (張)", f"{last['volume']:,.0f}")
c4.metric("資料日期", last["date"].strftime("%Y-%m-%d"))

# ---------------------------------------------------------------
# 圖表
# ---------------------------------------------------------------
records = []
for _, r in df.iterrows():
    ts = pd.Timestamp(r["date"]).tz_localize("Asia/Taipei")
    records.append(
        {
            "timestamp": int(ts.timestamp() * 1000),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
        }
    )

if theme == "dark":
    colors = {"bg": "#131722", "fg": "#d1d4dc", "panel": "#1e222d", "border": "#2a2e39", "hover": "#2a2e39"}
else:
    colors = {"bg": "#ffffff", "fg": "#131722", "panel": "#f0f3fa", "border": "#e0e3eb", "hover": "#dde3f0"}

up, down = ("#f23645", "#089981") if tw_color else ("#089981", "#f23645")
styles = {
    "candle": {
        "bar": {
            "upColor": up,
            "downColor": down,
            "noChangeColor": "#888888",
            "upBorderColor": up,
            "downBorderColor": down,
            "noChangeBorderColor": "#888888",
            "upWickColor": up,
            "downWickColor": down,
            "noChangeWickColor": "#888888",
        },
        "priceMark": {"last": {"upColor": up, "downColor": down, "noChangeColor": "#888888"}},
    },
    "indicator": {
        "bars": [{"upColor": up, "downColor": down, "noChangeColor": "#888888"}],
    },
}

main_list = [MAIN_INDICATORS[k] for k in main_sel]
sub_list = [SUB_INDICATORS[k] for k in sub_sel]

TOOLS = [
    ("趨勢線", "segment"),
    ("射線", "rayLine"),
    ("水平線", "horizontalStraightLine"),
    ("垂直線", "verticalStraightLine"),
    ("平行通道", "parallelStraightLine"),
    ("價格通道", "priceChannelLine"),
    ("費波那契", "fibonacciLine"),
    ("價格線", "priceLine"),
]

buttons_html = "".join(f'<button class="tb" data-ov="{ov}">{label}</button>' for label, ov in TOOLS)

html = """
<style>
  html, body { margin:0; padding:0; background:__BG__; color:__FG__; font-family:-apple-system,"Segoe UI","Noto Sans TC",sans-serif; }
  #wrap { display:flex; flex-direction:column; height:__H__px; border:1px solid __BORDER__; box-sizing:border-box; }
  #bar { display:flex; flex-wrap:wrap; align-items:center; gap:6px; padding:6px 8px; background:__PANEL__; border-bottom:1px solid __BORDER__; }
  #bar span { font-size:12px; opacity:.7; margin-right:4px; }
  .tb { background:transparent; color:__FG__; border:1px solid __BORDER__; border-radius:4px; padding:4px 10px; font-size:13px; cursor:pointer; }
  .tb:hover { background:__HOVER__; }
  .tb.clear { margin-left:auto; }
  #chart { flex:1; min-height:0; }
  #err { padding:12px; color:#f23645; font-size:13px; }
</style>
<div id="wrap">
  <div id="bar"><span>畫線工具：</span>__BUTTONS__<button class="tb clear" id="clear">清除全部</button></div>
  <div id="chart"></div>
</div>
<script src="https://cdn.jsdelivr.net/npm/klinecharts@9/dist/umd/klinecharts.min.js"></script>
<script>
(function () {
  try {
    const data = __DATA__;
    const mainInds = __MAIN__;
    const subInds = __SUB__;

    try {
      klinecharts.registerLocale('zh-TW', {
        time: '時間：', open: '開：', high: '高：', low: '低：', close: '收：',
        volume: '量(張)：', turnover: '成交額：', change: '漲跌：'
      });
    } catch (e) {}

    const chart = klinecharts.init('chart');
    try { chart.setLocale('zh-TW'); } catch (e) {}
    chart.setStyles('__THEME__');
    chart.setStyles(__STYLES__);
    try { chart.setTimezone('Asia/Taipei'); } catch (e) {}
    chart.applyNewData(data);

    mainInds.forEach(function (name) {
      const params = name === 'MA' ? [5, 10, 20, 60] : (name === 'EMA' ? [5, 20, 60] : undefined);
      const ind = params ? { name: name, calcParams: params } : { name: name };
      chart.createIndicator(ind, true, { id: 'candle_pane' });
    });
    subInds.forEach(function (name) {
      chart.createIndicator(name, false, { height: 110 });
    });

    document.querySelectorAll('.tb[data-ov]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        chart.createOverlay(btn.getAttribute('data-ov'));
      });
    });
    document.getElementById('clear').addEventListener('click', function () {
      chart.removeOverlay();
    });

    window.addEventListener('resize', function () { chart.resize(); });
  } catch (e) {
    document.getElementById('chart').innerHTML = '<div id="err">圖表載入失敗：' + e.message + '</div>';
  }
})();
</script>
"""

replacements = {
    "__BG__": colors["bg"],
    "__FG__": colors["fg"],
    "__PANEL__": colors["panel"],
    "__BORDER__": colors["border"],
    "__HOVER__": colors["hover"],
    "__H__": str(height),
    "__BUTTONS__": buttons_html,
    "__DATA__": json.dumps(records),
    "__MAIN__": json.dumps(main_list),
    "__SUB__": json.dumps(sub_list),
    "__THEME__": theme,
    "__STYLES__": json.dumps(styles),
}
for k, v in replacements.items():
    html = html.replace(k, v)

components.html(html, height=height + 6, scrolling=False)
st.caption("資料來源：FinMind（日線，成交量單位為張）。畫線工具：點上方按鈕後在圖上點選位置即可。")
