# Alpaca Trading System

An object-oriented, thread-safe trading service that uses **Alpaca** for market data and trade execution, with an **LLM (GPT-4o-mini)** constrained decision layer.

## 🚀 Overview

The system is designed for **Paper Trading** by default, ensuring safety and predictability. It follows a "Deterministic First, LLM Second" philosophy:
1.  **Deterministic Calculators**: All indicators, risk metrics, and position sizes are calculated using standard libraries (Pandas/NumPy).
2.  **Constrained Decision Layer**: The LLM only receives compact summaries of these metrics to make a final action choice (BUY, SELL, or SKIP).
3.  **Safety Gate**: Every signal is validated against account limits and risk parameters before submission.

## 🏗️ Architecture

The system runs 5 independent background loops:
*   **AssetRefreshLoop**: Scores the universe and selects the top-20 most liquid/volatile symbols every hour.
*   **EntryOpportunityLoop**: Scans active symbols for entry signals every 2 minutes.
*   **OpenOrderMonitorLoop**: Monitors open orders and manages exits (Profit Target / Stop Loss) every 2 minutes.
*   **ReconciliationLoop**: Syncs local CSV state with Alpaca broker reality every 10 minutes.
*   **HeartbeatLoop**: Logs service health every minute.

## ⚙️ Configuration

### 1. Environment Variables (`.env`)
Only 4 variables are allowed, adhering to strict security constraints:
```env
ALPACA_API_KEY=your_alpaca_key
ALPACA_API_SECRET=your_alpaca_secret
OPENAI_API_KEY=your_openai_key
TRADING_MODE=PAPER
```
*Note: `TRADING_MODE` must be either `PAPER` or `REAL`.*

### 2. Strategy & Risk Limits
All strategy-specific parameters are version-controlled in the `config/` directory:
*   `config/risk_limits.py`: Max risk per trade, max exposure, drawdown limits.
*   `config/strategy_params.py`: Indicator periods, ATR multipliers for SL/TP.
*   `config/settings.py`: Loop intervals, stock universe, and storage paths.

## 📁 Storage
All trade activity is recorded in local CSV files under the `data/` directory:
*   `open_orders.csv`: Currently active positions.
*   `past_orders.csv`: Completed trades history.
*   `signal_logs.csv`: Every LLM decision and validation result.

## 🛠️ Installation & Running

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure `.env`**:
    Copy the example and add your keys.

3.  **Run Tests**:
    ```bash
    pytest tests/ -v
    ```

4.  **Start the Service**:
    ```bash
    python main.py
    ```

5.  **Access the Dashboard**:
    Open [http://localhost:8000](http://localhost:8000) in your browser to view live status and signal history.

## 📊 Dashboard
The system includes a premium, glassmorphism-style dashboard that provides:
*   **Live Portfolio Stats**: Equity, buying power, and open orders.
*   **Signal History**: Real-time view of LLM decisions and validator results.
*   **Active Assets**: Current symbols being monitored by the entry scanner.
*   **System Health**: Uptime and pause/reconcile status.
The system includes 45+ unit and integration tests covering:
*   Thread-safe state management (`AppState`).
*   Atomic CSV operations with file locking.
*   Alpaca API interaction mocking.
*   Technical indicator accuracy.
*   Full trade pipeline integration.

## ⚠️ Safety Warning
This system defaults to **PAPER** mode. Real trading involves significant risk. Always verify performance in a paper environment for an extended period before switching to `REAL` mode.
