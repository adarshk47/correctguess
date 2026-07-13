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

@st.cache_data(ttl=5)
def fetch_ltp_info(token=NIFTY_TOKEN):
    """
    Fetch full LTP data for NIFTY 50, including previous close (for change calc).
    Returns a dict with ltp, close, open, high, low.
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

@st.cache_data(ttl=5)
def fetch_ltp(token=NIFTY_TOKEN):
    """Return only the LTP float."""
    return fetch_ltp_info(token)["ltp"]


def _read_secrets() -> dict:
    """
    Read AngelOne credentials from st.secrets.
    """
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
    """
    Get or create an AngelOne SmartConnect client session.
    """
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
        st.session_state["angel_error"] = f"smartapi-python not installed: {e}"
        return None

    creds = _read_secrets()
    missing = [k for k in ("api_key", "client_id", "login_pwd", "totp_secret")
               if not creds.get(k)]
    if missing:
        st.session_state["angel_client_valid"] = False
        st.session_state["angel_error"] = "Missing credentials in secrets"
        return None

    try:
        obj = SmartConnect(api_key=creds["api_key"])
        totp = pyotp.TOTP(creds["totp_secret"]).now()
        data = obj.generateSession(creds["client_id"], creds["login_pwd"], totp)

        if data and data.get("status"):
            try:
                obj.getfeedToken()
            except Exception:
                pass
            st.session_state["angel_client"] = obj
            st.session_state["angel_client_valid"] = True
            st.session_state["angel_auth_token"] = data["data"]["jwtToken"]
            st.session_state["angel_error"] = ""
            return obj

        msg = ""
        if isinstance(data, dict):
            msg = data.get("message") or data.get("errorcode") or str(data)
        st.session_state["angel_client_valid"] = False
        st.session_state["angel_error"] = f"Login failed: {msg}"
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


def get_data_source() -> str:
    return "LIVE" if is_connected() else "DEMO"


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def _candidate_expiry_strings(ref_date=None) -> list:
    today = ref_date or datetime.now(IST).date()
    candidates = []
    if today.weekday() == 1:
        candidates.append(today.strftime("%d%b%Y").upper())
    d = today
    for _ in range(6):
        days_ahead = (1 - d.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        d = d + timedelta(days=days_ahead)
        candidates.append(d.strftime("%d%b%Y").upper())
    return candidates


@st.cache_data(ttl=1800)
def _find_valid_nifty_expiry_via_api() -> str:
    obj = get_client()
    if obj is None:
        return ""
    for i, expiry_str in enumerate(_candidate_expiry_strings()):
        if i > 0:
            time.sleep(0.35)
        try:
            gr = obj.optionGreek({"name": "NIFTY", "expirydate": expiry_str})
            if gr and gr.get("status") and gr.get("data"):
                return expiry_str
        except Exception:
            pass
    return ""


def get_next_weekly_expiry() -> datetime:
    now = datetime.now(IST)
    today = now.date()
    mkt_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    def _as_dt(expiry_str: str):
        try:
            d = datetime.strptime(expiry_str, "%d%b%Y").date()
            return datetime.combine(d, datetime.min.time()).replace(tzinfo=IST)
        except Exception:
            return None

    try:
        valid = _find_valid_nifty_expiry_via_api()
        if valid:
            expiry_dt = _as_dt(valid)
            if expiry_dt:
                st.session_state["_last_known_expiry"] = expiry_dt
                st.session_state["_expiry_source"] = "AngelOne optionGreek"
                return expiry_dt
    except Exception:
        pass

    cached = st.session_state.get("_last_known_expiry")
    if cached is not None:
        if cached.date() >= today:
            return cached

    days_ahead = (1 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    tuesday = today + timedelta(days=days_ahead)
    expiry_dt = datetime.combine(tuesday, datetime.min.time()).replace(tzinfo=IST)
    st.session_state["_expiry_source"] = "estimated Tuesday"
    return expiry_dt


def get_expiry_string(expiry_dt) -> str:
    if expiry_dt is None:
        return "---"
    return expiry_dt.strftime("%d%b%Y").upper()


def get_expiry_countdown(expiry_dt) -> str:
    if expiry_dt is None:
        return "---"
    now = datetime.now(IST)
    expiry_close = expiry_dt.replace(hour=15, minute=30, second=0)
    diff = expiry_close - now
    if diff.total_seconds() <= 0:
        return "Expired"
    total_seconds = int(diff.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days == 0:
        return f"Expiry Today! {hours}h {minutes}m remaining"
    return f"{days}d {hours}h {minutes}m"


_EMPTY_CANDLES = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


@st.cache_data(ttl=30)
def fetch_candle_data(interval_minutes: int = 1, lookback_bars: int = 200) -> pd.DataFrame:
    obj = get_client()
    if obj is None:
        return _EMPTY_CANDLES.copy()

    try:
        interval_str = INTERVAL_MAP.get(interval_minutes, "ONE_MINUTE")
        now = datetime.now(IST)
        lookback_minutes = interval_minutes * lookback_bars
        from_dt = now - timedelta(minutes=lookback_minutes + 30)
        earliest = now - timedelta(days=6)
        if from_dt > earliest:
            from_dt = earliest

        from_str = from_dt.strftime("%Y-%m-%d %H:%M")
        to_str = now.strftime("%Y-%m-%d %H:%M")

        params = {
            "exchange": NIFTY_EXCHANGE,
            "symboltoken": NIFTY_TOKEN,
            "interval": interval_str,
            "fromdate": from_str,
            "todate": to_str,
        }
        response = obj.getCandleData(params)

        if response and response.get("status") and response.get("data"):
            raw = response["data"]
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            df = df.sort_values("timestamp").reset_index(drop=True)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df.dropna(inplace=True)
            return df
        return _EMPTY_CANDLES.copy()
    except Exception as e:
        logger.error(f"Candle data error: {e}")
        return _EMPTY_CANDLES.copy()


_SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

@st.cache_data(ttl=3600)
def _load_nifty_master_raw() -> pd.DataFrame:
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    resp = requests.get(_SCRIP_MASTER_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    rows = []
    for item in data:
        if item.get("name") != "NIFTY" or item.get("instrumenttype") != "OPTIDX":
            continue
        symbol = item.get("symbol", "")
        opt_type = "CE" if symbol.endswith("CE") else "PE" if symbol.endswith("PE") else None
        if opt_type is None:
            continue
        exp_raw = str(item.get("expiry", "")).upper()
        try:
            exp_date = datetime.strptime(exp_raw, "%d%b%Y").date()
            strike = float(item.get("strike", 0)) / 100.0
            rows.append({
                "strike": strike,
                "option_type": opt_type,
                "token": str(item.get("token", "")),
                "symbol": symbol,
                "expiry": exp_raw,
                "expiry_date": exp_date,
            })
        except Exception:
            continue
    return pd.DataFrame(rows)


def _load_nifty_option_master(expiry_str: str) -> pd.DataFrame:
    try:
        raw = _load_nifty_master_raw()
        if not raw.empty:
            sub = raw[raw["expiry"] == expiry_str.upper()]
            if not sub.empty:
                return sub[["strike", "option_type", "token", "symbol"]].reset_index(drop=True)
    except Exception as e:
        logger.warning(f"Scrip master option lookup failed: {e}")
    return pd.DataFrame()


def _chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


@st.cache_data(ttl=30)
def fetch_options_chain(expiry_str=None):
    try:
        if expiry_str is None or expiry_str == "---":
            expiry_dt = get_next_weekly_expiry()
            expiry_str = get_expiry_string(expiry_dt)

        obj = get_client()
        spot = fetch_ltp() if obj is not None else 0.0

        greeks_by_key = {}
        greek_strikes = set()
        if obj is not None:
            try:
                gr = obj.optionGreek({"name": "NIFTY", "expirydate": expiry_str})
                if gr and gr.get("status") and gr.get("data"):
                    for g in gr["data"]:
                        strike = float(g.get("strikePrice", 0))
                        ot = g.get("optionType", "").upper()
                        greeks_by_key[(strike, ot)] = g
                        greek_strikes.add(strike)
            except Exception:
                pass

        master = _load_nifty_option_master(expiry_str) if obj is not None else pd.DataFrame()
        strike_opt_to_md = {}

        if obj is not None and not master.empty:
            all_strikes = sorted(master["strike"].unique())
            if spot and spot > 0:
                atm = min(all_strikes, key=lambda s: abs(s - spot))
                idx = all_strikes.index(atm)
                master = master[master["strike"].isin(set(all_strikes[max(0, idx - 12):idx + 13]))]

            token_to_meta = {r["token"]: (r["strike"], r["option_type"]) for _, r in master.iterrows()}
            md_by_token = {}
            for batch in _chunked(list(token_to_meta.keys()), 50):
                try:
                    time.sleep(0.1) # Added sleep to avoid rate limiting
                    md = obj.getMarketData("FULL", {"NFO": batch})
                    if md and md.get("status") and md.get("data"):
                        for item in md["data"].get("fetched", []):
                            md_by_token[str(item.get("symbolToken"))] = item
                except Exception:
                    pass
            for tok, item in md_by_token.items():
                meta = token_to_meta.get(tok)
                if meta:
                    strike_opt_to_md[meta] = item

        all_avail = sorted(set(master["strike"].unique().tolist() if not master.empty else []) | greek_strikes)
        if spot and spot > 0 and all_avail:
            atm = min(all_avail, key=lambda s: abs(s - spot))
            idx = all_avail.index(atm)
            use_strikes = set(all_avail[max(0, idx - 12):idx + 13])
        else:
            use_strikes = set(all_avail[:25])

        rows = []
        for strike in sorted(use_strikes):
            row = {"strike": float(strike)}
            for opt in ("ce", "pe"):
                ot = opt.upper()
                md = strike_opt_to_md.get((float(strike), ot))
                g = greeks_by_key.get((float(strike), ot), {})
                row[f"{opt}_oi"] = int(float(md.get("opnInterest", 0) or 0)) if md else 0
                row[f"{opt}_volume"] = int(float(md.get("tradeVolume", 0) or 0)) if md else 0
                row[f"{opt}_ltp"] = float(md.get("ltp", 0) or 0) if md else float(g.get("ltp", 0) or 0)
                row[f"{opt}_bid"] = 0.0
                row[f"{opt}_ask"] = 0.0
                row[f"{opt}_iv"] = float(g.get("impliedVolatility", 0) or 0)
                row[f"{opt}_delta"] = float(g.get("delta", 0) or 0)
                row[f"{opt}_gamma"] = float(g.get("gamma", 0) or 0)
                row[f"{opt}_theta"] = float(g.get("theta", 0) or 0)
                row[f"{opt}_vega"] = float(g.get("vega", 0) or 0)
            rows.append(row)

        df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True) if rows else pd.DataFrame()
        
        # Fallback to NSE chain if AngelOne fails to provide OI
        if df.empty or (df["ce_oi"].sum() + df["pe_oi"].sum()) == 0:
            try:
                from modules.nse_client import fetch_nse_chain_df
                nse_df = fetch_nse_chain_df(expiry_str)
                if not nse_df.empty:
                    df = nse_df
                    st.session_state["_chain_source"] = "NSE"
            except Exception:
                pass
        else:
            st.session_state["_chain_source"] = "AngelOne"

        if not df.empty:
            st.session_state["_last_options_df"] = df.copy()
        return df
    except Exception as e:
        logger.error(f"Options chain error: {e}")
        return st.session_state.get("_last_options_df", pd.DataFrame())


def get_options_diagnostics(expiry_str=None):
    diag = {"connected": get_client() is not None, "last_error": get_last_error() or "—"}
    return diag


def get_atm_strike(spot_price, step=50):
    return int(round(spot_price / step) * step)


def get_strike_range(spot_price, n=5, step=50):
    atm = get_atm_strike(spot_price, step)
    return [atm + i * step for i in range(-n, n + 1)]
