import streamlit as st
import json, re, uuid, hashlib, requests
from pathlib import Path
from datetime import datetime, timedelta, date
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

st.set_page_config(page_title="Gestionale Funds", page_icon="◈", layout="wide")

BASE = Path(__file__).parent
CLIENTS_FILE = BASE / "clients.json"
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = st.secrets.get("SUPABASE_SECRET_KEY", "")

def load_clients():
    try:
        return json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def euro(v):
    return f"€ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def clean_iban(v):
    return re.sub(r"\s+", "", v or "").upper()

def mask_iban(v):
    v = clean_iban(v)
    return v if len(v) <= 8 else v[:4] + " •••• •••• " + v[-4:]

def valid_iban(v):
    v = clean_iban(v)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", v):
        return False
    moved = v[4:] + v[:4]
    digits = "".join(str(ord(c)-55) if c.isalpha() else c for c in moved)
    rem = 0
    for d in digits:
        rem = (rem * 10 + int(d)) % 97
    return rem == 1

def add_workdays(d, n=5):
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d

def password_ok(pw):
    expected = st.secrets.get("APP_PASSWORD", "Funds2026")
    return hashlib.sha256(pw.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()

def headers(prefer=None):
    h = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h

def get_operations():
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        return []
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=headers(),
        params={"select":"*", "order":"created_at.desc"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def get_operation(op_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=headers(),
        params={"select":"*", "id":f"eq.{op_id}", "limit":1},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None

def insert_operation(payload):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=headers("return=representation"),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if data else payload

def update_status(op_id, status):
    payload = {"status": status}
    if status in ("Accreditato", "Completato"):
        payload["completed_at"] = datetime.utcnow().isoformat() + "Z"
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=headers("return=minimal"),
        params={"id":f"eq.{op_id}"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

def pretty_date(v):
    if not v: return ""
    try: return datetime.fromisoformat(v.replace("Z","+00:00")).strftime("%d/%m/%Y %H:%M")
    except: return str(v)

def pretty_due(v):
    if not v: return ""
    try: return date.fromisoformat(v[:10]).strftime("%d/%m/%Y")
    except: return str(v)

def mark_expired(ops):
    changed = False
    today = date.today()
    for op in ops:
        if op.get("status") == "In elaborazione" and op.get("estimated_date"):
            try:
                due = date.fromisoformat(op["estimated_date"][:10])
            except:
                continue
            if due < today:
                update_status(op["id"], "Da aggiornare")
                changed = True
    return changed

def build_receipt_pdf(op):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20,
                           textColor=colors.HexColor("#102F55"), alignment=TA_CENTER, spaceAfter=6)
    subtitle = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10,
                              textColor=colors.HexColor("#667085"), alignment=TA_CENTER, spaceAfter=18)
    note = ParagraphStyle("note", parent=styles["Normal"], fontSize=8.5,
                          textColor=colors.HexColor("#667085"), spaceBefore=14)
    story = [
        Paragraph("Gestionale Funds", title),
        Paragraph("Ricevuta della richiesta registrata", subtitle),
    ]
    rows = [
        ["Codice riferimento", op.get("id","")],
        ["Beneficiario", op.get("holder","")],
        ["IBAN", op.get("iban","")],
        ["Importo", euro(op.get("amount",0))],
        ["Causale", op.get("reason","")],
        ["Data richiesta", pretty_date(op.get("created_at"))],
        ["Data prevista di accredito", pretty_due(op.get("estimated_date"))],
        ["Stato", op.get("status","")],
    ]
    table = Table(rows, colWidths=[150, 340])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#F4F7FB")),
        ("TEXTCOLOR",(0,0),(0,-1),colors.HexColor("#102F55")),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(1,0),(1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),9.5),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#DDE4ED")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),9),
        ("RIGHTPADDING",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),8),
        ("BOTTOMPADDING",(0,0),(-1,-1),8),
    ]))
    story += [
        table,
        Spacer(1,10),
        Paragraph(
            "Documento generato dal Gestionale Funds sulla base dei dati registrati nella richiesta. "
            "La data riportata è la data prevista di accredito associata all'operazione.",
            note
        )
    ]
    doc.build(story)
    return buf.getvalue()

