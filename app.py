from __future__ import annotations
from datetime import datetime, timezone
import streamlit as st

from config import APP_TITLE, APP_ICON, ASSETS, DATA_PERIOD, DATA_INTERVAL, REFRESH_SECONDS
from data_loader import download_market_data, MarketDataError
from signal_engine import evaluate_asset

st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide")

st.markdown("""
<style>
.block-container {max-width: 980px; padding-top: 1.5rem;}
.signal-card {border:1px solid rgba(128,128,128,.28);border-radius:18px;padding:1.25rem;margin:.4rem 0;}
.big-signal {font-size:2.4rem;font-weight:800;line-height:1.1;}
.asset {font-size:1.15rem;font-weight:700;opacity:.8;}
.small {opacity:.68;font-size:.9rem;}
</style>
""", unsafe_allow_html=True)

if "session_active" not in st.session_state:
    st.session_state.session_active = False
if "session_started" not in st.session_state:
    st.session_state.session_started = None
if "last_signal_key" not in st.session_state:
    st.session_state.last_signal_key = {}
if "signal_count" not in st.session_state:
    st.session_state.signal_count = 0

st.title("⚡ ARGO 4.0")
st.caption("SESSION TRADER · BTC + GBP/USD · M15")

left, right = st.columns(2)
with left:
    if not st.session_state.session_active:
        if st.button("▶ AVVIA SESSIONE", type="primary", use_container_width=True):
            st.session_state.session_active = True
            st.session_state.session_started = datetime.now(timezone.utc)
            st.session_state.last_signal_key = {}
            st.session_state.signal_count = 0
            st.rerun()
    else:
        if st.button("■ TERMINA SESSIONE", use_container_width=True):
            st.session_state.session_active = False
            st.rerun()

with right:
    status = "🟢 SESSIONE ATTIVA" if st.session_state.session_active else "⚪ ARGO A RIPOSO"
    st.metric("Stato", status)

if not st.session_state.session_active:
    st.info("Premi AVVIA SESSIONE. ARGO non analizza i mercati finché la sessione non è attiva.")
    st.stop()

def seconds_to_next_quarter():
    now = datetime.now(timezone.utc)
    elapsed = (now.minute % 15) * 60 + now.second
    return 15 * 60 - elapsed if elapsed else 15 * 60

@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def live_session():
    remaining = seconds_to_next_quarter()
    mm, ss = divmod(remaining, 60)

    a, b, c = st.columns(3)
    a.metric("Prossima chiusura M15", f"{mm:02d}:{ss:02d}")
    if st.session_state.session_started:
        elapsed = datetime.now(timezone.utc) - st.session_state.session_started
        total = int(elapsed.total_seconds())
        eh, rem = divmod(total, 3600); em, es = divmod(rem, 60)
        b.metric("Sessione", f"{eh:02d}:{em:02d}:{es:02d}")
    c.metric("Segnali sessione", st.session_state.signal_count)

    results = []
    for asset, cfg in ASSETS.items():
        try:
            df = download_market_data(cfg["ticker"], DATA_PERIOD, DATA_INTERVAL)
            result = evaluate_asset(asset, df, cfg)
        except MarketDataError as exc:
            result = None
            st.error(f"{asset}: {exc}")
        except Exception as exc:
            result = None
            st.error(f"{asset}: errore analisi — {exc}")
        results.append((asset, cfg, result))

    cols = st.columns(2)
    for col, (asset, cfg, result) in zip(cols, results):
        with col:
            if result is None:
                st.markdown(f"<div class='signal-card'><div class='asset'>{asset}</div><div class='big-signal'>⚠️ DATA</div></div>", unsafe_allow_html=True)
                continue

            icon = {"BUY":"🟢", "SELL":"🔴", "WAIT":"⚪"}[result.signal]
            label = result.signal

            # Count each candle/direction only once during this Streamlit session.
            if result.signal in ("BUY","SELL") and result.candle_time is not None:
                key = f"{result.candle_time}|{result.signal}"
                if st.session_state.last_signal_key.get(asset) != key:
                    st.session_state.last_signal_key[asset] = key
                    st.session_state.signal_count += 1

            candle = str(result.candle_time) if result.candle_time is not None else "—"
            kd = f"K {result.k:.1f} · D {result.d:.1f}" if result.k is not None else "In attesa"

            st.markdown(
                f"<div class='signal-card'>"
                f"<div class='asset'>{asset}</div>"
                f"<div class='big-signal'>{icon} {label}</div>"
                f"<div>{kd}</div>"
                f"<div class='small'>{result.reason}</div>"
                f"<div class='small'>Ultima candela valutata: {candle}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

    st.caption("ARGO genera solo la direzione. Apertura, dimensione e chiusura della posizione restano manuali.")

live_session()

st.warning(
    "Feed dati: questa build usa Yahoo Finance/yfinance. È adatta al collaudo del motore, "
    "ma non va considerata un feed XTB garantito in tempo reale o sincronizzato al tick."
)
