
import streamlit as st
import json
import re
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Gestionale Funds",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).parent
CLIENTS_FILE = BASE / "clients.json"
OPS_FILE = BASE / "operations.json"

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

def euro(value):
    return f"€ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def clean_iban(value):
    return re.sub(r"\s+", "", value or "").upper()

def valid_iban(value):
    value = clean_iban(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", value):
        return False
    moved = value[4:] + value[:4]
    digits = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in moved)
    remainder = 0
    for digit in digits:
        remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1

def add_workdays(start_date, number=5):
    result = start_date
    added = 0
    while added < number:
        result += timedelta(days=1)
        if result.weekday() < 5:
            added += 1
    return result

def password_ok(password):
    expected = st.secrets.get("APP_PASSWORD", "Funds2026")
    return hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()

st.markdown("""
<style>
:root {--navy:#102f55;--blue:#175b9c;--light:#f4f7fb;--line:#e3e9f1;--green:#16835b;}
.stApp {background:linear-gradient(180deg,#f2f6fb 0%,#fbfcfe 100%);}
.block-container {padding-top:1.2rem;max-width:1400px;}
[data-testid="stSidebar"] {background:linear-gradient(180deg,#102f55,#174d82);}
[data-testid="stSidebar"] * {color:white;}
[data-testid="stMetric"] {background:white;border:1px solid var(--line);padding:18px;border-radius:17px;box-shadow:0 7px 22px rgba(16,47,85,.06);}
.gf-brand {font-size:1.45rem;font-weight:850;letter-spacing:.2px;margin-bottom:1.6rem;}
.gf-title {font-size:2.05rem;font-weight:850;color:var(--navy);margin-bottom:.15rem;}
.gf-sub {font-size:.98rem;color:#667085;margin-bottom:1.4rem;}
.gf-panel {background:white;border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 8px 26px rgba(16,47,85,.06);margin-bottom:16px;}
.gf-ok {display:inline-block;background:#eaf8f2;color:#08734d;padding:7px 12px;border-radius:999px;font-weight:750;font-size:.84rem;}
.gf-status {display:inline-block;background:#eef4fb;color:#175b9c;padding:7px 12px;border-radius:999px;font-weight:750;font-size:.84rem;}
div.stButton > button, div.stFormSubmitButton > button {background:#175b9c;color:white;border:0;border-radius:11px;font-weight:750;min-height:46px;}
div.stButton > button:hover, div.stFormSubmitButton > button:hover {background:#102f55;color:white;}
[data-testid="stDataFrame"] {background:white;border-radius:15px;overflow:hidden;border:1px solid var(--line);}
.gf-login {max-width:430px;margin:8vh auto;background:white;border:1px solid var(--line);border-radius:22px;padding:30px;box-shadow:0 18px 50px rgba(16,47,85,.13);}
</style>
""", unsafe_allow_html=True)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown('<div class="gf-login">', unsafe_allow_html=True)
    st.markdown('<div class="gf-title">Gestionale Funds</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Accesso all’area gestionale</div>', unsafe_allow_html=True)
    with st.form("login_form"):
        password = st.text_input("Password", type="password")
        login = st.form_submit_button("ACCEDI", use_container_width=True)
    if login:
        if password_ok(password):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Password non corretta.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

clients = load_json(CLIENTS_FILE, [])
operations = load_json(OPS_FILE, [])

