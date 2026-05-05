# Alpaca Paper Trading System (24/7 Crypto + Stocks)

A professional-grade, autonomous trading system that uses AI (OpenAI or local LFM) and technical analysis to trade a dynamic universe of US Stocks and Crypto.

## 🚀 Key Features
- **24/7/365 Crypto Trading**: Seamlessly switches to Crypto-only when US markets are closed.
- **AI-Driven Decisions**: Uses GPT-4o-mini by default, or a local LFM provider when `USEGPT=FALSE`.
- **Dynamic Asset Universe**: Automatically scores and selects the top 25 balance-aware opportunity assets every hour.
- **Real-Time Dashboard**: Premium web UI (FastAPI) showing live positions, signals, and account equity with 1s updates.
- **Professional Risk Management**:
  - **Risk-Capped Sizing**: Caps submitted quantity by deterministic risk sizing and the default $200 per-trade limit.
  - **Short-Aware Exits**: Long positions exit with sell orders; short positions buy to cover when short selling is enabled.
  - **Hard TP/SL Exits**: Stored targets and stops are merged into exit checks before the LLM is consulted.
  - **Daily Risk Pauses**: Reconciliation pauses new entries on daily loss, portfolio drawdown, or max trades/day breaches.
  - **Daily Liquidity Checks**: Intraday bar volume is rolled up to daily volume; crypto uses notional dollar volume.
  - **Market Close Buffer**: Stops stock entries 15 minutes before US market close.
  - **Deep Reconciliation**: Automatically syncs local state with Alpaca exchange state every 10 mins.

## 🛠 Setup & Installation

1. **Clone the repository**
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Environment**:
   Create a `.env` file in the root:
   ```env
   ALPACA_API_KEY=your_key
   ALPACA_API_SECRET=your_secret
   OPENAI_API_KEY=your_openai_key
   TRADING_MODE=PAPER
   USEGPT=TRUE
   ```

   `OPENAI_API_KEY` is required only when `USEGPT=TRUE`. Set `USEGPT=FALSE` to run the local LFM provider without an OpenAI key.
   The local LFM path installs `torch`, `transformers`, and `accelerate` from `requirements.txt`; GPU-specific Torch wheels may still need the install command recommended for your CUDA version.

## 📈 Running the System

Start the main service:
```bash
python main.py
```
Access the dashboard:
[http://localhost:8000](http://localhost:8000)

## Optional LLM Latency Benchmark

To compare local Liquid LFM prompt-to-response latency against OpenAI GPT on the same entry prompt:

```powershell
$env:RUN_LLM_LATENCY_TEST="1"
python -m pytest tests\test_llm_latency.py -s -p no:cacheprovider
```

The benchmark reads `OPENAI_API_KEY` from the process environment or `.env`. It reports local model load time separately from prompt-to-response latency.

## 📁 Project Structure
- `/app/loops`: Autonomous threads for entry, monitoring, and reconciliation.
- `/app/llm`: OpenAI integration and prompt engineering.
- `/app/dashboard`: FastAPI server and HTML interface.
- `/data`: CSV logs for signals and order history.
- `/config`: Strategy parameters and risk limits.

## ⚠️ Disclaimer
This software is for educational purposes. Always test thoroughly in PAPER mode before using real capital. The authors are not responsible for any financial losses.
