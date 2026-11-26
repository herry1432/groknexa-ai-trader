# GROKNEXA AI TRADER — Starter MVP

A free, paper-trading-only multi-agent crypto market dashboard.

## Included in this first version
- Public Binance Spot market data (no API key required)
- Six watched USDT pairs: BTC, ETH, BNB, SOL, XRP, DOGE
- Six logical agents: scanner, basic risk checker, position sizer concept, paper executor boundary, logger, equity manager concept
- EMA 9/21 + RSI + relative-volume research signal
- Streamlit dashboard and scan log

## Safety limits
- No exchange credentials are requested or stored.
- No real buy/sell orders can be placed.
- The risk checker is not an on-chain token audit and cannot prove a token is safe.
- A BUY WATCH is not a recommendation or a guarantee of profit.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL shown by Streamlit (usually http://localhost:8501).

## Free deployment
Push this folder to a GitHub repository, then deploy `app.py` using Streamlit Community Cloud. See https://docs.streamlit.io/deploy/streamlit-community-cloud.

Note: Streamlit Community Cloud is a free app-hosting option, but availability, resource limits, and terms can change. This app is a prototype; do not use it as unattended financial software.