with st.sidebar:
    st.markdown('<div class="gf-brand">◈ Gestionale Funds</div>', unsafe_allow_html=True)
    page = st.radio("Navigazione", ["Dashboard", "Nuova operazione", "Clienti", "Storico"], label_visibility="collapsed")
    st.divider()
    st.caption("Sessione amministratore")
    if st.button("Esci", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

total_associated = sum(float(c["balance"]) for c in clients)
total_ordered = sum(float(o.get("amount", 0)) for o in operations)
pending = sum(1 for o in operations if o.get("status") == "In elaborazione")
today_str = datetime.now().date().strftime("%d/%m/%Y")
due_today = sum(1 for o in operations if o.get("estimated_date") == today_str)

if page == "Dashboard":
    st.markdown('<div class="gf-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Situazione complessiva del gestionale</div>', unsafe_allow_html=True)

    a,b,c,d = st.columns(4)
    a.metric("Clienti attivi", len([c for c in clients if c["status"] == "Attivo"]))
    b.metric("Somme associate", euro(total_associated))
    c.metric("In elaborazione", pending)
    d.metric("Totale ordinato", euro(total_ordered))

    st.markdown("### Ultime operazioni")
    if operations:
        display = []
        for op in reversed(operations[-10:]):
            display.append({
                "ID": op["id"],
                "Data": op["created_at"],
                "Cliente": op["client_name"],
                "Importo": euro(op["amount"]),
                "Stato": op["status"],
                "Data prevista": op["estimated_date"],
            })
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("Non risultano ancora operazioni registrate.")

elif page == "Nuova operazione":
    st.markdown('<div class="gf-title">Nuova operazione</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Ricerca cliente, inserimento beneficiario e definizione dell’importo</div>', unsafe_allow_html=True)

    code = st.selectbox("Codice cliente", ["Seleziona"] + [c["code"] for c in clients])
    client = next((c for c in clients if c["code"] == code), None)

    if client:
        st.markdown('<div class="gf-panel">', unsafe_allow_html=True)
        c1,c2,c3,c4 = st.columns(4)
        c1.text_input("Cliente", client["name"], disabled=True)
        c2.text_input("Banca", client["bank"], disabled=True)
        c3.text_input("Somma associata", euro(client["balance"]), disabled=True)
        c4.text_input("Stato", client["status"], disabled=True)
        st.markdown('<span class="gf-ok">Cliente verificato</span>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        amount = st.number_input(
            "Importo da ordinare",
            min_value=0.01,
            max_value=float(client["balance"]),
            value=min(1000.0, float(client["balance"])),
            step=100.0,
        )
        residual = float(client["balance"]) - float(amount)

        with st.form("operation_form"):
            x,y = st.columns(2)
            holder = x.text_input("Intestatario beneficiario")
            iban = y.text_input("IBAN beneficiario")
            x2,y2 = st.columns(2)
            x2.text_input("Importo selezionato", euro(amount), disabled=True)
            y2.text_input("Residuo previsto", euro(residual), disabled=True)
            reason = st.text_input("Causale")
            confirm = st.checkbox("Confermo i dati inseriti")
            submitted = st.form_submit_button("INVIA", use_container_width=True)

        if submitted:
            errors = []
            if not holder.strip():
                errors.append("Inserire l’intestatario.")
            if not valid_iban(iban):
                errors.append("L’IBAN non supera il controllo.")
            if not reason.strip():
                errors.append("Inserire la causale.")
            if not confirm:
                errors.append("Confermare i dati prima dell’invio.")

            if errors:
                for error in errors:
                    st.error(error)
            else:
                now = datetime.now()
                estimated = add_workdays(now.date(), 8)
                operation = {
                    "id": f"GF-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
                    "created_at": now.strftime("%d/%m/%Y %H:%M"),
                    "client_code": client["code"],
                    "client_name": client["name"],
                    "bank": client["bank"],
                    "holder": holder.strip(),
                    "iban": clean_iban(iban),
                    "amount": round(float(amount), 2),
                    "reason": reason.strip(),
                    "status": "In elaborazione",
                    "estimated_date": estimated.strftime("%d/%m/%Y"),
                }
                operations.append(operation)
                saved = save_json(OPS_FILE, operations)

                st.success("Richiesta inviata")
                r1,r2,r3,r4 = st.columns(4)
                r1.metric("ID operazione", operation["id"])
                r2.metric("Importo", euro(operation["amount"]))
                r3.metric("Stato", operation["status"])
                r4.metric("Data prevista", operation["estimated_date"])
                if not saved:
                    st.warning("La richiesta è visibile nella sessione corrente, ma il salvataggio locale non è persistente.")
    else:
        st.info("Seleziona il codice cliente per visualizzare i dati associati.")

elif page == "Clienti":
    st.markdown('<div class="gf-title">Clienti</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Anagrafica e somme associate</div>', unsafe_allow_html=True)
    display = [{
        "Codice": c["code"],
        "Cliente": c["name"],
        "Banca": c["bank"],
        "Somma associata": euro(c["balance"]),
        "Stato": c["status"],
    } for c in clients]
    st.dataframe(display, use_container_width=True, hide_index=True)

else:
    st.markdown('<div class="gf-title">Storico operazioni</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Elenco delle richieste registrate</div>', unsafe_allow_html=True)
    if operations:
        search = st.text_input("Cerca per cliente, codice o ID")
        filtered = operations
        if search.strip():
            q = search.lower().strip()
            filtered = [o for o in operations if q in o["client_name"].lower() or q in o["client_code"].lower() or q in o["id"].lower()]
        display = [{
            "ID": o["id"],
            "Data": o["created_at"],
            "Codice": o["client_code"],
            "Cliente": o["client_name"],
            "Banca": o["bank"],
            "Importo": euro(o["amount"]),
            "Stato": o["status"],
            "Data prevista": o["estimated_date"],
        } for o in reversed(filtered)]
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("Non risultano ancora operazioni registrate.")
