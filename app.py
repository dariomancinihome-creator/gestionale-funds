import streamlit as st
import json, re, uuid, hashlib, secrets, requests
from pathlib import Path
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
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
ROME = ZoneInfo("Europe/Rome")

def clients_load():
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
        rem = (rem*10 + int(d)) % 97
    return rem == 1

def add_workdays(d, n=5):
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d

def aml_update_window():
    today = datetime.now(ROME).date()
    min_date = add_workdays(today, 2)
    max_date = add_workdays(today, 3)
    return min_date, max_date

def admin_password_ok(pw):
    expected = st.secrets.get("APP_PASSWORD", "Funds2026")
    return hashlib.sha256(pw.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()

def api_headers(prefer=None):
    h = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h

def local_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ROME)
    except Exception:
        return None

def pretty_dt(value):
    dt = local_dt(value)
    return dt.strftime("%d/%m/%Y %H:%M") if dt else str(value or "")

def pretty_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except Exception:
        return str(value or "")

def get_operations(client_code=None):
    params = {"select":"*", "order":"created_at.desc"}
    if client_code:
        params["client_code"] = f"eq.{client_code}"
    r = requests.get(f"{SUPABASE_URL}/rest/v1/operations", headers=api_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def get_operation(op_id):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=api_headers(),
        params={"select":"*", "id":f"eq.{op_id}", "limit":1},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None

def insert_operation(payload):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=api_headers("return=representation"),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if data else payload

def update_status(op_id, status):
    payload = {"status":status}
    if status in ("Accreditato","Completato"):
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/operations",
        headers=api_headers("return=minimal"),
        params={"id":f"eq.{op_id}"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

def mark_expired(ops):
    changed = False
    today = datetime.now(ROME).date()
    for op in ops:
        if op.get("status") == "In elaborazione" and op.get("estimated_date"):
            try:
                due = date.fromisoformat(op["estimated_date"][:10])
            except Exception:
                continue
            if due < today:
                update_status(op["id"], "Da aggiornare")
                changed = True
    return changed

def pw_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200000).hex()
    return salt, digest

def get_client_access(code):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/client_access",
        headers=api_headers(),
        params={"select":"client_code,password_hash,salt,active,updated_at","client_code":f"eq.{code}","limit":1},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None

def list_client_access():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/client_access",
        headers=api_headers(),
        params={"select":"client_code,active,updated_at","order":"client_code.asc"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def set_client_password(code, password):
    salt, digest = pw_hash(password)
    payload = {
        "client_code":code,
        "password_hash":digest,
        "salt":salt,
        "active":True,
        "updated_at":datetime.now(timezone.utc).isoformat(),
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/client_access",
        headers=api_headers("resolution=merge-duplicates,return=minimal"),
        params={"on_conflict":"client_code"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

def set_client_active(code, active):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/client_access",
        headers=api_headers("return=minimal"),
        params={"client_code":f"eq.{code}"},
        json={"active":bool(active),"updated_at":datetime.now(timezone.utc).isoformat()},
        timeout=15,
    )
    r.raise_for_status()

def client_login_ok(code, password):
    access = get_client_access(code)
    if not access or not access.get("active", True):
        return False
    _, digest = pw_hash(password, salt=access["salt"])
    return secrets.compare_digest(digest, access["password_hash"])


def get_messages(client_code):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/messages",
        headers=api_headers(),
        params={
            "select":"id,client_code,sender,message,created_at",
            "client_code":f"eq.{client_code}",
            "order":"created_at.asc"
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def send_message(client_code, sender, message):
    message = (message or "").strip()
    if not message:
        return
    payload = {
        "client_code": client_code,
        "sender": sender,
        "message": message,
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/messages",
        headers=api_headers("return=minimal"),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

def position(client, ops):
    associated = float(client["balance"])
    ordered = sum(float(o.get("amount",0) or 0) for o in ops if o.get("status") != "Annullato")
    residual = max(associated - ordered, 0)
    open_ops = [o for o in ops if o.get("status") in ("In elaborazione","In valuta banca","In aggiornamento AML","Da aggiornare")]
    due_dates = []
    for o in open_ops:
        try:
            due_dates.append(date.fromisoformat(o["estimated_date"][:10]))
        except Exception:
            pass
    return associated, ordered, residual, open_ops, min(due_dates) if due_dates else None

def receipt_pdf(op):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20,
                           textColor=colors.HexColor("#102F55"), alignment=TA_CENTER, spaceAfter=6)
    sub = ParagraphStyle("s", parent=styles["Normal"], fontSize=10,
                         textColor=colors.HexColor("#667085"), alignment=TA_CENTER, spaceAfter=18)
    story = [Paragraph("Gestionale Funds", title), Paragraph("Ricevuta della richiesta registrata", sub)]
    rows = [
        ["Codice riferimento",op.get("id","")],
        ["Beneficiario",op.get("holder","")],
        ["IBAN",op.get("iban","")],
        ["Importo",euro(op.get("amount",0))],
        ["Causale",op.get("reason","")],
        ["Data richiesta",pretty_dt(op.get("created_at"))],
        ["Data prevista di accredito",pretty_date(op.get("estimated_date"))],
        ["Stato",op.get("status","")],
    ]

    if op.get("status") == "In aggiornamento AML":
        aml_min, aml_max = aml_update_window()
        rows.extend([
            ["Motivazione aggiornamento",
             "Aggiornamento verifiche antiriciclaggio - banca inviante extra SEPA"],
            ["Tempo stimato", "2-3 giorni lavorativi"],
            ["Finestra stimata",
             f"{aml_min.strftime('%d/%m/%Y')} - {aml_max.strftime('%d/%m/%Y')}"],
        ])

    table = Table(rows, colWidths=[150,340])
    table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#F4F7FB")),
        ("TEXTCOLOR",(0,0),(0,-1),colors.HexColor("#102F55")),
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(1,0),(1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),9.5),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#DDE4ED")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("PADDING",(0,0),(-1,-1),8),
    ]))
    story += [table, Spacer(1,10), Paragraph("Data e ora visualizzate secondo il fuso Europe/Rome.", styles["Normal"])]
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
.gf-pill{display:inline-block;background:#eaf8f2;color:#08734d;padding:6px 11px;border-radius:999px;font-weight:700}
[data-testid="stMetric"]{background:white;border:1px solid #e3e9f1;padding:16px;border-radius:16px}
div.stButton>button,div.stFormSubmitButton>button{background:#175b9c;color:white;border:0;border-radius:10px;min-height:44px;font-weight:700}
</style>
""", unsafe_allow_html=True)

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.error("Collegamento database non configurato.")
    st.stop()

for k,v in {"role":None,"client_code":None,"last_operation_id":None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

clients = clients_load()

if st.session_state.role is None:
    st.markdown('<div class="gf-title">Gestionale Funds</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Seleziona l’area di accesso</div>', unsafe_allow_html=True)
    tab_admin, tab_client = st.tabs(["Area Amministratore","Area Cliente FE"])

    with tab_admin:
        with st.form("admin_login"):
            pw = st.text_input("Password amministratore", type="password")
            go = st.form_submit_button("ACCEDI COME AMMINISTRATORE", use_container_width=True)
        if go:
            if admin_password_ok(pw):
                st.session_state.role = "admin"
                st.rerun()
            else:
                st.error("Password non corretta.")

    with tab_client:
        with st.form("client_login"):
            code = st.text_input("Codice cliente", placeholder="Es. FE-001").strip().upper()
            pw = st.text_input("Password personale", type="password")
            go = st.form_submit_button("ACCEDI ALLA POSIZIONE", use_container_width=True)
        if go:
            if not any(c["code"].upper() == code for c in clients):
                st.error("Codice cliente non riconosciuto.")
            else:
                try:
                    ok = client_login_ok(code, pw)
                except Exception:
                    st.error("Accesso cliente non ancora configurato.")
                    ok = False
                if ok:
                    st.session_state.role = "client"
                    st.session_state.client_code = code
                    st.rerun()
                elif any(c["code"].upper() == code for c in clients):
                    st.error("Password non corretta o accesso non configurato.")
    st.stop()

if st.session_state.role == "client":
    code = st.session_state.client_code
    client = next((c for c in clients if c["code"] == code), None)
    ops = get_operations(code)
    if mark_expired(ops):
        ops = get_operations(code)
    associated, ordered, residual, open_ops, next_due = position(client, ops)

    with st.sidebar:
        st.markdown("## ◈ Gestionale Funds")
        st.caption(f"Area cliente {code}")
        if st.button("Esci", use_container_width=True):
            st.session_state.role = None
            st.session_state.client_code = None
            st.rerun()

    st.markdown(f'<div class="gf-title">{client["name"]}</div>', unsafe_allow_html=True)
    st.markdown(f'<span class="gf-pill">{code} · {client["status"]}</span>', unsafe_allow_html=True)
    st.caption(f"Banca associata: {client['bank']}")
    a,b,c,d = st.columns(4)
    a.metric("Somma associata",euro(associated))
    b.metric("Totale ordinato",euro(ordered))
    c.metric("Residuo",euro(residual))
    d.metric("Operazioni aperte",len(open_ops))
    if next_due:
        st.info(f"Prossima data prevista: {next_due.strftime('%d/%m/%Y')}")

    aml_ops = [o for o in open_ops if o.get("status") == "In aggiornamento AML"]
    if aml_ops:
        aml_min, aml_max = aml_update_window()
        st.warning(
            "Aggiornamento verifiche antiriciclaggio – banca inviante extra SEPA\n\n"
            "**Tempo stimato:** 2–3 giorni lavorativi\n\n"
            f"**Finestra stimata:** {aml_min.strftime('%d/%m/%Y')} – {aml_max.strftime('%d/%m/%Y')}"
        )

    st.markdown("### Operazioni in corso")
    if open_ops:
        st.dataframe([{
            "Riferimento":o["id"],"Data":pretty_dt(o.get("created_at")),
            "Beneficiario":o.get("holder",""),"IBAN":mask_iban(o.get("iban","")),
            "Importo":euro(o["amount"]),"Stato":o["status"],
            "Data prevista":pretty_date(o.get("estimated_date")),
        } for o in open_ops], use_container_width=True, hide_index=True)
    else:
        st.success("Nessuna operazione aperta.")

    st.markdown("### Storico personale")
    if ops:
        st.dataframe([{
            "Riferimento":o["id"],"Data":pretty_dt(o.get("created_at")),
            "Beneficiario":o.get("holder",""),"IBAN":mask_iban(o.get("iban","")),
            "Importo":euro(o["amount"]),"Stato":o["status"],
            "Data prevista":pretty_date(o.get("estimated_date")),
        } for o in ops], use_container_width=True, hide_index=True)
        rid = st.selectbox("Ricevuta da scaricare",[o["id"] for o in ops])
        rop = next(o for o in ops if o["id"] == rid)
        st.download_button("SCARICA RICEVUTA PDF", receipt_pdf(rop),
                           file_name=f"ricevuta_{rid}.pdf", mime="application/pdf",
                           use_container_width=True)
    else:
        st.info("Non risultano operazioni registrate.")

    st.markdown("### Messaggi")
    st.caption("Scrivi all'amministrazione. La conversazione rimane memorizzata nella cronologia.")
    try:
        client_messages = get_messages(code)
    except Exception as e:
        st.error("Impossibile caricare i messaggi.")
        st.caption(str(e))
        client_messages = []

    if client_messages:
        for msg in client_messages:
            role = "user" if msg.get("sender") == "client" else "assistant"
            label = "Tu" if msg.get("sender") == "client" else "Amministrazione"
            with st.chat_message(role):
                st.markdown(f"**{label}** · {pretty_dt(msg.get('created_at'))}")
                st.write(msg.get("message",""))
    else:
        st.info("Nessun messaggio nella conversazione.")

    with st.form("client_message_form", clear_on_submit=True):
        new_message = st.text_area("Nuovo messaggio", placeholder="Scrivi qui il tuo messaggio...", height=100)
        send_client_message = st.form_submit_button("INVIA MESSAGGIO", use_container_width=True)
    if send_client_message:
        if not new_message.strip():
            st.warning("Scrivi un messaggio prima di inviare.")
        else:
            try:
                send_message(code, "client", new_message)
                st.success("Messaggio inviato.")
                st.rerun()
            except Exception as e:
                st.error("Invio non riuscito.")
                st.caption(str(e))

    st.stop()

ops = get_operations()
if mark_expired(ops):
    ops = get_operations()

with st.sidebar:
    st.markdown("## ◈ Gestionale Funds")
    page = st.radio("Menu",["Dashboard","Nuova operazione","Clienti","Storico","Messaggi","Accessi clienti"],label_visibility="collapsed")
    st.divider()
    st.caption("Area amministratore")
    if st.button("Esci", use_container_width=True):
        st.session_state.role = None
        st.session_state.last_operation_id = None
        st.rerun()

if page == "Dashboard":
    st.markdown('<div class="gf-title">Dashboard</div>', unsafe_allow_html=True)
    col1,col2,col3,col4 = st.columns(4)
    col1.metric("Clienti attivi",len([client for client in clients if client["status"]=="Attivo"]))
    col2.metric("Somme associate",euro(sum(float(client["balance"]) for client in clients)))
    col3.metric("Da gestire",sum(1 for o in ops if o.get("status") in ("In elaborazione","In valuta banca","In aggiornamento AML","Da aggiornare")))
    col4.metric("Totale ordinato",euro(sum(float(o.get("amount",0) or 0) for o in ops if o.get("status")!="Annullato")))
    open_ops = [o for o in ops if o.get("status") in ("In elaborazione","In valuta banca","In aggiornamento AML","Da aggiornare")]
    st.markdown("### Operazioni aperte")
    if open_ops:
        st.dataframe([{
            "ID":o["id"],"Data":pretty_dt(o.get("created_at")),"Cliente":o["client_name"],
            "Importo":euro(o["amount"]),"Stato":o["status"],"Data prevista":pretty_date(o.get("estimated_date"))
        } for o in open_ops],use_container_width=True,hide_index=True)
    else:
        st.success("Nessuna operazione aperta.")

elif page == "Nuova operazione":
    st.markdown('<div class="gf-title">Nuova operazione</div>', unsafe_allow_html=True)
    if st.session_state.last_operation_id:
        last = get_operation(st.session_state.last_operation_id)
        if last:
            st.success("Richiesta registrata correttamente.")
            st.download_button("SCARICA RICEVUTA PDF", receipt_pdf(last),
                               file_name=f"ricevuta_{last['id']}.pdf", mime="application/pdf",
                               use_container_width=True)
            st.divider()

    code = st.selectbox("Codice cliente",["Seleziona"]+[c["code"] for c in clients])
    client = next((c for c in clients if c["code"]==code),None)
    if client:
        client_ops = [o for o in ops if o.get("client_code")==code]
        associated, ordered, residual, _, _ = position(client, client_ops)
        c1,c2,c3,c4 = st.columns(4)
        c1.text_input("Cliente",client["name"],disabled=True)
        c2.text_input("Banca",client["bank"],disabled=True)
        c3.text_input("Somma associata",euro(associated),disabled=True)
        c4.text_input("Residuo attuale",euro(residual),disabled=True)
        if residual <= 0:
            st.warning("Non risulta disponibilità residua.")
        else:
            amount = st.number_input("Importo da ordinare",min_value=0.01,max_value=float(residual),
                                     value=min(1000.0,float(residual)),step=100.0)
            with st.form("op_form"):
                x,y = st.columns(2)
                holder = x.text_input("Intestatario beneficiario")
                iban = y.text_input("IBAN beneficiario")
                x2,y2 = st.columns(2)
                x2.text_input("Importo selezionato",euro(amount),disabled=True)
                y2.text_input("Residuo previsto",euro(residual-float(amount)),disabled=True)
                reason = st.text_input("Causale")
                confirm = st.checkbox("Confermo i dati inseriti")
                send = st.form_submit_button("INVIA",use_container_width=True)
            if send:
                errors=[]
                if not holder.strip(): errors.append("Inserire l’intestatario.")
                if not valid_iban(iban): errors.append("L’IBAN non supera il controllo.")
                if not reason.strip(): errors.append("Inserire la causale.")
                if not confirm: errors.append("Confermare i dati prima dell’invio.")
                if errors:
                    for e in errors: st.error(e)
                else:
                    now = datetime.now(ROME)
                    saved = insert_operation({
                        "id":f"GF-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
                        "client_code":client["code"],"client_name":client["name"],"bank":client["bank"],
                        "holder":holder.strip(),"iban":clean_iban(iban),"amount":round(float(amount),2),
                        "reason":reason.strip(),"status":"In elaborazione",
                        "estimated_date":add_workdays(now.date(),5).isoformat(),
                    })
                    st.session_state.last_operation_id = saved["id"]
                    st.rerun()
    else:
        st.info("Seleziona il codice cliente.")

elif page == "Clienti":
    st.markdown('<div class="gf-title">Clienti</div>', unsafe_allow_html=True)
    rows=[]
    for c in clients:
        cops=[o for o in ops if o.get("client_code")==c["code"]]
        a,o,r,opened,_=position(c,cops)
        rows.append({"Codice":c["code"],"Cliente":c["name"],"Banca":c["bank"],
                     "Somma associata":euro(a),"Ordinato":euro(o),"Residuo":euro(r),
                     "Aperte":len(opened),"Stato":c["status"]})
    st.dataframe(rows,use_container_width=True,hide_index=True)

elif page == "Storico":
    st.markdown('<div class="gf-title">Storico operazioni</div>', unsafe_allow_html=True)
    if ops:
        q=st.text_input("Cerca per cliente, codice o ID").strip().lower()
        filtered=ops if not q else [o for o in ops if q in o["client_name"].lower() or q in o["client_code"].lower() or q in o["id"].lower()]
        st.dataframe([{
            "ID":o["id"],"Data":pretty_dt(o.get("created_at")),"Codice":o["client_code"],
            "Cliente":o["client_name"],"Beneficiario":o.get("holder",""),"IBAN":mask_iban(o.get("iban","")),
            "Importo":euro(o["amount"]),"Stato":o["status"],"Data prevista":pretty_date(o.get("estimated_date"))
        } for o in filtered],use_container_width=True,hide_index=True)

        rid=st.selectbox("Ricevuta operazione",[o["id"] for o in ops],key="receipt")
        rop=next(o for o in ops if o["id"]==rid)
        st.download_button("SCARICA RICEVUTA PDF",receipt_pdf(rop),file_name=f"ricevuta_{rid}.pdf",
                           mime="application/pdf",use_container_width=True)

        sid=st.selectbox("Operazione da aggiornare",[o["id"] for o in ops],key="status")
        sop=next(o for o in ops if o["id"]==sid)
        states=["In elaborazione","In valuta banca","In aggiornamento AML","Da aggiornare","Accreditato","Completato","Annullato"]
        idx=states.index(sop.get("status")) if sop.get("status") in states else 0
        ns=st.selectbox("Nuovo stato",states,index=idx)
        if st.button("AGGIORNA STATO",use_container_width=True):
            update_status(sid,ns)
            st.rerun()
    else:
        st.info("Non risultano operazioni registrate.")

elif page == "Messaggi":
    st.markdown('<div class="gf-title">Messaggi clienti</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Apri una conversazione FE e rispondi al cliente</div>', unsafe_allow_html=True)

    message_code = st.selectbox(
        "Cliente",
        [c["code"] for c in clients],
        format_func=lambda code: f"{code} · {next((c['name'] for c in clients if c['code'] == code), code)}",
        key="messages_client_code",
    )
    message_client = next((c for c in clients if c["code"] == message_code), None)

    if message_client:
        st.caption(f"{message_client['name']} · {message_client['bank']}")

    try:
        thread = get_messages(message_code)
    except Exception as e:
        st.error("Impossibile caricare la conversazione.")
        st.caption(str(e))
        thread = []

    if thread:
        for msg in thread:
            role = "assistant" if msg.get("sender") == "admin" else "user"
            label = "Amministrazione" if msg.get("sender") == "admin" else message_client["name"]
            with st.chat_message(role):
                st.markdown(f"**{label}** · {pretty_dt(msg.get('created_at'))}")
                st.write(msg.get("message",""))
    else:
        st.info("Nessun messaggio per questo cliente.")

    with st.form("admin_message_form", clear_on_submit=True):
        admin_reply = st.text_area("Rispondi", placeholder="Scrivi la risposta...", height=100)
        send_admin_reply = st.form_submit_button("INVIA RISPOSTA", use_container_width=True)

    if send_admin_reply:
        if not admin_reply.strip():
            st.warning("Scrivi una risposta prima di inviare.")
        else:
            try:
                send_message(message_code, "admin", admin_reply)
                st.success("Risposta inviata.")
                st.rerun()
            except Exception as e:
                st.error("Invio non riuscito.")
                st.caption(str(e))

else:
    st.markdown('<div class="gf-title">Accessi clienti</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Imposta una password personale per ogni codice FE</div>', unsafe_allow_html=True)
    try:
        access=list_client_access()
    except Exception as e:
        st.error("Prima esegui lo script SQL client_access su Supabase.")
        st.caption(str(e))
        st.stop()
    amap={a["client_code"]:a for a in access}
    st.dataframe([{
        "Codice":c["code"],"Cliente":c["name"],
        "Configurato":"Sì" if c["code"] in amap else "No",
        "Attivo":"Sì" if amap.get(c["code"],{}).get("active") else "No",
        "Aggiornato":pretty_dt(amap.get(c["code"],{}).get("updated_at"))
    } for c in clients],use_container_width=True,hide_index=True)

    code=st.selectbox("Codice cliente",[c["code"] for c in clients],key="access_code")
    with st.form("pw_form"):
        p1=st.text_input("Nuova password personale",type="password")
        p2=st.text_input("Ripeti password",type="password")
        save=st.form_submit_button("SALVA PASSWORD",use_container_width=True)
    if save:
        if len(p1)<8:
            st.error("La password deve avere almeno 8 caratteri.")
        elif p1!=p2:
            st.error("Le password non coincidono.")
        else:
            set_client_password(code,p1)
            st.success(f"Password aggiornata per {code}.")
            st.rerun()

    if code in amap:
        if amap[code].get("active"):
            if st.button("DISATTIVA ACCESSO CLIENTE",use_container_width=True):
                set_client_active(code,False)
                st.rerun()
        else:
            if st.button("RIATTIVA ACCESSO CLIENTE",use_container_width=True):
                set_client_active(code,True)
                st.rerun()

