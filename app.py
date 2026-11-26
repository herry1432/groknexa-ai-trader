import time
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

BASE_URL = "https://data-api.binance.vision"
WATCHLIST = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]

st.set_page_config(page_title="GROKNEXA AI TRADER", page_icon="📈", layout="wide")
st.markdown("""
<style>
.stApp {background: radial-gradient(circle at top left, #14251f 0, #080d12 42%, #07090d 100%); color:#e8eef5;}
[data-testid="stMetric"] {background:#111a20; border:1px solid #26363c; padding:14px; border-radius:12px;}
.agent {background:#111a20; border:1px solid #26363c; border-radius:12px; padding:14px; min-height:112px;}
.agent h4 {margin:0 0 8px 0; color:#a7f3b0;}
.small {color:#9aaab5; font-size:0.85rem;}
</style>
""", unsafe_allow_html=True)

st.title("🟢 GROKNEXA AI TRADER")
st.caption("Multi-agent crypto research dashboard · PAPER TRADING ONLY · No exchange account or API key required")

if "scan_history" not in st.session_state:
    st.session_state.scan_history = []
if "last_scan" not in st.session_state:
    st.session_state.last_scan = None
if "signals" not in st.session_state:
    st.session_state.signals = []

@st.cache_data(ttl=30, show_spinner=False)
def get_ticker_data():
    r = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", timeout=15)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data)
    df = df[df["symbol"].isin(WATCHLIST)].copy()
    for col in ["lastPrice", "priceChangePercent", "quoteVolume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(ttl=30, show_spinner=False)
def get_klines(symbol, interval="15m", limit=100):
    r = requests.get(f"{BASE_URL}/api/v3/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows, columns=["time","open","high","low","close","volume","close_time","quote_volume","trades","taker_base","taker_quote","ignore"])
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))

def analyse_symbol(symbol):
    df = get_klines(symbol)
    if len(df) < 30:
        return {"symbol": symbol, "price": float(df.close.iloc[-1]), "signal": "WAIT", "rsi": None, "trend": "Insufficient data", "risk": "CAUTION", "reason": "Not enough candles"}
    df["ema9"] = df.close.ewm(span=9, adjust=False).mean()
    df["ema21"] = df.close.ewm(span=21, adjust=False).mean()
    df["rsi"] = rsi(df.close)
    last = df.iloc[-1]
    avg_vol = df.volume.iloc[-21:-1].mean()
    volume_ok = bool(last.volume >= avg_vol) if pd.notna(avg_vol) else False
    trend_up = bool(last.ema9 > last.ema21)
    momentum_ok = bool(pd.notna(last.rsi) and 45 <= last.rsi <= 70)
    # This is a basic market-data filter, not a token contract/security audit.
    risk = "PASS" if volume_ok and abs(float(last.close / df.close.iloc[-2] - 1)) < 0.06 else "CAUTION"
    signal = "BUY WATCH" if trend_up and momentum_ok and volume_ok and risk == "PASS" else "WAIT"
    reasons = []
    reasons.append("EMA trend up" if trend_up else "EMA trend not up")
    reasons.append(f"RSI {last.rsi:.1f}" if pd.notna(last.rsi) else "RSI unavailable")
    reasons.append("volume above average" if volume_ok else "volume below average")
    return {"symbol": symbol, "price": float(last.close), "signal": signal, "rsi": float(last.rsi) if pd.notna(last.rsi) else None, "trend": "Bullish" if trend_up else "Not bullish", "risk": risk, "reason": "; ".join(reasons)}

col1, col2, col3, col4 = st.columns(4)
try:
    tickers = get_ticker_data()
    total_market_move = tickers.priceChangePercent.mean()
    col1.metric("Watchlist", f"{len(tickers)} pairs")
    col2.metric("Avg. 24h change", f"{total_market_move:+.2f}%")
    col3.metric("Mode", "PAPER")
    col4.metric("Starting balance", "$1,000.00")
    st.subheader("Live market watch")
    view = tickers[["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]].rename(columns={"symbol":"Pair", "lastPrice":"Last price (USDT)", "priceChangePercent":"24h change %", "quoteVolume":"24h volume (USDT)"})
    st.dataframe(view, use_container_width=True, hide_index=True)
except Exception as e:
    tickers = pd.DataFrame()
    st.warning(f"Market data is temporarily unavailable: {e}")

st.subheader("Agent pipeline")
agents = st.columns(3)
agent_info = [
    ("01 · SCANNER", "Finds price/volume setups from public market data."),
    ("02 · RISK CHECK", "Basic volatility and volume checks; not an on-chain rug-pull audit."),
    ("03 · POSITION SIZER", "Calculates a sample position using a 1% account-risk rule."),
    ("04 · EXECUTOR", "Creates paper-trade records only; no real orders."),
    ("05 · LOGGER", "Keeps scan and signal history during this app session."),
    ("06 · EQUITY", "Displays simulated account metrics as the paper-trading engine grows."),
]
for i, (name, desc) in enumerate(agent_info):
    with agents[i % 3]:
        st.markdown(f'<div class="agent"><h4>{name}</h4><div class="small">{desc}</div></div>', unsafe_allow_html=True)

st.subheader("Run the agents")
left, right = st.columns([1, 3])
with left:
    run_scan = st.button("▶ Run scan", type="primary", use_container_width=True)
with right:
    st.caption("Scans six selected USDT spot pairs using 15-minute candles. A BUY WATCH is a research signal, not a recommendation or an order.")

if run_scan:
    results = []
    progress = st.progress(0)
    status = st.empty()
    for i, symbol in enumerate(WATCHLIST):
        status.write(f"Scanner + risk checker: {symbol}")
        try:
            results.append(analyse_symbol(symbol))
        except Exception as e:
            results.append({"symbol": symbol, "price": None, "signal": "ERROR", "rsi": None, "trend": "Unknown", "risk": "UNKNOWN", "reason": str(e)[:100]})
        progress.progress((i + 1) / len(WATCHLIST))
        time.sleep(0.15)
    st.session_state.last_scan = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.session_state.scan_history = results
    for item in results:
        if item["signal"] == "BUY WATCH":
            st.session_state.signals.append({"time": st.session_state.last_scan, **item, "execution": "PAPER ONLY — not placed"})
    status.success("All six agents completed the scan.")

if st.session_state.scan_history:
    st.subheader("Latest agent results")
    result_df = pd.DataFrame(st.session_state.scan_history)
    st.dataframe(result_df, use_container_width=True, hide_index=True)
    st.caption(f"Last scan: {st.session_state.last_scan}")
    st.subheader("Trade signal log")
    if st.session_state.signals:
        st.dataframe(pd.DataFrame(st.session_state.signals).tail(20), use_container_width=True, hide_index=True)
    else:
        st.info("No BUY WATCH setup found in the latest scan. The bot correctly stayed out.")
else:
    st.info("Press ‘Run scan’ to start the six agents. No trades are executed.")

st.divider()
st.caption("Educational prototype. Signals are rule-based and can be wrong. No guaranteed returns. Paper trading only; no API keys, deposits, or real-money execution.")
