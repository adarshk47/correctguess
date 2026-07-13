"""
Nifty50 Pro Trader - Streamlit App
Live chart, pattern detection, OI analysis, greeks, paper trading.
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import time

st.set_page_config(
    page_title="Nifty50 Pro Trader",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none; }
    .main { background-color: #0e1117; }
    .block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; }
    .metric-card {
        background: #1e2130;
        border-radius: 8px;
        padding: 12px 16px;
        text-align: center;
        border: 1px solid #2d3250;
    }
    .metric-label { font-size: 11px; color: #888; text-transform: uppercase; }
    .metric-value { font-size: 22px; font-weight: bold; color: #fff; }
    .metric-sub { font-size: 12px; color: #aaa; }
</style>
""", unsafe_allow_html=True)

IST = pytz.timezone("Asia/Kolkata")

# ── Import modules ─────────────────────────────────────────────────────────────
try:
    from modules.angelone_client import (
        fetch_candle_data, fetch_options_chain, fetch_ltp, fetch_ltp_info,
        get_next_weekly_expiry, get_expiry_string, get_expiry_countdown,
        is_market_open, get_atm_strike, get_strike_range, INTERVAL_MAP,
        is_connected, get_client, get_last_error, get_options_diagnostics,
    )
    from modules.pattern_detector import detect_all_patterns
    from modules.oi_analyzer import (
        compute_delta_oi, build_oi_timeframe_table,
        get_oi_arrow_annotations, build_strike_volume_table,
        get_most_traded_strikes, get_oi_snapshot, store_oi_snapshot,
        analyze_oi_trend, oi_support_resistance,
    )
    from modules.greeks_analyzer import analyze_greeks, build_greeks_trend_table, get_gamma_exposure
    from modules.paper_trader import (
        is_market_open as paper_market_open,
        add_paper_trade, update_paper_trades, get_trades_df,
        get_paper_trade_summary, should_add_new_trade, clear_all_trades,
        get_atm_option_quote,
    )
    MODULES_OK = True
except Exception as e:
    MODULES_OK = False
    st.error(f"Module import error: {e}")

# ── Autorefresh ──────────────────────────────────────────────────────────────
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# ── Session state init ─────────────────────────────────────────────────────────
if "chart_tf" not in st.session_state: st.session_state["chart_tf"] = 5
if "recommendation_history" not in st.session_state: st.session_state["recommendation_history"] = []

def filter_to_recent_data(df, days=2):
    if df is None or df.empty: return df
    ts = pd.to_datetime(df["timestamp"])
    last_dates = sorted(ts.dt.date.unique())[-days:]
    return df[ts.dt.date.isin(last_dates)].reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────────────────────────────────────

def render_header(ltp, spot_prev, connected):
    now = datetime.now(IST)
    expiry_dt = get_next_weekly_expiry()
    expiry_str = get_expiry_string(expiry_dt)
    countdown = get_expiry_countdown(expiry_dt)
    market_open = is_market_open()
    
    status_html = '<span style="color:#00ff88;">🟢 LIVE</span>' if connected else '<span style="color:#ff5555;">🔴 OFFLINE</span>'
    st.markdown(f'<div style="text-align:right; font-size:12px;">{status_html}</div>', unsafe_allow_html=True)
    
    chg = ltp - spot_prev if ltp and spot_prev else 0
    chg_pct = chg / spot_prev * 100 if spot_prev else 0
    chg_color = "#00ff88" if chg >= 0 else "#ff4444"
    chg_sign = "+" if chg >= 0 else ""
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="metric-label">NIFTY 50</div><div class="metric-value" style="color:{chg_color};">{ltp:,.2f}</div><div class="metric-sub" style="color:{chg_color};">{chg_sign}{chg:.2f} ({chg_sign}{chg_pct:.2f}%)</div></div>', unsafe_allow_html=True)
    with col2:
        time_val = now.strftime('%H:%M:%S') if market_open else "15:30:00"
        time_label = "IST Time" if market_open else "Market Closed"
        st.markdown(f'<div class="metric-card"><div class="metric-label">{time_label}</div><div class="metric-value">{time_val}</div><div class="metric-sub">{now.strftime("%d %b %Y")}</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Expiry</div><div class="metric-value" style="color:#ffd700;">{expiry_str}</div><div class="metric-sub">{expiry_dt.strftime("%A") if expiry_dt else "---"}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Countdown</div><div class="metric-value" style="color:#ffd700;">{countdown}</div><div class="metric-sub">Settlement</div></div>', unsafe_allow_html=True)
    with col5:
        mkt_status = "🟢 OPEN" if market_open else "🔴 CLOSED"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Status</div><div class="metric-value">{mkt_status}</div><div class="metric-sub">09:15 - 15:30</div></div>', unsafe_allow_html=True)

