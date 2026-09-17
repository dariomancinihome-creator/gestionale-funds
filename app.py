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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

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

def parse_date_or_today(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return datetime.now(ROME).date()

def effective_credit_date(op):
    base_value = op.get("value_date_to") or op.get("value_date_from")
    if base_value:
        try:
            return date.fromisoformat(str(base_value)[:10]) + timedelta(days=1)
        except Exception:
            pass

    estimated = op.get("estimated_date")
    if estimated:
        try:
            return date.fromisoformat(str(estimated)[:10])
        except Exception:
            pass

    return None

def pretty_credit_date(op):
    d = effective_credit_date(op)
    return d.strftime("%d/%m/%Y") if d else ""

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

def update_status(op_id, status, comment=None, value_date_from=None, value_date_to=None):
    payload = {
        "status": status,
        "status_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if comment is not None:
        payload["status_comment"] = comment.strip() or None

    if value_date_from is not None:
        payload["value_date_from"] = value_date_from.isoformat() if hasattr(value_date_from, "isoformat") else value_date_from

    if value_date_to is not None:
        payload["value_date_to"] = value_date_to.isoformat() if hasattr(value_date_to, "isoformat") else value_date_to

    credit_base = value_date_to if value_date_to is not None else value_date_from
    if credit_base is not None:
        if isinstance(credit_base, str):
            credit_base = date.fromisoformat(credit_base[:10])
        payload["estimated_date"] = (credit_base + timedelta(days=1)).isoformat()

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


def get_operation_updates(operation_id=None, client_code=None):
    params = {
        "select":"id,operation_id,client_code,update_text,created_at",
        "order":"created_at.desc"
    }
    if operation_id:
        params["operation_id"] = f"eq.{operation_id}"
    if client_code:
        params["client_code"] = f"eq.{client_code}"
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/operation_updates",
        headers=api_headers(),
        params=params,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def add_operation_update(operation_id, client_code, update_text):
    update_text = (update_text or "").strip()
    if not update_text:
        return
    payload = {
        "operation_id": operation_id,
        "client_code": client_code,
        "update_text": update_text,
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/operation_updates",
        headers=api_headers("return=minimal"),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

def get_portfolio(client_code):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/investment_portfolios",
        headers=api_headers(),
        params={"select":"*", "client_code":f"eq.{client_code}", "limit":1},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None

def save_portfolio(client_code, asset, initial_capital, return_value, debt_payment,
                   available_funds, payment_due_date, next_payment_date):
    payload = {
        "client_code": client_code,
        "asset": (asset or "").strip(),
        "initial_capital": round(float(initial_capital or 0), 2),
        "return_value": round(float(return_value or 0), 2),
        "debt_payment": round(float(debt_payment or 0), 2),
        "available_funds": round(float(available_funds or 0), 2),
        "payment_due_date": payment_due_date.isoformat() if payment_due_date else None,
        "next_payment_date": next_payment_date.isoformat() if next_payment_date else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/investment_portfolios",
        headers=api_headers("resolution=merge-duplicates,return=minimal"),
        params={"on_conflict":"client_code"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

def position(client, ops):
    associated = float(client["balance"])
    ordered = sum(float(o.get("amount",0) or 0) for o in ops if o.get("status") != "Annullato")
    residual = max(associated - ordered, 0)
    open_ops = [o for o in ops if o.get("status") != "Annullato"]
    due_dates = []
    for o in open_ops:
        if o.get("status") in ("In elaborazione","In valuta banca","In aggiornamento AML","Da aggiornare"):
            d = effective_credit_date(o)
            if d:
                due_dates.append(d)
    return associated, ordered, residual, open_ops, min(due_dates) if due_dates else None

def receipt_pdf(op):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=30, leftMargin=30, topMargin=28, bottomMargin=28
    )
    styles = getSampleStyleSheet()

    navy = colors.HexColor("#0B3764")
    blue = colors.HexColor("#0B67B2")
    pale_blue = colors.HexColor("#F3F8FD")
    line = colors.HexColor("#CAD8E7")
    green = colors.HexColor("#0A7A48")
    pale_green = colors.HexColor("#E7F8EE")
    dark = colors.HexColor("#102F55")
    muted = colors.HexColor("#667085")

    title = ParagraphStyle(
        "gf_title", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=22, leading=25, textColor=dark, alignment=TA_LEFT, spaceAfter=2
    )
    subtitle = ParagraphStyle(
        "gf_subtitle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.5, leading=12, textColor=muted, alignment=TA_LEFT
    )
    section = ParagraphStyle(
        "gf_section", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=13, textColor=colors.white
    )
    cell = ParagraphStyle(
        "gf_cell", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8.6, leading=11, textColor=colors.HexColor("#172B4D")
    )
    cell_bold = ParagraphStyle(
        "gf_cell_bold", parent=cell, fontName="Helvetica-Bold", textColor=dark
    )
    tiny = ParagraphStyle(
        "gf_tiny", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.5, leading=10, textColor=muted
    )
    status_big = ParagraphStyle(
        "gf_status", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=17, leading=20, textColor=green
    )
    status_sub = ParagraphStyle(
        "gf_status_sub", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=12, textColor=dark
    )

    story = []

    # Header
    header = Table([
        [
            Paragraph("◇  Gestionale Funds", title),
            Paragraph(
                f"<b>Documento generato il</b><br/>{datetime.now(ROME).strftime('%d/%m/%Y - %H:%M')}<br/>"
                f"<b>ID ricevuta:</b> {op.get('id','')}",
                tiny
            )
        ]
    ], colWidths=[350, 185])
    header.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("ALIGN",(1,0),(1,0),"RIGHT"),
        ("BOTTOMPADDING",(0,0),(-1,-1),10),
        ("LINEBELOW",(0,0),(-1,-1),1.2,navy),
    ]))
    story += [
        header,
        Spacer(1,12),
        Paragraph("RICEVUTA DI OPERAZIONE", ParagraphStyle(
            "receipt_heading", parent=title, fontSize=18, leading=21
        )),
        Paragraph("Documento di riepilogo dell’operazione registrata nel Gestionale Funds.", subtitle),
        Spacer(1,12),
    ]

    # Status banner
    completed = pretty_date(op.get("completed_at")) if op.get("completed_at") else "—"
    status_label = "PAGAMENTO ESEGUITO" if op.get("status") == "Pagamento eseguito" else str(op.get("status","")).upper()
    status_banner = Table([
        [
            Paragraph(f"✓  {status_label}", status_big),
            Paragraph(f"<b>Data completamento</b><br/><font size='15'><b>{completed}</b></font>", status_sub)
        ]
    ], colWidths=[365,170], rowHeights=[58])
    status_banner.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),pale_green),
        ("BOX",(0,0),(-1,-1),0.8,colors.HexColor("#58B985")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(0,0),18),
        ("LEFTPADDING",(1,0),(1,0),18),
        ("LINEBEFORE",(1,0),(1,0),0.8,colors.HexColor("#58B985")),
    ]))
    story += [status_banner, Spacer(1,14)]

    # Main details
    detail_rows = [
        [Paragraph("DETTAGLI OPERAZIONE", section), ""],
        [Paragraph("Cliente", cell_bold), Paragraph(str(op.get("client_name") or op.get("holder") or ""), cell)],
        [Paragraph("Codice cliente", cell_bold), Paragraph(str(op.get("client_code","")), cell)],
        [Paragraph("Banca ordinante", cell_bold), Paragraph("WELLS FARGO BANK N.A", cell)],
        [Paragraph("Indirizzo banca", cell_bold), Paragraph("420 Montgomery Street, San Francisco, CA 94104 – USA", cell)],
        [Paragraph("Account Number", cell_bold), Paragraph("3986639171", cell)],
        [Paragraph("User Reference", cell_bold), Paragraph("210716472797534H01", cell)],
        [Paragraph("Codice riferimento operazione", cell_bold), Paragraph(str(op.get("id","")), cell)],
        [Paragraph("Beneficiario", cell_bold), Paragraph(str(op.get("holder","")), cell)],
        [Paragraph("IBAN (banca ricevente)", cell_bold), Paragraph(str(op.get("iban","")), cell)],
        [Paragraph("Importo", cell_bold), Paragraph(f"<b>{euro(op.get('amount',0))}</b>", cell)],
        [Paragraph("Causale", cell_bold), Paragraph(str(op.get("reason","")), cell)],
        [Paragraph("Data richiesta", cell_bold), Paragraph(pretty_dt(op.get("created_at")), cell)],
        [Paragraph("Data prevista di accredito", cell_bold), Paragraph(pretty_credit_date(op), cell)],
        [Paragraph("Data completamento", cell_bold), Paragraph(completed, cell)],
        [Paragraph("Stato operazione", cell_bold), Paragraph("Pagamento eseguito" if op.get("status") == "Pagamento eseguito" else str(op.get("status","")), cell)],
    ]
    if op.get("value_date_from") or op.get("value_date_to"):
        if op.get("value_date_from") and op.get("value_date_to") and op.get("value_date_from") != op.get("value_date_to"):
            value_text = f"{pretty_date(op.get('value_date_from'))} – {pretty_date(op.get('value_date_to'))}"
        else:
            value_text = pretty_date(op.get("value_date_from") or op.get("value_date_to"))
        detail_rows.append([Paragraph("Valuta", cell_bold), Paragraph(value_text, cell)])

    details = Table(detail_rows, colWidths=[190,345])
    details.setStyle(TableStyle([
        ("SPAN",(0,0),(1,0)),
        ("BACKGROUND",(0,0),(1,0),navy),
        ("TEXTCOLOR",(0,0),(1,0),colors.white),
        ("LEFTPADDING",(0,0),(1,0),10),
        ("TOPPADDING",(0,0),(1,0),6),
        ("BOTTOMPADDING",(0,0),(1,0),6),
        ("BACKGROUND",(0,1),(0,-1),pale_blue),
        ("GRID",(0,1),(-1,-1),0.45,line),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,1),(-1,-1),8),
        ("RIGHTPADDING",(0,1),(-1,-1),8),
        ("TOPPADDING",(0,1),(-1,-1),5),
        ("BOTTOMPADDING",(0,1),(-1,-1),5),
    ]))
    story += [details, Spacer(1,14)]

    # Wells Fargo update history. Old status_comment is intentionally not shown here.
    try:
        receipt_updates = get_operation_updates(operation_id=op.get("id"))
    except Exception:
        receipt_updates = []

    updates_rows = [
        [Paragraph("AGGIORNAMENTI STATO DA WELLS FARGO", section), ""],
        [Paragraph(
            "Registro delle comunicazioni relative allo stato dell’operazione tra banca inviante e banca ricevente.",
            tiny
        ), ""],
        [Paragraph("<b>Data e ora</b>", cell), Paragraph("<b>Aggiornamento</b>", cell)],
    ]
    if receipt_updates:
        for upd in reversed(receipt_updates):
            updates_rows.append([
                Paragraph(pretty_dt(upd.get("created_at")), cell),
                Paragraph(str(upd.get("update_text","")), cell)
            ])
    else:
        updates_rows.append([
            Paragraph("—", cell),
            Paragraph("Nessun aggiornamento amministrativo registrato.", cell)
        ])

    updates = Table(updates_rows, colWidths=[135,400])
    updates.setStyle(TableStyle([
        ("SPAN",(0,0),(1,0)),
        ("BACKGROUND",(0,0),(1,0),navy),
        ("TEXTCOLOR",(0,0),(1,0),colors.white),
        ("SPAN",(0,1),(1,1)),
        ("BACKGROUND",(0,1),(1,1),pale_blue),
        ("BACKGROUND",(0,2),(1,2),colors.HexColor("#E8F0F8")),
        ("GRID",(0,2),(-1,-1),0.45,line),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),5),
        ("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story += [updates, Spacer(1,14)]

    # Informational note
    note = Table([[
        Paragraph(
            "<b>Nota informativa</b><br/>"
            "Gli aggiornamenti vengono registrati dall’amministrazione del Gestionale Funds sulla base "
            "delle comunicazioni relative alla banca inviante e alla banca ricevente. "
            "Per eventuali chiarimenti è possibile utilizzare la sezione Messaggi.",
            ParagraphStyle("note", parent=cell, fontSize=8, leading=11)
        )
    ]], colWidths=[535])
    note.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),pale_blue),
        ("BOX",(0,0),(-1,-1),0.6,line),
        ("LEFTPADDING",(0,0),(-1,-1),12),
        ("RIGHTPADDING",(0,0),(-1,-1),12),
        ("TOPPADDING",(0,0),(-1,-1),9),
        ("BOTTOMPADDING",(0,0),(-1,-1),9),
    ]))
    story += [
        note, Spacer(1,16),
        Table([[
            Paragraph("<b>Gestionale Funds</b><br/>Sicurezza. Controllo. Risultati.", tiny),
            Paragraph("Documento generato automaticamente.<br/>La presente ricevuta ha valore informativo.", tiny)
        ]], colWidths=[300,235], style=[
            ("LINEABOVE",(0,0),(-1,-1),1,navy),
            ("TOPPADDING",(0,0),(-1,-1),8),
            ("ALIGN",(1,0),(1,0),"RIGHT"),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
        ])
    ]

    doc.build(story)
    return buf.getvalue()

