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
    .refresh-bar {
        background: #1e2130;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        color: #888;
        margin-top: 8px;
    }
    .bullish { color: #00ff88 !important; }
    .bearish { color: #ff4444 !important; }
    .badge-high { background: #1a3a1a; color: #00ff88; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
    .badge-med  { background: #3a3a1a; color: #ffd700; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
    .badge-low  { background: #3a1a1a; color: #ff8888; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
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

# ── Helpers ──────────────────────────────────────────────────────────────────
if "recommendation_history" not in st.session_state:
    st.session_state["recommendation_history"] = []

def get_now(): return datetime.now(IST)

def filter_to_recent_data(df, days=2):
    if df is None or df.empty: return df
    ts = pd.to_datetime(df["timestamp"])
    last_dates = sorted(ts.dt.date.unique())[-days:]
    return df[ts.dt.date.isin(last_dates)].reset_index(drop=True)

def style_cells(styler, func, subset):
    if hasattr(styler, "map"):
        try: return styler.map(func, subset=subset)
        except: pass
    return styler.applymap(func, subset=subset)

# ─────────────────────────────────────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────────────────────────────────────

def render_header(ltp, spot_prev, connected):
    now = get_now()
    expiry_dt = get_next_weekly_expiry()
    expiry_str = get_expiry_string(expiry_dt)
    countdown = get_expiry_countdown(expiry_dt)
    market_open = is_market_open()
    
    status_html = '<span style="color:#00ff88;">🟢 AngelOne LIVE</span>' if connected else '<span style="color:#ff5555;">🔴 DEMO / OFFLINE</span>'
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
        st.markdown(f'<div class="metric-card"><div class="metric-label">Weekly Expiry</div><div class="metric-value" style="color:#ffd700;">{expiry_str}</div><div class="metric-sub">{expiry_dt.strftime("%A") if expiry_dt else "---"}</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Countdown</div><div class="metric-value" style="color:#ffd700;">{countdown}</div><div class="metric-sub">Settlement</div></div>', unsafe_allow_html=True)
    with col5:
        mkt_status = "🟢 OPEN" if market_open else "🔴 CLOSED"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Status</div><div class="metric-value">{mkt_status}</div><div class="metric-sub">09:15 - 15:30 IST</div></div>', unsafe_allow_html=True)

def build_chart(candle_df, patterns, oi_annotations, tf_minutes):
    if candle_df is None or candle_df.empty:
        return go.Figure().update_layout(title="Waiting for market data...", paper_bgcolor="#0e1117", font_color="#fff")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=candle_df["timestamp"], open=candle_df["open"], high=candle_df["high"], low=candle_df["low"], close=candle_df["close"], name="NIFTY"), row=1, col=1)
    
    # EMAs
    ema9 = candle_df["close"].ewm(span=9, adjust=False).mean()
    ema21 = candle_df["close"].ewm(span=21, adjust=False).mean()
    fig.add_trace(go.Scatter(x=candle_df["timestamp"], y=ema9, line=dict(color="#ffaa00", width=1), name="EMA 9"), row=1, col=1)
    fig.add_trace(go.Scatter(x=candle_df["timestamp"], y=ema21, line=dict(color="#33b5ff", width=1), name="EMA 21"), row=1, col=1)

    fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font=dict(color="#ccc", size=10), height=500, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False, hovermode="x unified")
    
    # Remove non-trading hours
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[15.5, 9.25], pattern="hour")])
    
    if oi_annotations:
        for ann in oi_annotations:
            try: fig.add_annotation(ann)
            except: pass

    return fig

# ── Tabs ─────────────────────────────────────────────────────────────────────

def render_paper_trade_tab(patterns, spot, options_df=None):
    st.markdown("### 📝 Paper Trading")
    if not spot:
        st.warning("Waiting for spot price...")
        return
    
    update_paper_trades(spot)
    summary = get_paper_trade_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Trades", summary["total"])
    c2.metric("P&L", f"₹{summary['total_pnl']:+.2f}")
    c3.metric("Win Rate", f"{summary['win_rate']}%")
    c4.metric("Open", summary["open"])

    df = get_trades_df()
    if not df.empty:
        st.markdown("#### 📋 All Trades")
        st.dataframe(df.style.applymap(lambda x: "color: #00ff88" if x == "PROFIT" else "color: #ff4444" if x == "LOSS" else "", subset=["status"]), width='stretch', hide_index=True)
    
    if st.button("🗑️ Clear Trades"):
        clear_all_trades()
        st.rerun()

