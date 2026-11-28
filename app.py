import time
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

BASE_URL = "https://data-api.binance.vision"
WATCHLIST = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
STARTING_BALANCE = 1000.0

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

# Session state: paper trades remain available while this app session is active.
defaults = {
    "scan_history": [],
    "last_scan": None,
    "signals": [],
    "cash_balance": STARTING_BALANCE,
    "open_positions": [],
    "closed_trades": [],
    "next_trade_id": 1,
    "auto_trading_enabled": False,
    "daily_date": None,
    "daily_start_equity": None,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value.copy() if isinstance(value, list) else value


@st.cache_data(ttl=30, show_spinner=False)
def get_ticker_data():
    response = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", timeout=15)
    response.raise_for_status()
    df = pd.DataFrame(response.json())
    df = df[df["symbol"].isin(WATCHLIST)].copy()
    for col in ["lastPrice", "priceChangePercent", "quoteVolume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_klines(symbol, interval="15m", limit=100):
    response = requests.get(
        f"{BASE_URL}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=15,
    )
    response.raise_for_status()
    rows = response.json()
    columns = [
        "time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=columns)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def analyse_symbol(symbol):
    df = get_klines(symbol)
    if len(df) < 30:
        price = float(df.close.iloc[-1]) if not df.empty else None
        return {
            "symbol": symbol, "price": price, "signal": "WAIT", "rsi": None,
            "trend": "Insufficient data", "risk": "CAUTION",
            "reason": "Not enough candles",
        }

    df["ema9"] = df.close.ewm(span=9, adjust=False).mean()
    df["ema21"] = df.close.ewm(span=21, adjust=False).mean()
    df["rsi"] = rsi(df.close)
    last = df.iloc[-1]
    average_volume = df.volume.iloc[-21:-1].mean()
    volume_ok = bool(last.volume >= average_volume) if pd.notna(average_volume) else False
    trend_up = bool(last.ema9 > last.ema21)
    momentum_ok = bool(pd.notna(last.rsi) and 45 <= last.rsi <= 70)
    one_candle_move = abs(float(last.close / df.close.iloc[-2] - 1))
    risk = "PASS" if volume_ok and one_candle_move < 0.06 else "CAUTION"
    signal = "BUY WATCH" if trend_up and momentum_ok and volume_ok and risk == "PASS" else "WAIT"

    reasons = [
        "EMA trend up" if trend_up else "EMA trend not up",
        f"RSI {last.rsi:.1f}" if pd.notna(last.rsi) else "RSI unavailable",
        "volume above average" if volume_ok else "volume below average",
    ]
    return {
        "symbol": symbol,
        "price": float(last.close),
        "signal": signal,
        "rsi": float(last.rsi) if pd.notna(last.rsi) else None,
        "trend": "Bullish" if trend_up else "Not bullish",
        "risk": risk,
        "reason": "; ".join(reasons),
    }


# Market data
st.subheader("Live market watch")
try:
    tickers = get_ticker_data()
    if tickers.empty:
        raise ValueError("No watchlist market data returned.")
    price_map = dict(zip(tickers["symbol"], tickers["lastPrice"]))
    total_market_move = tickers["priceChangePercent"].mean()
    current_prices = {symbol: float(price_map[symbol]) for symbol in WATCHLIST if symbol in price_map and pd.notna(price_map[symbol])}
    market_ok = True
except Exception as error:
    tickers = pd.DataFrame()
    current_prices = {}
    market_ok = False
    st.warning(f"Market data is temporarily unavailable: {error}")

# Process stop-loss / take-profit exits using the latest available ticker prices.
if market_ok:
    still_open = []
    for position in st.session_state.open_positions:
        current_price = current_prices.get(position["symbol"])
        if current_price is None:
            still_open.append(position)
            continue

        position["mark_price"] = current_price
        exit_reason = None
        if current_price <= position["stop_loss"]:
            exit_reason = "STOP LOSS"
        elif current_price >= position["take_profit"]:
            exit_reason = "TAKE PROFIT"

        if exit_reason:
            pnl = (current_price - position["entry_price"]) * position["quantity"]
            proceeds = position["quantity"] * current_price
            st.session_state.cash_balance += proceeds
            st.session_state.closed_trades.append({
                **position,
                "exit_price": current_price,
                "pnl_usdt": pnl,
                "exit_reason": exit_reason,
                "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            })
        else:
            still_open.append(position)
    st.session_state.open_positions = still_open

# Account metrics
open_market_value = sum(
    p["quantity"] * current_prices.get(p["symbol"], p["mark_price"])
    for p in st.session_state.open_positions
)
unrealized_pnl = sum(
    (current_prices.get(p["symbol"], p["mark_price"]) - p["entry_price"]) * p["quantity"]
    for p in st.session_state.open_positions
)
realized_pnl = sum(t["pnl_usdt"] for t in st.session_state.closed_trades)
equity = st.session_state.cash_balance + open_market_value

# Daily risk limit is measured against the account equity at the start of each UTC day.
today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
if st.session_state.daily_date != today_utc:
    st.session_state.daily_date = today_utc
    st.session_state.daily_start_equity = equity

daily_closed_pnl = sum(
    t["pnl_usdt"] for t in st.session_state.closed_trades
    if str(t.get("closed_at", "")).startswith(today_utc)
)
daily_open_pnl = sum(
    (current_prices.get(p["symbol"], p["mark_price"]) - p["entry_price"]) * p["quantity"]
    for p in st.session_state.open_positions
)
daily_pnl = daily_closed_pnl + daily_open_pnl
daily_loss_limit = float(st.session_state.daily_start_equity or STARTING_BALANCE) * 0.03
daily_loss_locked = daily_pnl <= -daily_loss_limit

col1, col2, col3, col4 = st.columns(4)
col1.metric("Watchlist", f"{len(current_prices)} pairs")
if market_ok:
    col2.metric("Avg. 24h change", f"{total_market_move:+.2f}%")
else:
    col2.metric("Avg. 24h change", "Unavailable")
col3.metric("Mode", "PAPER")
col4.metric("Account equity", f"${equity:,.2f}", f"{equity - STARTING_BALANCE:+,.2f} USDT")

if market_ok:
    market_view = tickers[
        ["symbol", "lastPrice", "priceChangePercent", "quoteVolume"]
    ].rename(columns={
        "symbol": "Pair",
        "lastPrice": "Last price (USDT)",
        "priceChangePercent": "24h change %",
        "quoteVolume": "24h volume (USDT)",
    })
    st.dataframe(market_view, use_container_width=True, hide_index=True)

st.subheader("Account overview")
a, b, c, d = st.columns(4)
a.metric("Available cash", f"${st.session_state.cash_balance:,.2f}")
b.metric("Open positions", str(len(st.session_state.open_positions)))
c.metric("Unrealized P&L", f"${unrealized_pnl:+,.2f}")
d.metric("Realized P&L", f"${realized_pnl:+,.2f}")

st.subheader("Agent pipeline")
agents = st.columns(3)
agent_info = [
    ("01 · SCANNER", "Finds price and volume setups from public market data."),
    ("02 · RISK CHECK", "Basic volatility and volume checks; not an on-chain security audit."),
    ("03 · POSITION SIZER", "Sizes a sample position using a 1% account-risk budget."),
    ("04 · EXECUTOR", "Opens and closes simulated paper positions only."),
    ("05 · LOGGER", "Records paper trades during this app session."),
    ("06 · EQUITY", "Tracks simulated cash, open positions and profit/loss."),
]
for index, (name, description) in enumerate(agent_info):
    with agents[index % 3]:
        st.markdown(
            f'<div class="agent"><h4>{name}</h4><div class="small">{description}</div></div>',
            unsafe_allow_html=True,
        )

# Auto-test controls and safety status
st.divider()
st.header("🛡️ Auto Test & Safety Controls")
st.caption("Auto mode only opens virtual paper trades after a scan. It does not run in the background.")
auto_button_label = "🟢 TURN AUTO PAPER TRADING OFF" if st.session_state.auto_trading_enabled else "⚪ TURN AUTO PAPER TRADING ON"
if st.button(auto_button_label, key="auto_paper_trading_toggle", use_container_width=True):
    st.session_state.auto_trading_enabled = not st.session_state.auto_trading_enabled
    st.rerun()
safe1, safe2, safe3, safe4 = st.columns(4)
safe1.metric("Risk per trade", "1% max")
safe2.metric("Daily loss limit", f"${daily_loss_limit:,.2f}")
safe3.metric("Daily P&L", f"${daily_pnl:+,.2f}")
safe4.metric("Auto mode", "ON" if st.session_state.auto_trading_enabled else "OFF")
if daily_loss_locked:
    st.error("DAILY LOSS LIMIT REACHED — all new paper trades are locked until the next UTC day.")
else:
    st.success("Safety checks active. Real exchange orders are disabled.")

# Scanner
st.subheader("Run the agents")
left, right = st.columns([1, 3])
with left:
    run_scan = st.button("▶ Run scan", type="primary", use_container_width=True)
with right:
    st.caption("Scans six selected USDT spot pairs using 15-minute candles. BUY WATCH is a research signal, not a recommendation.")

if run_scan:
    results = []
    progress = st.progress(0)
    status = st.empty()
    for index, symbol in enumerate(WATCHLIST):
        status.write(f"Scanner + risk checker: {symbol}")
        try:
            results.append(analyse_symbol(symbol))
        except Exception as error:
            results.append({
                "symbol": symbol, "price": None, "signal": "ERROR", "rsi": None,
                "trend": "Unknown", "risk": "UNKNOWN", "reason": str(error)[:120],
            })
        progress.progress((index + 1) / len(WATCHLIST))
        time.sleep(0.1)

    st.session_state.last_scan = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.session_state.scan_history = results
    for item in results:
        if item["signal"] == "BUY WATCH":
            st.session_state.signals.append({
                "time": st.session_state.last_scan,
                **item,
                "execution": "BUY WATCH signal",
            })

    # Auto test: paper-only execution with fixed 1% risk, 2% stop and 4% target.
    auto_opened = []
    if st.session_state.auto_trading_enabled:
        current_equity = st.session_state.cash_balance + sum(
            p["quantity"] * current_prices.get(p["symbol"], p["mark_price"])
            for p in st.session_state.open_positions
        )
        today_closed = sum(
            t["pnl_usdt"] for t in st.session_state.closed_trades
            if str(t.get("closed_at", "")).startswith(today_utc)
        )
        today_open = sum(
            (current_prices.get(p["symbol"], p["mark_price"]) - p["entry_price"]) * p["quantity"]
            for p in st.session_state.open_positions
        )
        if today_closed + today_open <= -daily_loss_limit:
            status.warning("Auto test blocked: daily loss limit reached.")
        else:
            for item in results:
                if item["signal"] != "BUY WATCH" or item["symbol"] not in current_prices:
                    continue
                if len(st.session_state.open_positions) >= 2:
                    break
                if any(p["symbol"] == item["symbol"] for p in st.session_state.open_positions):
                    continue
                entry = current_prices[item["symbol"]]
                risk_budget = current_equity * 0.01
                stop_price = entry * 0.98
                target_price = entry * 1.04
                quantity_by_risk = risk_budget / (entry - stop_price)
                quantity_by_cash = st.session_state.cash_balance / entry
                quantity = min(quantity_by_risk, quantity_by_cash)
                notional = quantity * entry
                if quantity <= 0 or notional < 1:
                    continue
                trade = {
                    "trade_id": st.session_state.next_trade_id,
                    "symbol": item["symbol"],
                    "side": "LONG",
                    "entry_price": entry,
                    "mark_price": entry,
                    "quantity": quantity,
                    "notional_usdt": notional,
                    "stop_loss": stop_price,
                    "take_profit": target_price,
                    "risk_budget_usdt": risk_budget,
                    "opened_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                }
                st.session_state.cash_balance -= notional
                st.session_state.open_positions.append(trade)
                st.session_state.next_trade_id += 1
                current_equity -= 0  # equity is unchanged by opening a position
                auto_opened.append(item["symbol"])
    if st.session_state.auto_trading_enabled:
        status.success(
            "Scan completed. Auto paper trades opened: " + (", ".join(auto_opened) if auto_opened else "none")
        )
    else:
        status.success("Scan completed.")

if st.session_state.scan_history:
    st.subheader("Latest agent results")
    st.dataframe(pd.DataFrame(st.session_state.scan_history), use_container_width=True, hide_index=True)
    st.caption(f"Last scan: {st.session_state.last_scan}")
    st.subheader("Research signal log")
    if st.session_state.signals:
        st.dataframe(pd.DataFrame(st.session_state.signals).tail(20), use_container_width=True, hide_index=True)
    else:
        st.info("No BUY WATCH setup found in the latest scan. The bot stayed out.")
else:
    st.info("Press Run scan to start the six market-analysis checks.")

# Paper trading controls
st.divider()
st.header("🧪 Paper trading simulator")
st.caption("Long-only simulation. Orders are virtual and are never sent to Binance.")

if not market_ok:
    st.warning("Trading controls are paused until live market prices are available.")
else:
    with st.form("open_paper_trade_form"):
        st.subheader("Open a virtual position")
        form_col1, form_col2, form_col3, form_col4 = st.columns(4)
        with form_col1:
            selected_symbol = st.selectbox("Trading pair", WATCHLIST)
        with form_col2:
            risk_percent = st.number_input("Risk per trade (%)", min_value=0.25, max_value=1.0, value=1.0, step=0.25)
        with form_col3:
            stop_percent = st.number_input("Stop Loss distance (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
        with form_col4:
            target_percent = st.number_input("Take Profit distance (%)", min_value=0.5, max_value=20.0, value=4.0, step=0.5)
        submit_trade = st.form_submit_button("＋ Open paper BUY", type="primary", use_container_width=True)

    if submit_trade:
        entry = current_prices.get(selected_symbol)
        if daily_loss_locked:
            st.error("Daily loss limit reached. New paper trades are locked until the next UTC day.")
        elif entry is None or entry <= 0:
            st.error("A valid live price is not available for this pair.")
        elif any(p["symbol"] == selected_symbol for p in st.session_state.open_positions):
            st.error("There is already an open paper position for this pair.")
        else:
            risk_budget = equity * (risk_percent / 100.0)
            stop_price = entry * (1 - stop_percent / 100.0)
            target_price = entry * (1 + target_percent / 100.0)
            risk_per_unit = entry - stop_price
            quantity_by_risk = risk_budget / risk_per_unit
            quantity_by_cash = st.session_state.cash_balance / entry
            quantity = min(quantity_by_risk, quantity_by_cash)
            notional = quantity * entry

            if quantity <= 0 or notional < 1:
                st.error("Not enough available paper cash to open this position.")
            else:
                trade = {
                    "trade_id": st.session_state.next_trade_id,
                    "symbol": selected_symbol,
                    "side": "LONG",
                    "entry_price": entry,
                    "mark_price": entry,
                    "quantity": quantity,
                    "notional_usdt": notional,
                    "stop_loss": stop_price,
                    "take_profit": target_price,
                    "risk_budget_usdt": risk_budget,
                    "opened_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                }
                st.session_state.cash_balance -= notional
                st.session_state.open_positions.append(trade)
                st.session_state.next_trade_id += 1
                st.success(
                    f"Paper position opened: {selected_symbol} at {entry:.8g} USDT. "
                    f"Position size: ${notional:,.2f}; estimated risk budget: ${risk_budget:,.2f}."
                )

# Open positions and manual close
st.subheader("Open paper positions")
if st.session_state.open_positions:
    open_rows = []
    for position in st.session_state.open_positions:
        mark = current_prices.get(position["symbol"], position["mark_price"])
        pnl = (mark - position["entry_price"]) * position["quantity"]
        open_rows.append({
            "ID": position["trade_id"],
            "Pair": position["symbol"],
            "Entry": position["entry_price"],
            "Current": mark,
            "Quantity": position["quantity"],
            "Position value": position["quantity"] * mark,
            "Stop Loss": position["stop_loss"],
            "Take Profit": position["take_profit"],
            "Unrealized P&L": pnl,
        })
    st.dataframe(pd.DataFrame(open_rows), use_container_width=True, hide_index=True)

    ids = [p["trade_id"] for p in st.session_state.open_positions]
    with st.form("close_paper_trade_form"):
        selected_trade_id = st.selectbox("Select position to close", ids, format_func=lambda trade_id: next(
            f'#{p["trade_id"]} · {p["symbol"]}' for p in st.session_state.open_positions if p["trade_id"] == trade_id
        ))
        close_trade = st.form_submit_button("Close selected paper position")
    if close_trade:
        position = next(p for p in st.session_state.open_positions if p["trade_id"] == selected_trade_id)
        exit_price = current_prices.get(position["symbol"], position["mark_price"])
        pnl = (exit_price - position["entry_price"]) * position["quantity"]
        st.session_state.cash_balance += position["quantity"] * exit_price
        st.session_state.closed_trades.append({
            **position,
            "exit_price": exit_price,
            "pnl_usdt": pnl,
            "exit_reason": "MANUAL CLOSE",
            "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        })
        st.session_state.open_positions = [
            p for p in st.session_state.open_positions if p["trade_id"] != selected_trade_id
        ]
        st.success(f"Paper position closed. P&L: {pnl:+.2f} USDT")
        st.rerun()
else:
    st.info("No open paper positions.")

st.subheader("Closed trade history")
if st.session_state.closed_trades:
    history = pd.DataFrame(st.session_state.closed_trades)
    display_columns = [
        "trade_id", "symbol", "entry_price", "exit_price", "quantity",
        "pnl_usdt", "exit_reason", "opened_at", "closed_at",
    ]
    st.dataframe(history[display_columns].sort_values("trade_id", ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("Closed paper trades will appear here.")

st.caption(
    "Important: Educational simulator only. Signals can be wrong; no guaranteed returns. "
    "Paper trades are long-only, use public market prices, and are stored only for the current app session. "
    "Auto mode runs only when you press Run scan; it is not 24/7. They are not exchange orders and do not include trading fees, slippage or tax."
)