st.markdown("""
<style>
.stApp{background:#f4f7fb}
.block-container{padding-top:1.2rem;max-width:1400px}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#102f55,#174d82)}
[data-testid="stSidebar"] *{color:white}
.gf-title{font-size:2rem;font-weight:800;color:#102f55}
.gf-sub{color:#667085;margin-bottom:1rem}
[data-testid="stMetric"]{background:white;border:1px solid #e3e9f1;padding:16px;border-radius:16px}
div.stButton>button,div.stFormSubmitButton>button{background:#175b9c;color:white;border:0;border-radius:10px;min-height:44px;font-weight:700}
</style>
""", unsafe_allow_html=True)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "last_operation_id" not in st.session_state:
    st.session_state.last_operation_id = None

if not st.session_state.authenticated:
    st.markdown('<div class="gf-title">Gestionale Funds</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Accesso all’area gestionale</div>', unsafe_allow_html=True)
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        go = st.form_submit_button("ACCEDI", use_container_width=True)
    if go:
        if password_ok(pw):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Password non corretta.")
    st.stop()

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.error("Collegamento database non configurato.")
    st.stop()

clients = load_clients()
try:
    operations = get_operations()
except Exception as e:
    st.error("Impossibile leggere lo storico dal database.")
    st.caption(str(e))
    st.stop()

if mark_expired(operations):
    operations = get_operations()

