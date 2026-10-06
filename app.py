import json
import time

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

# 週期：分K 需要 FinMind 付費權限；日K 以上免費
PERIODS = {
    "1 分": "1m",
    "30 分": "30m",
    "60 分": "60m",
    "日 K": "D",
    "3 日 K": "3D",
    "週 K": "W",
    "月 K": "M",
}
INTRADAY = {"1m": 1, "30m": 30, "60m": 60}

# 主圖疊加指標 / 副圖指標（KLineChart 內建名稱）
MAIN_INDICATORS = {"均線 MA": "MA", "均線 EMA": "EMA", "布林通道": "BOLL"}
SUB_INDICATORS = {"成交量": "VOL", "KD (KDJ)": "KDJ", "MACD": "MACD", "RSI": "RSI"}

try:
    DEFAULT_TOKEN = st.secrets.get("FINMIND_TOKEN", "")
except Exception:
    DEFAULT_TOKEN = ""


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------------------------------------------------------------
# 日線資料
# ---------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="讀取 FinMind 日線資料中…")
def load_price(code: str, start: str, token: str) -> pd.DataFrame:
    params = {"dataset": "TaiwanStockPrice", "data_id": code, "start_date": start}
    r = requests.get(FINMIND_URL, params=params, headers=_headers(token), timeout=30)
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
        params = {"dataset": "TaiwanStockInfo", "data_id": code}
        j = requests.get(FINMIND_URL, params=params, headers=_headers(token), timeout=20).json()
        rows = j.get("data", [])
        return rows[0].get("stock_name", "") if rows else ""
    except Exception:
        return ""


# ---------------------------------------------------------------
# 分K 資料（FinMind TaiwanStockKBar，需付費權限）
# ---------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def load_kbar_day(code: str, day: str, token: str) -> pd.DataFrame:
    params = {"dataset": "TaiwanStockKBar", "data_id": code, "start_date": day, "end_date": day}
    r = requests.get(FINMIND_URL, params=params, headers=_headers(token), timeout=30)
    j = r.json()
    if j.get("status") != 200:
        raise RuntimeError(j.get("msg", "FinMind 回傳錯誤"))
    df = pd.DataFrame(j.get("data", []))
    if df.empty:
        return df
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    time_col = "minute" if "minute" in df.columns else ("time" if "time" in df.columns else None)
    need = {"date", "open", "high", "low", "close", "volume"}
    if time_col is None or not need.issubset(df.columns):
        raise RuntimeError(f"分K 欄位與預期不同：{list(df.columns)}")
    df["dt"] = pd.to_datetime(df["date"].astype(str) + " " + df[time_col].astype(str))
    return df[["dt", "open", "high", "low", "close", "volume"]]


def load_kbar(code: str, ndays: int, token: str) -> pd.DataFrame:
    frames, got, tries = [], 0, 0
    day = pd.Timestamp.today().normalize()
    while got < ndays and tries < ndays * 2 + 10:
        if day.weekday() < 5:
            d = load_kbar_day(code, day.strftime("%Y-%m-%d"), token)
            if not d.empty:
                frames.append(d)
                got += 1
        day -= pd.Timedelta(days=1)
        tries += 1
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_values("dt").reset_index(drop=True)
    return df[(df["open"] > 0) & (df["close"] > 0)]


# ---------------------------------------------------------------
# 分K 資料（Yahoo Finance，免費；1分 最多約 5 個交易日，30/60 分 約 60 天）
# ---------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def yahoo_fetch(code: str, interval: str, calendar_days: int) -> pd.DataFrame:
    now = int(time.time())
    p1 = now - calendar_days * 86400
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    last_err = ""
    for suffix in (".TW", ".TWO"):  # 上市 .TW、上櫃 .TWO
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}"
        params = {"interval": interval, "period1": p1, "period2": now, "includePrePost": "false"}
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 429:
            raise RuntimeError("Yahoo 暫時限制請求（429），請稍後再試")
        try:
            j = r.json()
        except Exception:
            last_err = f"HTTP {r.status_code}"
            continue
        chart = j.get("chart", {})
        res = chart.get("result")
        if not res:
            last_err = (chart.get("error") or {}).get("description", "查無資料")
            continue
        res = res[0]
        ts = res.get("timestamp") or []
        quote = (res.get("indicators", {}).get("quote") or [{}])[0]
        if not ts or not quote:
            last_err = "查無資料"
            continue
        n = len(ts)
        df = pd.DataFrame(
            {
                "ts": ts,
                "open": quote.get("open") or [None] * n,
                "high": quote.get("high") or [None] * n,
                "low": quote.get("low") or [None] * n,
                "close": quote.get("close") or [None] * n,
                "volume": quote.get("volume") or [None] * n,
            }
        ).dropna(subset=["open", "high", "low", "close"])
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
        df["volume"] = df["volume"].fillna(0) / 1000  # 股 → 張
        return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)
    raise RuntimeError(last_err or "查無資料")