st.markdown("""
<style>
:root{
  --gf-navy:#0b3764;
  --gf-blue:#0b67b2;
  --gf-bg:#f3f7fb;
  --gf-line:#d8e3ef;
  --gf-text:#132a45;
  --gf-muted:#6b7b8e;
  --gf-green:#168451;
  --gf-green-bg:#e7f7ee;
}
.stApp{background:var(--gf-bg);color:var(--gf-text)}
.block-container{padding-top:1.35rem;padding-bottom:2rem;max-width:1280px}
[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#0b3764 0%,#0a315a 100%);
  border-right:0;
}
[data-testid="stSidebar"] .block-container{padding-top:1.35rem}
[data-testid="stSidebar"] *{color:#fff}
[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.16)}
[data-testid="stSidebar"] [role="radiogroup"] label{
  padding:.45rem .55rem;border-radius:8px;margin:.08rem 0;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{
  background:rgba(255,255,255,.09);
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:#0b67b2;
}
.gf-title{
  font-size:2rem;font-weight:800;letter-spacing:-.02em;color:var(--gf-navy);
  margin-bottom:.15rem
}
.gf-sub{color:var(--gf-muted);margin-bottom:1.1rem}
.gf-pill{
  display:inline-block;background:#dceeff;color:#0b5a9e;padding:6px 12px;
  border-radius:999px;font-weight:800;font-size:.84rem
}
[data-testid="stMetric"]{
  background:#fff;border:1px solid var(--gf-line);padding:16px 18px;
  border-radius:12px;box-shadow:0 1px 2px rgba(16,47,85,.03)
}
[data-testid="stMetricLabel"]{color:var(--gf-muted)}
[data-testid="stMetricValue"]{color:var(--gf-navy);font-weight:800}
div[data-testid="stDataFrame"]{
  background:#fff;border:1px solid var(--gf-line);border-radius:10px;
  overflow:hidden
}
div.stButton>button,div.stFormSubmitButton>button,
div.stDownloadButton>button{
  background:#0b67b2;color:#fff;border:0;border-radius:7px;
  min-height:42px;font-weight:750
}
div.stButton>button:hover,div.stFormSubmitButton>button:hover,
div.stDownloadButton>button:hover{
  background:#095a9c;color:#fff;border:0
}
div[data-baseweb="select"]>div, textarea, input{
  border-color:var(--gf-line)!important;border-radius:7px!important
}
[data-testid="stAlert"]{border-radius:9px}
[data-testid="stChatMessage"]{
  background:#fff;border:1px solid var(--gf-line);border-radius:10px;
  padding:.8rem 1rem;margin-bottom:.65rem
}
h3{
  color:var(--gf-navy)!important;font-weight:800!important;
  margin-top:1.25rem!important
}
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
        st.markdown("## ◇ Gestionale Funds")
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

    st.markdown("### Le mie transazioni")
    if ops:
        st.dataframe([{
            "Data": pretty_date(o.get("completed_at") or o.get("created_at")),
            "Importo": euro(o["amount"]),
            "Stato": "Pagamento eseguito" if o.get("status") == "Pagamento eseguito" else o.get("status",""),
            "Data completamento": pretty_date(o.get("completed_at")) if o.get("completed_at") else "—",
        } for o in ops], use_container_width=True, hide_index=True)

        rid = st.selectbox(
            "Ricevuta da scaricare",
            [o["id"] for o in ops],
            format_func=lambda oid: next(
                (f"{o.get('client_name','')} · {euro(o.get('amount',0))} · {pretty_date(o.get('completed_at') or o.get('created_at'))}"
                 for o in ops if o["id"] == oid),
                oid
            ),
        )
        rop = next(o for o in ops if o["id"] == rid)
        st.download_button(
            "SCARICA RICEVUTA PDF",
            receipt_pdf(rop),
            file_name=f"ricevuta_{rid}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    else:
        st.info("Non risultano transazioni registrate.")

    st.markdown("### Aggiornamenti sulla mia operazione")
    st.caption("Registro delle comunicazioni relative allo stato dell’operazione tra banca inviante e banca ricevente.")
    try:
        client_updates = get_operation_updates(client_code=code)
    except Exception:
        client_updates = []

    if client_updates:
        op_map = {o["id"]: o for o in ops}
        for upd in client_updates:
            linked = op_map.get(upd.get("operation_id"), {})
            st.markdown(
                f"**{pretty_dt(upd.get('created_at'))}**  \\n"
                f"{upd.get('update_text','')}  \\n"
                f"<small>{euro(linked.get('amount',0)) if linked else ''}</small>",
                unsafe_allow_html=True
            )
            st.divider()
    else:
        st.info("Nessun aggiornamento amministrativo disponibile.")

    st.markdown("### Portafoglio investimenti")
    try:
        portfolio = get_portfolio(code)
    except Exception:
        portfolio = None

    if portfolio:
        p1,p2,p3,p4 = st.columns(4)
        p1.metric("Capitale iniziale", euro(portfolio.get("initial_capital",0)))
        p2.metric("Rendita", euro(portfolio.get("return_value",0)))
        p3.metric("Fondi disponibili", euro(portfolio.get("available_funds",0)))
        portfolio_total = (
            float(portfolio.get("initial_capital",0) or 0) +
            float(portfolio.get("available_funds",0) or 0)
        )
        p4.metric("Totale", euro(portfolio_total))
        st.write(f"**Asset:** {portfolio.get('asset','')}")
        st.write(f"**Quota versamento a debito:** {euro(portfolio.get('debt_payment',0))}")
        st.write(f"**Data scadenza versamento:** {pretty_date(portfolio.get('payment_due_date'))}")
        st.write(f"**Prossima data versamento:** {pretty_date(portfolio.get('next_payment_date'))}")
    else:
        st.info("Portafoglio investimenti non ancora configurato.")

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
    st.markdown("## ◇ Gestionale Funds")
    page = st.radio("Menu",["Dashboard","Nuova operazione","Clienti","Portafoglio investimenti","Storico transazioni","Aggiornamenti stato da Wells Fargo","Messaggi","Accessi clienti"],label_visibility="collapsed")
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
    col3.metric("Transazioni",sum(1 for o in ops if o.get("status") != "Annullato"))
    col4.metric("Totale ordinato",euro(sum(float(o.get("amount",0) or 0) for o in ops if o.get("status")!="Annullato")))
    open_ops = [o for o in ops if o.get("status") != "Annullato"]
    st.markdown("### Elenco transazioni")
    if open_ops:
        st.dataframe([{
            "ID":o["id"],"Data":pretty_dt(o.get("created_at")),"Cliente":o["client_name"],
            "Importo":euro(o["amount"]),"Stato":o["status"],
            "Valuta da":pretty_date(o.get("value_date_from")),
            "Valuta a":pretty_date(o.get("value_date_to")),
            "Commento":o.get("status_comment",""),
            "Data prevista":pretty_credit_date(o)
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
                value_date = st.date_input(
                    "Data valuta prevista",
                    value=datetime.now(ROME).date(),
                    format="DD/MM/YYYY",
                    help="La data richiesta viene registrata automaticamente. La data prevista di accredito sarà il giorno successivo alla data valuta."
                )
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
                        "reason":reason.strip(),"status":"Pagamento eseguito",
                        "value_date_from":value_date.isoformat(),
                        "value_date_to":value_date.isoformat(),
                        "estimated_date":(value_date + timedelta(days=1)).isoformat(),
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

elif page == "Portafoglio investimenti":
    st.markdown('<div class="gf-title">Portafoglio investimenti</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Dati compilabili esclusivamente dall’amministratore</div>', unsafe_allow_html=True)

    pcode = st.selectbox(
        "Cliente",
        [c["code"] for c in clients],
        format_func=lambda code: f"{code} · {next((c['name'] for c in clients if c['code'] == code), code)}",
        key="portfolio_client",
    )
    try:
        current_portfolio = get_portfolio(pcode)
    except Exception as e:
        st.error("Prima esegui lo script SQL del Portafoglio investimenti su Supabase.")
        st.caption(str(e))
        st.stop()

    with st.form("portfolio_form"):
        asset = st.text_input("Asset", value=(current_portfolio or {}).get("asset",""))
        c1,c2,c3 = st.columns(3)
        initial_capital = c1.number_input("Capitale iniziale", min_value=0.0,
            value=float((current_portfolio or {}).get("initial_capital",0) or 0), step=100.0)
        return_value = c2.number_input("Rendita", min_value=0.0,
            value=float((current_portfolio or {}).get("return_value",0) or 0), step=10.0)
        debt_payment = c3.number_input("Quota versamento a debito", min_value=0.0,
            value=float((current_portfolio or {}).get("debt_payment",0) or 0), step=10.0)

        available_funds = st.number_input(
            "Liquidità / Fondi disponibili",
            min_value=0.0,
            value=float((current_portfolio or {}).get("available_funds",0) or 0),
            step=100.0
        )
        portfolio_total = float(initial_capital) + float(available_funds)
        st.metric("Totale portafoglio (Fondi disponibili + Capitale iniziale)", euro(portfolio_total))

        d1,d2 = st.columns(2)
        due_default = parse_date_or_today((current_portfolio or {}).get("payment_due_date"))
        next_default = parse_date_or_today((current_portfolio or {}).get("next_payment_date"))
        payment_due_date = d1.date_input("Data scadenza versamento", value=due_default)
        next_payment_date = d2.date_input("Prossima data versamento", value=next_default)

        save_pf = st.form_submit_button("SALVA PORTAFOGLIO", use_container_width=True)

    if save_pf:
        if not asset.strip():
            st.error("Inserisci l’asset.")
        else:
            save_portfolio(
                pcode, asset, initial_capital, return_value, debt_payment,
                available_funds, payment_due_date, next_payment_date
            )
            st.success(f"Portafoglio {pcode} aggiornato.")
            st.rerun()

elif page == "Storico transazioni":
    st.markdown('<div class="gf-title">Storico transazioni</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Elenco delle operazioni registrate e concluse</div>', unsafe_allow_html=True)

    if ops:
        q = st.text_input("Cerca per nome e cognome").strip().lower()
        filtered = ops if not q else [
            o for o in ops if q in (o.get("client_name") or "").lower()
        ]

        st.dataframe([{
            "Data": pretty_date(o.get("completed_at") or o.get("created_at")),
            "Cliente": o.get("client_name",""),
            "Importo": euro(o.get("amount",0)),
            "Stato finale": "Pagamento eseguito" if o.get("status") == "Pagamento eseguito" else o.get("status",""),
            "Data completamento": pretty_date(o.get("completed_at")) if o.get("completed_at") else "—",
        } for o in filtered], use_container_width=True, hide_index=True)

        rid = st.selectbox(
            "Ricevuta",
            [o["id"] for o in ops],
            format_func=lambda oid: next(
                (f"{o.get('client_name','')} · {euro(o.get('amount',0))}" for o in ops if o["id"] == oid),
                oid
            ),
            key="receipt_history"
        )
        rop = next(o for o in ops if o["id"] == rid)
        st.download_button(
            "SCARICA RICEVUTA PDF",
            receipt_pdf(rop),
            file_name=f"ricevuta_{rid}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    else:
        st.info("Non risultano transazioni registrate.")

elif page == "Aggiornamenti stato da Wells Fargo":
    st.markdown('<div class="gf-title">Aggiornamenti stato da Wells Fargo</div>', unsafe_allow_html=True)
    st.caption("Registro delle comunicazioni relative allo stato dell’operazione tra banca inviante e banca ricevente.")

    if not ops:
        st.info("Non risultano operazioni registrate.")
    else:
        update_op_id = st.selectbox(
            "Seleziona operazione",
            [o["id"] for o in ops],
            format_func=lambda oid: next(
                (f"{o.get('client_name','')} · {euro(o.get('amount',0))} · {pretty_date(o.get('completed_at') or o.get('created_at'))}"
                 for o in ops if o["id"] == oid),
                oid
            ),
            key="wf_update_operation"
        )
        selected_op = next(o for o in ops if o["id"] == update_op_id)

        with st.form("wf_update_form", clear_on_submit=True):
            update_text = st.text_area(
                "Nuovo aggiornamento",
                placeholder="Inserisci l’aggiornamento da registrare...",
                height=120
            )
            save_update = st.form_submit_button("SALVA AGGIORNAMENTO", use_container_width=True)

        if save_update:
            if not update_text.strip():
                st.warning("Scrivi l’aggiornamento prima di salvarlo.")
            else:
                add_operation_update(
                    selected_op["id"],
                    selected_op["client_code"],
                    update_text
                )
                st.success("Aggiornamento registrato. Sarà visibile nell’area FE e nella ricevuta.")
                st.rerun()

        st.markdown("### Ultimi aggiornamenti inseriti")
        try:
            recent_updates = get_operation_updates()
        except Exception as e:
            st.error("Impossibile caricare gli aggiornamenti.")
            st.caption(str(e))
            recent_updates = []

        if recent_updates:
            op_map = {o["id"]: o for o in ops}
            st.dataframe([{
                "Data e ora": pretty_dt(u.get("created_at")),
                "Cliente": op_map.get(u.get("operation_id"),{}).get("client_name",""),
                "Importo": euro(op_map.get(u.get("operation_id"),{}).get("amount",0)),
                "Aggiornamento": u.get("update_text",""),
            } for u in recent_updates], use_container_width=True, hide_index=True)
        else:
            st.info("Nessun aggiornamento ancora registrato.")

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