with st.sidebar:
    st.markdown("## ◈ Gestionale Funds")
    page = st.radio("Menu", ["Dashboard","Nuova operazione","Clienti","Storico"], label_visibility="collapsed")
    st.divider()
    if st.button("Esci", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.last_operation_id = None
        st.rerun()

if page == "Dashboard":
    st.markdown('<div class="gf-title">Dashboard</div>', unsafe_allow_html=True)
    a,b,c,d = st.columns(4)
    a.metric("Clienti attivi", len([x for x in clients if x["status"]=="Attivo"]))
    b.metric("Somme associate", euro(sum(float(x["balance"]) for x in clients)))
    c.metric("Da gestire", sum(1 for x in operations if x.get("status") in ("In elaborazione","Da aggiornare")))
    d.metric("Totale ordinato", euro(sum(float(x.get("amount",0) or 0) for x in operations)))
    st.markdown("### Operazioni aperte")
    open_ops = [x for x in operations if x.get("status") in ("In elaborazione","Da aggiornare")]
    if open_ops:
        st.dataframe([{
            "ID":x["id"],"Data":pretty_date(x.get("created_at")),"Cliente":x["client_name"],
            "Importo":euro(x["amount"]),"Stato":x["status"],"Data prevista":pretty_due(x.get("estimated_date"))
        } for x in open_ops], use_container_width=True, hide_index=True)
    else:
        st.success("Nessuna operazione aperta.")

elif page == "Nuova operazione":
    st.markdown('<div class="gf-title">Nuova operazione</div>', unsafe_allow_html=True)

    if st.session_state.last_operation_id:
        try:
            last_op = get_operation(st.session_state.last_operation_id)
        except:
            last_op = None
        if last_op:
            st.success("Richiesta registrata correttamente.")
            st.download_button(
                "SCARICA RICEVUTA PDF",
                data=build_receipt_pdf(last_op),
                file_name=f"ricevuta_{last_op['id']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            st.divider()

    code = st.selectbox("Codice cliente", ["Seleziona"] + [x["code"] for x in clients])
    client = next((x for x in clients if x["code"]==code), None)
    if client:
        c1,c2,c3,c4 = st.columns(4)
        c1.text_input("Cliente",client["name"],disabled=True)
        c2.text_input("Banca",client["bank"],disabled=True)
        c3.text_input("Somma associata",euro(client["balance"]),disabled=True)
        c4.text_input("Stato",client["status"],disabled=True)

        amount = st.number_input("Importo da ordinare", min_value=0.01, max_value=float(client["balance"]),
                                 value=min(1000.0,float(client["balance"])), step=100.0)
        residual = float(client["balance"]) - float(amount)

        with st.form("operation_form"):
            x,y = st.columns(2)
            holder = x.text_input("Intestatario beneficiario")
            iban = y.text_input("IBAN beneficiario")
            x2,y2 = st.columns(2)
            x2.text_input("Importo selezionato",euro(amount),disabled=True)
            y2.text_input("Residuo previsto",euro(residual),disabled=True)
            reason = st.text_input("Causale")
            confirm = st.checkbox("Confermo i dati inseriti")
            submit = st.form_submit_button("INVIA",use_container_width=True)
        if submit:
            errors=[]
            if not holder.strip(): errors.append("Inserire l’intestatario.")
            if not valid_iban(iban): errors.append("L’IBAN non supera il controllo.")
            if not reason.strip(): errors.append("Inserire la causale.")
            if not confirm: errors.append("Confermare i dati prima dell’invio.")
            if errors:
                for e in errors: st.error(e)
            else:
                now = datetime.now()
                op = {
                    "id":f"GF-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
                    "client_code":client["code"],
                    "client_name":client["name"],
                    "bank":client["bank"],
                    "holder":holder.strip(),
                    "iban":clean_iban(iban),
                    "amount":round(float(amount),2),
                    "reason":reason.strip(),
                    "status":"In elaborazione",
                    "estimated_date":add_workdays(now.date(),5).isoformat(),
                }
                try:
                    saved = insert_operation(op)
                    st.session_state.last_operation_id = saved["id"]
                    st.rerun()
                except Exception as e:
                    st.error("Non è stato possibile registrare la richiesta.")
                    st.caption(str(e))
    else:
        st.info("Seleziona il codice cliente.")

elif page == "Clienti":
    st.markdown('<div class="gf-title">Clienti</div>', unsafe_allow_html=True)
    st.dataframe([{
        "Codice":x["code"],"Cliente":x["name"],"Banca":x["bank"],
        "Somma associata":euro(x["balance"]),"Stato":x["status"]
    } for x in clients], use_container_width=True, hide_index=True)

else:
    st.markdown('<div class="gf-title">Storico operazioni</div>', unsafe_allow_html=True)
    if operations:
        q = st.text_input("Cerca per cliente, codice o ID").strip().lower()
        filtered = operations if not q else [
            x for x in operations
            if q in x["client_name"].lower() or q in x["client_code"].lower() or q in x["id"].lower()
        ]
        st.dataframe([{
            "ID":x["id"],"Data":pretty_date(x.get("created_at")),"Codice":x["client_code"],
            "Cliente":x["client_name"],"Banca":x["bank"],"Beneficiario":x.get("holder",""),
            "IBAN":mask_iban(x.get("iban","")),"Importo":euro(x["amount"]),
            "Stato":x["status"],"Data prevista":pretty_due(x.get("estimated_date"))
        } for x in filtered], use_container_width=True, hide_index=True)

        st.markdown("### Ricevuta operazione")
        rid = st.selectbox("Seleziona operazione per ricevuta",[x["id"] for x in operations],key="receipt")
        rop = next((x for x in operations if x["id"]==rid),None)
        if rop:
            st.download_button(
                "SCARICA RICEVUTA PDF",
                data=build_receipt_pdf(rop),
                file_name=f"ricevuta_{rop['id']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        st.markdown("### Aggiorna stato")
        sid = st.selectbox("Operazione",[x["id"] for x in operations],key="status")
        sop = next((x for x in operations if x["id"]==sid),None)
        if sop:
            states=["In elaborazione","Da aggiornare","Accreditato","Completato","Annullato"]
            idx=states.index(sop.get("status","In elaborazione")) if sop.get("status") in states else 0
            new_status=st.selectbox("Nuovo stato",states,index=idx)
            if st.button("AGGIORNA STATO",use_container_width=True):
                try:
                    update_status(sid,new_status)
                    st.success("Stato aggiornato.")
                    st.rerun()
                except Exception as e:
                    st.error("Aggiornamento non riuscito.")
                    st.caption(str(e))
    else:
        st.info("Non risultano ancora operazioni registrate.")