def load_yahoo_intraday(code: str, interval: str, ndays: int) -> pd.DataFrame:
    cap = 7 if interval == "1m" else 59
    calendar_days = min(int(ndays * 1.6) + 3, cap)
    df = yahoo_fetch(code, interval, calendar_days)
    # 只保留最近 ndays 個交易日
    days = df["date"].dt.normalize().drop_duplicates().tolist()[-ndays:]
    return df[df["date"].dt.normalize().isin(days)].reset_index(drop=True)


def merge_today(daily: pd.DataFrame, code: str):
    """FinMind 日線收盤後才更新；若缺最新交易日，用 Yahoo 日線補上（盤中約延遲 20 分鐘）。"""
    try:
        y = yahoo_fetch(code, "1d", 10)
    except Exception:
        return daily, False
    y = y.copy()
    y["date"] = y["date"].dt.normalize()
    y = y.drop_duplicates("date", keep="last")
    newer = y[y["date"] > daily["date"].max()]
    if newer.empty:
        return daily, False
    return pd.concat([daily, newer], ignore_index=True), True


def to_intraday_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if df.empty:
        return df
    if minutes == 1:
        return df.rename(columns={"dt": "date"})
    # 若資料時間標在「該分鐘結束」(最早一筆 ≥ 09:01)，分組前先往前移 1 分鐘
    tod = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    shift = pd.Timedelta(minutes=1) if tod.min() >= 9 * 60 + 1 else pd.Timedelta(0)
    key = (df["dt"] - shift).dt.floor(f"{minutes}min")
    out = (
        df.groupby(key)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
        .rename(columns={"dt": "date"})
    )
    return out


