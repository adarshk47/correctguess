"""
AngelOne SmartAPI Client Wrapper
Handles authentication, session management, and all data fetching.
"""

import streamlit as st
import pyotp
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import time
import logging
import re as _re

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

NIFTY_TOKEN = "99926000"
NIFTY_EXCHANGE = "NSE"

INTERVAL_MAP = {
    1: "ONE_MINUTE",
    2: "TWO_MINUTE",
    3: "THREE_MINUTE",
    5: "FIVE_MINUTE",
    10: "TEN_MINUTE",
    15: "FIFTEEN_MINUTE",
    30: "THIRTY_MINUTE",
    60: "ONE_HOUR",
}

@st.cache_data(ttl=10)
def fetch_ltp_info(token=NIFTY_TOKEN):
    """
    Fetch full LTP data for NIFTY 50, including previous close.
    """
    obj = get_client()
    default = {"ltp": 0.0, "close": 0.0, "open": 0.0, "high": 0.0, "low": 0.0}
    if obj is None:
        return default

    try:
        response = obj.ltpData(NIFTY_EXCHANGE, "NIFTY 50", token)
        if response and response.get("status") and response.get("data"):
            d = response["data"]
            return {
                "ltp": float(d.get("ltp", 0)),
                "close": float(d.get("close", 0)),
                "open": float(d.get("open", 0)),
                "high": float(d.get("high", 0)),
                "low": float(d.get("low", 0)),
            }
        # Fall back to candles
        candles = fetch_candle_data(1, 2)
        if not candles.empty:
            last_close = float(candles["close"].iloc[-1])
            return {**default, "ltp": last_close, "close": last_close}
        return default
    except Exception as e:
        logger.error(f"LTP fetch error: {e}")
        return default

def fetch_ltp(token=NIFTY_TOKEN):
    """Return only the LTP float."""
    return fetch_ltp_info(token)["ltp"]


def _read_secrets() -> dict:
    section = {}
    for key in ("angel_one", "angelone", "ANGEL_ONE", "ANGELONE"):
        try:
            if key in st.secrets:
                section = st.secrets[key]
                break
        except Exception:
            continue
    if not section:
        section = st.secrets

    def g(*names):
        for n in names:
            try:
                if n in section and section[n]:
                    return str(section[n])
            except Exception:
                pass
        return ""

    return {
        "api_key": g("api_key", "apikey", "key"),
        "client_id": g("client_id", "clientid", "client_code", "clientcode"),
        "login_pwd": g("mpin", "pin", "password"),
        "totp_secret": g("totp_secret", "totp", "totp_key"),
    }


def get_client(force: bool = False):
    if force:
        st.session_state.pop("angel_client", None)
        st.session_state["angel_client_valid"] = False

    if st.session_state.get("angel_client") is not None and \
            st.session_state.get("angel_client_valid", False):
        return st.session_state["angel_client"]

    st.session_state["angel_error"] = ""
    try:
        from SmartApi import SmartConnect
    except ImportError as e:
        st.session_state["angel_client_valid"] = False
        st.session_state["angel_error"] = f"smartapi-python error: {e}"
        return None

    creds = _read_secrets()
    missing = [k for k in ("api_key", "client_id", "login_pwd", "totp_secret") if not creds.get(k)]
    if missing:
        st.session_state["angel_client_valid"] = False
        st.session_state["angel_error"] = "Missing credentials"
        return None

    try:
        obj = SmartConnect(api_key=creds["api_key"])
        totp = pyotp.TOTP(creds["totp_secret"]).now()
        data = obj.generateSession(creds["client_id"], creds["login_pwd"], totp)

        if data and data.get("status"):
            try: obj.getfeedToken()
            except Exception: pass
            st.session_state["angel_client"] = obj
            st.session_state["angel_client_valid"] = True
            st.session_state["angel_auth_token"] = data["data"]["jwtToken"]
            st.session_state["angel_error"] = ""
            return obj

        st.session_state["angel_client_valid"] = False
        st.session_state["angel_error"] = f"Login failed: {data.get('message') if data else 'Unknown error'}"
        return None
    except Exception as e:
        logger.error(f"AngelOne login error: {e}")
        st.session_state["angel_client_valid"] = False
        st.session_state["angel_error"] = f"Login error: {e}"
        return None