def build_chart(candle_df, patterns):
    if candle_df is None or candle_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Waiting for market data... (Make sure AngelOne is connected)",
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
            font_color="#fff"
        )
        return fig

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=candle_df["timestamp"], open=candle_df["open"], high=candle_df["high"], low=candle_df["low"], close=candle_df["close"], name="NIFTY"), row=1, col=1)
    
    # EMAs
    ema9 = candle_df["close"].ewm(span=9, adjust=False).mean()
    ema21 = candle_df["close"].ewm(span=21, adjust=False).mean()
    fig.add_trace(go.Scatter(x=candle_df["timestamp"], y=ema9, line=dict(color="#ffaa00", width=1), name="EMA 9"), row=1, col=1)
    fig.add_trace(go.Scatter(x=candle_df["timestamp"], y=ema21, line=dict(color="#33b5ff", width=1), name="EMA 21"), row=1, col=1)

    fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="#ccc", size=10), height=500, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False, hovermode="x unified")
    
    # Remove non-trading hours and weekends
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]), # Hide weekends
            dict(bounds=[15.5, 9.25], pattern="hour"), # Hide 15:30 to 09:15
        ]
    )
    return fig

# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not MODULES_OK: st.stop()

    # Core Data
    ltp_info = fetch_ltp_info()
    ltp, spot_prev = ltp_info["ltp"], ltp_info["close"]
    connected = is_connected()

    # Timeframe selection
    tf_col, _ = st.columns([2, 8])
    with tf_col:
        sel_tf = st.selectbox("Interval", options=[1, 5, 15, 60], format_func=lambda x: f"{x}m", index=1)

    # Data Fetching
    candle_df = fetch_candle_data(sel_tf, 500)
    candle_df = filter_to_recent_data(candle_df, days=2)
    patterns = detect_all_patterns(candle_df) if not candle_df.empty else []
    options_df = fetch_options_chain()

    # UI Layout
    # 1. Chart
    st.plotly_chart(build_chart(candle_df, patterns), use_container_width=True)
    
    # 2. Banner
    render_header(ltp, spot_prev, connected)

    # 3. Tabs
    t1, t2, t3, t4 = st.tabs(["📝 Paper Trade", "📊 OI Analysis", "🔢 Greeks", "📋 Signals"])
    
    with t1:
        st.markdown("#### 📝 Automated Paper Trading")
        update_paper_trades(ltp)
        summary = get_paper_trade_summary()
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Trades", summary["total"])
        col2.metric("P&L", f"₹{summary['total_pnl']:+.2f}")
        col3.metric("Win Rate", f"{summary['win_rate']}%")
        
        df = get_trades_df()
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
        if st.button("🗑️ Clear All Trades"):
            clear_all_trades()
            st.rerun()
    
    with t2:
        st.markdown("#### 📊 Open Interest Analysis")
        # Reuse existing candle data for simplicity
        st.dataframe(build_oi_timeframe_table({sel_tf: candle_df}, options_df, ltp), use_container_width=True)
    
    with t3:
        st.markdown("#### 🔢 Option Greeks")
        if options_df is not None:
            greeks = analyze_greeks(options_df, ltp)
            st.dataframe(greeks.get("table", pd.DataFrame()), use_container_width=True)

    with t4:
        st.markdown("#### 📋 Detected Pattern Signals")
        for p in patterns[-10:]:
            st.info(f"**{p.signal}** | {p.pattern} | Entry: {p.entry} | Target: {p.target}")

    # Auto-refresh
    if st.toggle("Enable Live Refresh (5s)", value=False, key="ar_toggle") and HAS_AUTOREFRESH:
        st_autorefresh(interval=5000, key="main_refresh")

if __name__ == "__main__":
    main()
