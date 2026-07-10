# Nifty50 Pro Trader

A comprehensive Streamlit-based trading dashboard for Nifty 50, featuring live charts, pattern detection, Option Interest (OI) analysis, Greeks, and paper trading.

## Features

- **Live Charts**: Real-time Nifty 50 candlestick charts with EMA overlays, support/resistance levels, and linear regression trends.
- **Pattern Detection**: Automated detection of various candlestick and technical patterns with entry, stop-loss, and target recommendations.
- **OI Analysis**: Deep dive into Option Interest, including PCR (Put-Call Ratio), OI change trends across multiple timeframes, and support/resistance based on max OI.
- **Greeks Analysis**: Insight into Delta, Gamma, and Theta for ATM and near-the-money options to gauge market sentiment and risk.
- **Paper Trading**: Automated buy-side option trading simulation. Automatically takes trades based on detected patterns and tracks their performance in option premium terms.
- **Best Trade Recommendation**: A proprietary scoring system that combines pattern confidence, OI bias, and Greeks to suggest the highest probability trade.

## Project Structure

- `app.py`: The main Streamlit application and UI layout.
- `modules/`:
    - `angelone_client.py`: Handles connection to AngelOne API and data fetching (Candles, LTP, Option Chain).
    - `pattern_detector.py`: Contains logic for detecting technical patterns.
    - `oi_analyzer.py`: Processes and analyzes Option Interest data.
    - `greeks_analyzer.py`: Calculates and analyzes option Greeks.
    - `paper_trader.py`: Manages paper trade execution, tracking, and P&L calculation.
    - `nse_client.py`: (Optional/Fallback) NSE data client.

## Setup and Installation

1. Clone the repository.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your AngelOne API credentials in Streamlit secrets (`.streamlit/secrets.toml`):
   ```toml
   [angel_one]
   api_key = "your_api_key"
   client_id = "your_client_code"
   mpin = "your_mpin"
   totp_secret = "your_totp_base32_secret"
   ```
4. Run the application:
   ```bash
   streamlit run app.py
   ```

## Usage

- **Auto-refresh**: Use the toggle at the bottom to enable 5-second auto-refresh for live market tracking.
- **Timeframes**: Switch between different chart timeframes (1m to 60m).
- **Tabs**: Explore different analysis sections like Strike Volume, OI Trend, and Greeks.
- **Paper Trading**: Monitor automated trades in the "Paper Trade" tab.

## Disclaimer

This tool is for educational and simulation purposes only. Trading in financial markets involves risk. Always consult with a qualified financial advisor before making any investment decisions.