# ---------------------------------------------------------------
# 日線以上的重組
# ---------------------------------------------------------------
def _agg(g):
    return g.agg(
        date=("date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule == "D" or df.empty:
        return df
    if rule == "3D":
        # 從最新一天往回，每 3 個交易日合成一根（最新一根一定是完整的 3 日）
        idx = pd.Series(range(len(df)), index=df.index)
        grp = (len(df) - 1 - idx) // 3
        return _agg(df.groupby(grp)).sort_values("date").reset_index(drop=True)
    key = df["date"].dt.to_period("W-FRI" if rule == "W" else "M")
    return _agg(df.groupby(key)).reset_index(drop=True)


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

    period_label = st.selectbox("週期", list(PERIODS.keys()), index=3)
    period_key = PERIODS[period_label]
    is_intraday = period_key in INTRADAY

    if is_intraday:
        kbar_source_label = st.selectbox(
            "分K 資料來源", ["Yahoo Finance（免費）", "FinMind（需 Sponsor 付費）"], index=0
        )
        kbar_source = "yahoo" if kbar_source_label.startswith("Yahoo") else "finmind"
        kbar_days = st.slider("分K 天數（交易日）", 1, 20, 5)
        if kbar_source == "yahoo":
            st.caption("Yahoo 的 1 分K 最多約 5 個交易日，30 / 60 分約 60 天；報價可能延遲約 20 分鐘。")
        else:
            st.caption("FinMind 分K 需要 Sponsor 等級的 Token。")
    else:
        years = st.slider("資料年數", 1, 10, 3)

    main_sel = st.multiselect("主圖指標", list(MAIN_INDICATORS.keys()), default=["均線 MA"])
    sub_sel = st.multiselect("副圖指標", list(SUB_INDICATORS.keys()), default=["成交量", "KD (KDJ)"])

    theme = st.radio("主題", ["dark", "light"], horizontal=True)
    tw_color = st.checkbox("紅漲綠跌（台股習慣）", value=True)
    height = st.slider("圖表高度 (px)", 500, 1100, 760, 20)

    token = st.text_input(
        "FinMind Token（日K 選填、分K 必填）",
        value=DEFAULT_TOKEN,
        type="password",
        help="也可放在 Streamlit secrets：FINMIND_TOKEN",
    ).strip()

# ---------------------------------------------------------------
# 取資料
# ---------------------------------------------------------------
if not code:
    st.info("請在左側輸入股票代號。")
    st.stop()

if is_intraday and kbar_source == "finmind" and not token:
    st.warning("FinMind 分K 需要 Token，請在左側填入，或改用 Yahoo Finance 資料來源。")
    st.stop()

if is_intraday:
    daily_start = (pd.Timestamp.today() - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
else:
    daily_start = (pd.Timestamp.today() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")

try:
    daily = load_price(code, daily_start, token)
except Exception as e:
    st.error(f"讀取 {code} 失敗：{e}")
    st.stop()

if daily.empty:
    st.warning(f"查無 {code} 的資料，請確認代號是否正確。")
    st.stop()

daily, patched = merge_today(daily, code)

if is_intraday and kbar_source == "yahoo":
    try:
        with st.spinner("讀取 Yahoo Finance 分K 資料中…"):
            df = load_yahoo_intraday(code, period_key, kbar_days)
    except Exception as e:
        st.error(f"讀取 {code} 分K 失敗：{e}\n\nYahoo 偶爾會擋雲端主機，可稍後重試，或改選日 K 以上的週期。")
        st.stop()
elif is_intraday:
    try:
        with st.spinner("讀取 FinMind 分K 資料中…"):
            raw = load_kbar(code, kbar_days, token)
    except Exception as e:
        st.error(f"讀取 {code} 分K 失敗：{e}\n\n分K 資料集通常需要 FinMind 付費會員權限，請確認 Token 的等級。")
        st.stop()
    if raw.empty:
        st.warning(f"查無 {code} 的分K 資料。")
        st.stop()
    df = to_intraday_bars(raw, INTRADAY[period_key])
else:
    df = resample(daily, period_key)

name = load_name(code, token)

# 標題與最新報價（用日線）
st.title(f"{code} {name}".strip())
if patched:
    st.caption("最新交易日資料來自 Yahoo Finance（盤中約延遲 20 分鐘）；FinMind 收盤後更新完成就會改用 FinMind。")
last = daily.iloc[-1]
prev = daily.iloc[-2] if len(daily) > 1 else daily.iloc[-1]
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
        volume: '量：', turnover: '成交額：', change: '漲跌：'
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

    // ---- 畫線持久化：依股票代號存，與週期無關（以「時間 + 價格」定位）----
    const STORE_KEY = 'tvdraw_' + __CODE__;
    const reg = {};
    function loadSaved() {
      try { return JSON.parse(localStorage.getItem(STORE_KEY) || '[]'); } catch (e) { return []; }
    }
    function persist() {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(Object.values(reg))); } catch (e) {}
    }
    function snap(o) {
      return {
        id: o.id,
        name: o.name,
        points: (o.points || []).map(function (p) { return { timestamp: p.timestamp, value: p.value }; })
      };
    }
    function handlers() {
      return {
        onDrawEnd: function (e) { reg[e.overlay.id] = snap(e.overlay); persist(); return false; },
        onPressedMoveEnd: function (e) { reg[e.overlay.id] = snap(e.overlay); persist(); return false; },
        onRemoved: function (e) { delete reg[e.overlay.id]; persist(); return false; },
        onRightClick: function (e) { chart.removeOverlay({ id: e.overlay.id }); return true; }
      };
    }

    loadSaved().forEach(function (o) {
      try {
        reg[o.id] = o;
        const cfg = handlers();
        cfg.id = o.id;
        cfg.name = o.name;
        cfg.points = o.points;
        chart.createOverlay(cfg);
      } catch (e) {}
    });

    document.querySelectorAll('.tb[data-ov]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        const cfg = handlers();
        cfg.name = btn.getAttribute('data-ov');
        cfg.id = 'o' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        chart.createOverlay(cfg);
      });
    });
    document.getElementById('clear').addEventListener('click', function () {
      chart.removeOverlay();
      Object.keys(reg).forEach(function (k) { delete reg[k]; });
      persist();
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
    "__CODE__": json.dumps(code),
}
for k, v in replacements.items():
    html = html.replace(k, v)

components.html(html, height=height + 6, scrolling=False)
st.caption(
    "資料來源：日K 以上為 FinMind；分K 依側邊欄選擇（Yahoo Finance 或 FinMind）。成交量單位為張。"
    "畫線工具：點上方按鈕後在圖上點選位置即可；線依股票代號保存在這個瀏覽器，切換週期仍在，右鍵點線可刪除。"
)