def get_last_error() -> str:
    return st.session_state.get("angel_error", "")


def is_connected() -> bool:
    if "angel_client_valid" not in st.session_state:
        get_client()
    return bool(st.session_state.get("angel_client_valid", False))


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5: return False
    mo = now.replace(hour=9, minute=15, second=0, microsecond=0)
    mc = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return mo <= now <= mc


def _candidate_expiry_strings(ref_date=None) -> list:
    today = ref_date or datetime.now(IST).date()
    candidates = []
    if today.weekday() == 1: candidates.append(today.strftime("%d%b%Y").upper())
    d = today
    for _ in range(6):
        days_ahead = (1 - d.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        d = d + timedelta(days=days_ahead)
        candidates.append(d.strftime("%d%b%Y").upper())
    return candidates


@st.cache_data(ttl=1800)
def _find_valid_nifty_expiry_via_api() -> str:
    obj = get_client()
    if obj is None: return ""
    for i, expiry_str in enumerate(_candidate_expiry_strings()):
        if i > 0: time.sleep(0.35)
        try:
            gr = obj.optionGreek({"name": "NIFTY", "expirydate": expiry_str})
            if gr and gr.get("status") and gr.get("data"): return expiry_str
        except Exception: pass
    return ""


def get_next_weekly_expiry() -> datetime:
    now = datetime.now(IST)
    today = now.date()
    try:
        valid = _find_valid_nifty_expiry_via_api()
        if valid:
            d = datetime.strptime(valid, "%d%b%Y").date()
            dt = datetime.combine(d, datetime.min.time()).replace(tzinfo=IST)
            st.session_state["_last_known_expiry"] = dt
            return dt
    except Exception: pass
    cached = st.session_state.get("_last_known_expiry")
    if cached and cached.date() >= today: return cached
    days_ahead = (1 - today.weekday()) % 7
    if days_ahead == 0: days_ahead = 7
    dt = datetime.combine(today + timedelta(days=days_ahead), datetime.min.time()).replace(tzinfo=IST)
    return dt


def get_expiry_string(expiry_dt) -> str:
    return expiry_dt.strftime("%d%b%Y").upper() if expiry_dt else "---"


def get_expiry_countdown(expiry_dt) -> str:
    if expiry_dt is None: return "---"
    now = datetime.now(IST)
    diff = expiry_dt.replace(hour=15, minute=30, second=0) - now
    if diff.total_seconds() <= 0: return "Expired"
    ts = int(diff.total_seconds())
    days, hours, minutes = ts // 86400, (ts % 86400) // 3600, (ts % 3600) // 60
    if days == 0: return f"Today! {hours}h {minutes}m"
    return f"{days}d {hours}h {minutes}m"


_EMPTY_CANDLES = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


@st.cache_data(ttl=60)
def fetch_candle_data(interval_minutes: int = 5, lookback_bars: int = 500) -> pd.DataFrame:
    obj = get_client()
    if obj is None: return _EMPTY_CANDLES.copy()
    try:
        now = datetime.now(IST)
        from_dt = now - timedelta(days=6)
        params = {
            "exchange": NIFTY_EXCHANGE, "symboltoken": NIFTY_TOKEN,
            "interval": INTERVAL_MAP.get(interval_minutes, "FIVE_MINUTE"),
            "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
            "todate": now.strftime("%Y-%m-%d %H:%M"),
        }
        res = obj.getCandleData(params)
        if res and res.get("status") and res.get("data"):
            df = pd.DataFrame(res["data"], columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            for c in ["open", "high", "low", "close", "volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.sort_values("timestamp").dropna().reset_index(drop=True).tail(lookback_bars)
        return _EMPTY_CANDLES.copy()
    except Exception as e:
        logger.error(f"Candle error: {e}")
        return _EMPTY_CANDLES.copy()


_SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

@st.cache_data(ttl=3600)
def _load_nifty_master_raw() -> pd.DataFrame:
    import requests
    try:
        resp = requests.get(_SCRIP_MASTER_URL, timeout=30)
        resp.raise_for_status()
        rows = []
        for item in resp.json():
            if item.get("name") == "NIFTY" and item.get("instrumenttype") == "OPTIDX":
                sym = item.get("symbol", "")
                ot = "CE" if sym.endswith("CE") else "PE" if sym.endswith("PE") else None
                if ot:
                    exp_raw = str(item.get("expiry", "")).upper()
                    try:
                        rows.append({
                            "strike": float(item.get("strike", 0)) / 100.0,
                            "option_type": ot, "token": str(item.get("token", "")),
                            "symbol": sym, "expiry": exp_raw,
                        })
                    except: continue
        return pd.DataFrame(rows)
    except: return pd.DataFrame()


def _load_nifty_option_master(expiry_str: str) -> pd.DataFrame:
    raw = _load_nifty_master_raw()
    if not raw.empty:
        sub = raw[raw["expiry"] == expiry_str.upper()]
        if not sub.empty: return sub.reset_index(drop=True)
    return pd.DataFrame()


@st.cache_data(ttl=60)
def fetch_options_chain(expiry_str=None):
    try:
        if not expiry_str or expiry_str == "---":
            expiry_str = get_expiry_string(get_next_weekly_expiry())
        obj = get_client()
        spot = fetch_ltp()
        
        greeks_by_key, greek_strikes = {}, set()
        if obj:
            try:
                gr = obj.optionGreek({"name": "NIFTY", "expirydate": expiry_str})
                if gr and gr.get("status") and gr.get("data"):
                    for g in gr["data"]:
                        k = (float(g.get("strikePrice", 0)), g.get("optionType", "").upper())
                        greeks_by_key[k] = g
                        greek_strikes.add(k[0])
            except: pass

        master = _load_nifty_option_master(expiry_str)
        strike_opt_to_md = {}
        if obj and not master.empty:
            all_s = sorted(master["strike"].unique())
            atm = min(all_s, key=lambda s: abs(s - (spot or all_s[len(all_s)//2])))
            idx = all_s.index(atm)
            master = master[master["strike"].isin(set(all_s[max(0, idx-12):idx+13]))]
            tokens = master["token"].tolist()
            for batch in [tokens[i:i + 50] for i in range(0, len(tokens), 50)]:
                try:
                    time.sleep(0.1)
                    md = obj.getMarketData("FULL", {"NFO": batch})
                    if md and md.get("status") and md.get("data"):
                        for item in md["data"].get("fetched", []):
                            tok = str(item.get("symbolToken"))
                            meta = master[master["token"] == tok].iloc[0]
                            strike_opt_to_md[(float(meta["strike"]), meta["option_type"])] = item
                except: pass

        use_strikes = sorted(greek_strikes if not strike_opt_to_md else set(k[0] for k in strike_opt_to_md.keys()))
        rows = []
        for s in use_strikes:
            row = {"strike": float(s)}
            for opt in ("ce", "pe"):
                md, g = strike_opt_to_md.get((float(s), opt.upper())), greeks_by_key.get((float(s), opt.upper()), {})
                row[f"{opt}_oi"] = int(float(md.get("opnInterest", 0))) if md else 0
                row[f"{opt}_volume"] = int(float(md.get("tradeVolume", 0))) if md else 0
                row[f"{opt}_ltp"] = float(md.get("ltp", 0)) if md else float(g.get("ltp", 0))
                row[f"{opt}_iv"] = float(g.get("impliedVolatility", 0))
                for gk in ("delta", "gamma", "theta", "vega"): row[f"{opt}_{gk}"] = float(g.get(gk, 0))
            rows.append(row)
        df = pd.DataFrame(rows)
        if df.empty or df["ce_oi"].sum() + df["pe_oi"].sum() == 0:
            try:
                from modules.nse_client import fetch_nse_chain_df
                df = fetch_nse_chain_df(expiry_str)
                st.session_state["_chain_source"] = "NSE"
            except: pass
        else: st.session_state["_chain_source"] = "AngelOne"
        if not df.empty: st.session_state["_last_options_df"] = df.copy()
        return df
    except: return st.session_state.get("_last_options_df", pd.DataFrame())


def get_options_diagnostics(expiry_str=None):
    return {"connected": is_connected(), "last_error": get_last_error() or "None"}

def get_atm_strike(spot_price, step=50): return int(round(spot_price / step) * step)

def get_strike_range(spot_price, n=5, step=50):
    atm = get_atm_strike(spot_price, step)
    return [atm + i * step for i in range(-n, n + 1)]