def render_best_trade_tab(patterns, options_df, spot, oi_delta, greeks):
    st.markdown("### 🏆 Best Trade Recommendation")
    if not is_market_open():
        st.warning("🔴 Market Closed – Showing analysis based on latest data.")

    if not patterns:
        st.info("Scanning for high-probability setups... Try switching timeframes.")
        return

    scored = []
    for pat in patterns:
        # Robust confidence access
        conf = getattr(pat, "confidence", 0.5)
        conf_score = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}.get(conf, 0.5) if isinstance(conf, str) else float(conf)
        
        # Risk:Reward score (capped at 1.0 for rr=5)
        rr = float(getattr(pat, "risk_reward", 0) or 0)
        rr_score = min(rr / 5, 1.0)
        
        score = conf_score * 0.5 + rr_score * 0.5
        
        # Confirmation from OI
        oi_bias = oi_delta.get("bias", "NEUTRAL")
        if (pat.signal == "BUY" and oi_bias == "BULLISH") or (pat.signal == "SELL" and oi_bias == "BEARISH"): 
            score += 0.2
        
        # Confirmation from Greeks
        g_bias = greeks.get("bias", "NEUTRAL")
        if (pat.signal == "BUY" and g_bias == "BULLISH") or (pat.signal == "SELL" and g_bias == "BEARISH"): 
            score += 0.15
        
        scored.append((score, pat))

    if not scored:
        st.info("No valid setups found right now.")
        return

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_pat = scored[0]
    
    sig_color = "#00ff88" if best_pat.signal == "BUY" else "#ff4444"
    atm = round(spot / 50) * 50
    opt_type = "CE" if best_pat.signal == "BUY" else "PE"
    
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1a2a1a,#1e2130); border:2px solid {sig_color}; border-radius:12px; padding:20px; margin-bottom:20px;">
        <div style="font-size:24px; font-weight:bold; color:{sig_color};">{best_pat.signal} | {best_pat.pattern}</div>
        <div style="color:#aaa;">Score: <b style="color:#ffd700;">{best_score:.2f}</b> | Confidence: <b>{best_pat.confidence}</b></div>
        <hr style="border-color:#333;">
        <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap: 10px;">
            <div><small>Entry</small><br><b>{best_pat.entry:.2f}</b></div>
            <div><small>SL</small><br><b style="color:#ff8888;">{best_pat.stop_loss:.2f}</b></div>
            <div><small>Target</small><br><b style="color:#88ff88;">{best_pat.target:.2f}</b></div>
            <div><small>R:R</small><br><b style="color:#ffd700;">1:{best_pat.risk_reward}</b></div>
        </div>
        <div style="margin-top:15px; font-size:14px;">
            Trade: <b style="color:#fff;">NIFTY {atm} {opt_type} (ATM)</b>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not MODULES_OK: st.stop()

    ltp_info = fetch_ltp_info()
    ltp, spot_prev = ltp_info["ltp"], ltp_info["close"]
    connected = is_connected()

    # Data Fetching
    candle_df = fetch_candle_data(5, 1000) # Increased lookback to 1000
    candle_df = filter_to_recent_data(candle_df, days=3) # More context
    patterns = detect_all_patterns(candle_df) if not candle_df.empty else []
    
    # OI Annotations
    oi_annotations = []
    options_df = fetch_options_chain()
    if options_df is not None and not candle_df.empty:
        oi_annotations = get_oi_arrow_annotations(candle_df, options_df, ltp, 5)
    
    # 1. Chart
    st.plotly_chart(build_chart(candle_df, patterns, oi_annotations, 5), width='stretch')
    
    # 2. Header
    render_header(ltp, spot_prev, connected)

    # 3. Tabs
    tabs = st.tabs(["🏆 Best Trade", "📝 Paper Trade", "📊 OI Analysis", "🔢 Greeks", "🎯 Most Traded"])
    
    oi_delta = compute_delta_oi(options_df, ltp) if options_df is not None else {}
    greeks_res = analyze_greeks(options_df, ltp) if options_df is not None else {}

    with tabs[0]:
        render_best_trade_tab(patterns, options_df, ltp, oi_delta, greeks_res)
    
    with tabs[1]:
        render_paper_trade_tab(patterns, ltp, options_df)
    
    with tabs[2]:
        st.markdown("### 📊 Open Interest Analysis")
        if options_df is not None:
            sr = oi_support_resistance(options_df, ltp)
            if sr.get("available"):
                c1, c2 = st.columns(2)
                c1.write("🟢 Support (Max PE OI)")
                c1.dataframe(pd.DataFrame(sr["supports"]), hide_index=True)
                c2.write("🔴 Resistance (Max CE OI)")
                c2.dataframe(pd.DataFrame(sr["resistances"]), hide_index=True)
            st.write("#### OI Timeframe Table")
            st.dataframe(build_oi_timeframe_table({5: candle_df}, options_df, ltp), width='stretch')

    with tabs[3]:
        st.markdown("### 🔢 Option Greeks")
        if greeks_res:
            st.dataframe(greeks_res.get("table", pd.DataFrame()), width='stretch', hide_index=True)

    with tabs[4]:
        st.markdown("### 🎯 Most Traded Strikes")
        if options_df is not None:
            st.dataframe(build_strike_volume_table(options_df, {5: candle_df}, ltp), width='stretch', hide_index=True)

    # Refresh
    if st.toggle("Enable Live Refresh (5s)", value=False, key="ar_toggle") and HAS_AUTOREFRESH:
        st_autorefresh(interval=5000, key="main_refresh")

if __name__ == "__main__":
    main()
