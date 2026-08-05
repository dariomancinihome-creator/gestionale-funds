
import streamlit as st
import json, re, uuid
from pathlib import Path
from datetime import datetime, timedelta

st.set_page_config(page_title="Gestionale Funds", page_icon="💼", layout="wide")
BASE = Path(__file__).parent
CLIENTS_FILE = BASE / "clients.json"
OPS_FILE = BASE / "operations.json"

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def euro(v):
    return f"€ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def clean_iban(v):
    return re.sub(r"\s+", "", v or "").upper()

def valid_iban(v):
    v = clean_iban(v)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", v):
        return False
    moved = v[4:] + v[:4]
    digits = "".join(str(ord(c)-55) if c.isalpha() else c for c in moved)
    rem = 0
    for ch in digits:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1

def add_workdays(d, n=5):
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d

clients = load(CLIENTS_FILE, [])
operations = load(OPS_FILE, [])

st.markdown("""
<style>
.block-container{padding-top:1.4rem}
[data-testid="stSidebar"]{background:#123b68}
[data-testid="stSidebar"] *{color:white}
.gf-title{font-size:2rem;font-weight:800;color:#123b68}
.gf-sub{color:#667085;margin-bottom:1rem}
.gf-ok{display:inline-block;background:#ecfdf3;color:#027a48;padding:7px 12px;border-radius:999px;font-weight:700}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 💼 Gestionale Funds")
    page = st.radio("Menu", ["Dashboard","Nuova operazione","Clienti","Storico"])
    st.caption("Area gestionale")

if page == "Dashboard":
    st.markdown('<div class="gf-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Riepilogo generale</div>', unsafe_allow_html=True)
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Clienti", len(clients))
    c2.metric("Somme associate", euro(sum(float(c["balance"]) for c in clients)))
    c3.metric("In elaborazione", sum(1 for o in operations if o.get("status")=="In elaborazione"))
    c4.metric("Operazioni", len(operations))
    st.subheader("Ultime operazioni")
    if operations:
        st.dataframe(list(reversed(operations[-10:])), use_container_width=True, hide_index=True)
    else:
        st.info("Nessuna operazione registrata.")

elif page == "Nuova operazione":
    st.markdown('<div class="gf-title">Nuova operazione</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Seleziona il cliente e inserisci i dati</div>', unsafe_allow_html=True)
    code = st.selectbox("Codice cliente", [""] + [c["code"] for c in clients])
    client = next((c for c in clients if c["code"] == code), None)

    if client:
        a,b,c,d = st.columns(4)
        a.text_input("Cliente", client["name"], disabled=True)
        b.text_input("Banca", client["bank"], disabled=True)
        c.text_input("Somma disponibile", euro(float(client["balance"])), disabled=True)
        d.text_input("Stato", client["status"], disabled=True)
        st.markdown('<span class="gf-ok">Cliente verificato</span>', unsafe_allow_html=True)

        with st.form("operation"):
            holder = st.text_input("Intestatario beneficiario")
            iban = st.text_input("IBAN beneficiario")
            amount = st.number_input("Importo da inviare", min_value=0.01, max_value=float(client["balance"]), step=100.0)
            st.text_input("Residuo previsto", euro(float(client["balance"]) - float(amount)), disabled=True)
            reason = st.text_input("Causale")
            submitted = st.form_submit_button("INVIA", use_container_width=True)

        if submitted:
            errors = []
            if not holder.strip(): errors.append("Inserire l'intestatario.")
            if not valid_iban(iban): errors.append("IBAN non valido.")
            if not reason.strip(): errors.append("Inserire la causale.")
            if errors:
                for err in errors: st.error(err)
            else:
                now = datetime.now()
                estimated = add_workdays(now.date(), 5)
                op = {
                    "id": f"GF-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
                    "data": now.strftime("%d/%m/%Y %H:%M"),
                    "codice": client["code"],
                    "cliente": client["name"],
                    "banca": client["bank"],
                    "intestatario": holder.strip(),
                    "iban": clean_iban(iban),
                    "importo": round(float(amount),2),
                    "causale": reason.strip(),
                    "stato": "In elaborazione",
                    "accredito_previsto": estimated.strftime("%d/%m/%Y")
                }
                operations.append(op)
                save(OPS_FILE, operations)
                st.success("Richiesta inviata")
                x,y,z = st.columns(3)
                x.metric("ID operazione", op["id"])
                y.metric("Stato", op["stato"])
                z.metric("Data prevista", op["accredito_previsto"])
    else:
        st.info("Seleziona un codice cliente.")

elif page == "Clienti":
    st.markdown('<div class="gf-title">Clienti</div>', unsafe_allow_html=True)
    st.dataframe(clients, use_container_width=True, hide_index=True)

else:
    st.markdown('<div class="gf-title">Storico</div>', unsafe_allow_html=True)
    if operations:
        st.dataframe(list(reversed(operations)), use_container_width=True, hide_index=True)
    else:
        st.info("Nessuna operazione registrata.")
