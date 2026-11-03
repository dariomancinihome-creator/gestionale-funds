"""CREDIT DESK 1.0 — applicazione Streamlit, Supabase Auth + RLS.
Nessuna funzione bancaria: le informazioni sono inserite dall'amministrazione.
"""
import html
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken

st.set_page_config(page_title="CREDIT DESK", page_icon="🏦", layout="wide")
URL = st.secrets.get("SUPABASE_URL", "").rstrip("/")
ANON = st.secrets.get("SUPABASE_PUBLISHABLE_KEY", "") or st.secrets.get("SUPABASE_ANON_KEY", "")
FERNET_KEY = st.secrets.get("CREDIT_DESK_FERNET_KEY", "")
PRIVACY_URL = st.secrets.get("CREDIT_DESK_PRIVACY_URL", "").strip()
TZ = ZoneInfo("Europe/Madrid")
REQUEST_STATES = ["Ricevuta", "In valutazione", "Soluzione disponibile", "Archiviata"]
LOAN_STATES = ["Deliberata", "Documenti in verifica", "Pronta per erogazione", "Erogazione disposta", "Accredito confermato", "Sospesa", "Annullata"]
HOLIDAYS = set()  # Inserire YYYY-MM-DD delle festività applicabili alla sede del finanziatore.

st.markdown("""<style>
:root {--navy:#10243b; --navy2:#173b58; --gold:#c8a96b; --ink:#172d46; --muted:#748396; --line:#e0e7ef;}
.stApp {background:radial-gradient(circle at 93% 0%,#e3ecf3 0%,#f5f7fb 42%,#f5f7fb 100%);color:var(--ink);}
.block-container {padding-top:2rem; padding-bottom:3rem; max-width:1200px;}
[data-testid="stHeader"] {background:transparent;}
h1,h2,h3 {color:var(--navy)!important;letter-spacing:-.025em;}
h1 {font-weight:800!important;}
[data-testid="stSidebar"] {background:linear-gradient(160deg,#0c2035 0%,#173952 100%);}
[data-testid="stSidebar"] * {color:#f7f8fa;}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:rgba(203,173,112,.15);border-radius:9px;}
[data-testid="stMetric"] {background:#fff;padding:16px 19px;border:1px solid var(--line);border-top:3px solid var(--gold);border-radius:14px;box-shadow:0 8px 24px rgba(16,36,59,.03);}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{background:var(--navy);border:1px solid var(--navy);color:white;border-radius:10px;font-weight:700;min-height:44px;}
.stButton>button[kind="primary"]:hover,.stFormSubmitButton>button[kind="primary"]:hover{background:#244968;border-color:#244968;color:#fff;}
.stFormSubmitButton>button,.stButton>button{border-radius:10px;min-height:42px;}
[data-testid="stForm"] {background:#fff;border:1px solid var(--line);border-radius:16px;padding:22px 24px 18px;box-shadow:0 14px 40px rgba(16,36,59,.055);}
[data-baseweb="input"]>div,[data-baseweb="select"]>div,textarea{background:#fff!important;border-radius:9px!important;}
button[data-baseweb="tab"] {font-weight:700;padding:14px 20px;color:#64758b;}
button[data-baseweb="tab"][aria-selected="true"] {color:var(--navy)!important;}
[data-baseweb="tab-highlight"] {background:var(--gold)!important;}
.cdbrand {font-weight:850;letter-spacing:.09em;font-size:1.42rem;color:var(--navy);display:flex;align-items:center;gap:10px;}
.cdbrand-mark {display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;background:var(--navy);color:var(--gold);border-radius:11px;font-weight:900;font-size:1rem;letter-spacing:0;}
.cdsub {color:var(--muted);font-size:.87rem;letter-spacing:.015em;}
.cd-hero {border:1px solid #d9e3ec;box-shadow:0 16px 45px rgba(16,36,59,.06);background:linear-gradient(112deg,#ffffff 0%,#f1f5f9 72%,#e8eff5 100%);padding:26px 30px 24px;border-radius:20px;margin:0 0 22px;position:relative;overflow:hidden;}
.cd-hero:after {content:'';position:absolute;right:-70px;top:-90px;width:245px;height:245px;border-radius:50%;border:38px solid rgba(200,169,107,.13);pointer-events:none;}
.cd-kicker{font-size:.76rem;text-transform:uppercase;letter-spacing:.14em;font-weight:800;color:#987643;margin-bottom:12px;}
.cd-headline{font-size:clamp(1.65rem,3.3vw,2.55rem);font-weight:850;line-height:1.14;color:var(--navy);letter-spacing:-.035em;margin:6px 0 12px;max-width:740px;}
.cd-intro{font-size:1rem;color:#65768a;line-height:1.6;max-width:670px;margin:0;}
.cdprogress{height:19px;border-radius:20px;background:#dfe7e9;overflow:hidden}
.cdprogressbar{height:19px;border-radius:20px;background:linear-gradient(90deg,#0f8b4c,#42bf75)}
.cdcard{background:white;border:1px solid var(--line);border-radius:13px;padding:18px;margin:10px 0}
@media (max-width:650px) {.block-container{padding-top:1.2rem}.cd-hero{padding:22px 18px}[data-testid="stForm"]{padding:14px 12px;}}
</style>""", unsafe_allow_html=True)

if not URL or not ANON:
    st.error("Configurare SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY (oppure SUPABASE_ANON_KEY) nei Secrets di Streamlit.")
    st.stop()


def api(method, path, payload=None, params=None, token=None, prefer=None):
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if prefer:
        headers["Prefer"] = prefer
    resp = requests.request(method, URL + path, headers=headers, json=payload, params=params, timeout=25)
    if resp.status_code >= 400:
        try:
            message = resp.json().get("msg") or resp.json().get("message") or resp.json().get("error_description")
        except ValueError:
            message = resp.text[:250]
        raise RuntimeError(f"{resp.status_code} — {message or 'Richiesta non riuscita'}")
    return resp.json() if resp.content else None


def auth_token():
    return st.session_state.get("cd_access_token")


def query(table, params=None):
    return api("GET", f"/rest/v1/{table}", params=params or {"select": "*"}, token=auth_token()) or []


def insert(table, payload):
    result = api("POST", f"/rest/v1/{table}", payload=payload, token=auth_token(), prefer="return=representation")
    return result[0] if result else None


def patch(table, where, payload):
    return api("PATCH", f"/rest/v1/{table}", params=where, payload=payload, token=auth_token(), prefer="return=minimal")


def rpc(name, params):
    return api("POST", f"/rest/v1/rpc/{name}", token=auth_token(), payload=params)


def money(value):
    return f"€ {float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def nice_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "—"


def workday(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def add_workdays(d, n):
    for _ in range(n):
        d += timedelta(days=1)
        while not workday(d):
            d += timedelta(days=1)
    return d


def elapsed_workdays(start, today):
    if today <= start:
        return 0
    result = 0
    step = start
    while step < today:
        step += timedelta(days=1)
        if workday(step):
            result += 1
    return result


def iban_clean(value):
    return re.sub(r"\s+", "", value or "").upper()


def iban_valid(value):
    value = iban_clean(value)
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", value):
        return False
    shifted = value[4:] + value[:4]
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in shifted)
    rem = 0
    for c in digits:
        rem = (rem * 10 + int(c)) % 97
    return rem == 1


def cipher():
    if not FERNET_KEY:
        raise RuntimeError("Manca CREDIT_DESK_FERNET_KEY nei Secrets.")
    return Fernet(FERNET_KEY.encode())


def user_id():
    return st.session_state["cd_user"]["id"]


def logout():
    for key in ["cd_access_token", "cd_refresh_token", "cd_user", "cd_profile"]:
        st.session_state.pop(key, None)
    st.rerun()


def load_profile():
    profiles = query("cd_profiles", {"select": "id,full_name,email,role", "id": f"eq.{user_id()}", "limit": 1})
    if not profiles:
        raise RuntimeError("Profilo non ancora disponibile. Verifica lo schema SQL e l'account.")
    st.session_state["cd_profile"] = profiles[0]


def ensure_session():
    token = auth_token()
    if not token:
        return False
    try:
        data = api("GET", "/auth/v1/user", token=token)
    except RuntimeError:
        refresh = st.session_state.get("cd_refresh_token")
        if not refresh:
            return False
        try:
            updated = api("POST", "/auth/v1/token?grant_type=refresh_token", payload={"refresh_token": refresh})
            st.session_state["cd_access_token"] = updated["access_token"]
            st.session_state["cd_refresh_token"] = updated["refresh_token"]
            data = updated["user"]
        except (RuntimeError, KeyError):
            return False
    st.session_state["cd_user"] = data
    load_profile()
    return True


def brand():
    st.markdown('<div class="cdbrand"><span class="cdbrand-mark">CD</span> CREDIT DESK</div>', unsafe_allow_html=True)
    st.markdown('<div class="cdsub">Area riservata finanziamenti</div>', unsafe_allow_html=True)


def signup_login():
    st.markdown("""<div class="cd-hero"><div class="cdbrand"><span class="cdbrand-mark">CD</span> CREDIT DESK</div>
<div class="cd-kicker" style="margin-top:26px">La tua area riservata</div>
<div class="cd-headline">Il tuo finanziamento,<br>sempre sotto controllo.</div>
<p class="cd-intro">Richiedi una soluzione di finanziamento, consulta le proposte e segui lo stato delle pratiche già deliberate fino all’erogazione.</p></div>""", unsafe_allow_html=True)
    left, center, right = st.columns([1, 2.1, 1], gap="medium")
    with center:
        login_tab, register_tab = st.tabs(["Accedi", "Registrati"])
        with login_tab:
            with st.form("cd_login"):
                email = st.text_input("Email", key="cd_email")
                password = st.text_input("Password", type="password", key="cd_pw")
                go = st.form_submit_button("ACCEDI", type="primary", use_container_width=True)
            if go:
                try:
                    data = api("POST", "/auth/v1/token?grant_type=password", {"email": email.strip(), "password": password})
                    st.session_state["cd_access_token"] = data["access_token"]
                    st.session_state["cd_refresh_token"] = data["refresh_token"]
                    st.session_state["cd_user"] = data["user"]
                    load_profile()
                    st.rerun()
                except (RuntimeError, KeyError) as ex:
                    st.error(f"Accesso non riuscito: {ex}")
        with register_tab:
            with st.form("cd_signup"):
                name = st.text_input("Nome e cognome")
                email_new = st.text_input("Email personale")
                pw1 = st.text_input("Crea password", type="password")
                pw2 = st.text_input("Conferma password", type="password")
                privacy_ready = PRIVACY_URL.startswith(("https://", "http://"))
                if privacy_ready:
                    st.markdown(f"[Leggi l’informativa sul trattamento dei dati personali]({PRIVACY_URL})")
                    agree = st.checkbox("Dichiaro di aver preso visione dell’informativa privacy.")
                else:
                    st.warning("Registrazione temporaneamente non disponibile: informativa privacy da pubblicare.")
                    agree = False
                send = st.form_submit_button("CREA ACCOUNT", use_container_width=True, disabled=not privacy_ready)
            if send:
                if not name.strip() or "@" not in email_new:
                    st.warning("Inserisci nome e indirizzo email valido.")
                elif len(pw1) < 10 or pw1 != pw2:
                    st.warning("Usa almeno 10 caratteri e verifica che le password coincidano.")
                elif not agree:
                    st.warning("Leggi e accetta la presa visione dell'informativa privacy prima di proseguire.")
                else:
                    try:
                        api("POST", "/auth/v1/signup", {"email": email_new.strip(), "password": pw1, "data": {"full_name": name.strip()}})
                        st.success("Registrazione acquisita. Se richiesta, conferma l'email prima di accedere.")
                    except RuntimeError as ex:
                        st.error(f"Registrazione non completata: {ex}")
    st.stop()


def progress(loan):
    start = date.fromisoformat(loan["signed_at"])
    today = datetime.now(TZ).date()
    target = date.fromisoformat(loan["expected_disbursement_date"]) if loan.get("expected_disbursement_date") else add_workdays(start, int(loan["planned_workdays"]))
    elapsed = elapsed_workdays(start, today)
    total = int(loan["planned_workdays"])
    shown = min(elapsed, total)
    remaining = max(0, total-elapsed)
    col1, col2, col3 = st.columns(3)
    col1.metric("Giorni lavorativi trascorsi", f"{shown}/{total}")
    col2.metric("Giorni lavorativi rimanenti", remaining)
    col3.metric("Data stimata", nice_date(target.isoformat()))
    percent = min(100, round(shown / max(total,1) * 100))
    st.markdown(f'<div class="cdprogress"><div class="cdprogressbar" style="width:{percent}%"></div></div>', unsafe_allow_html=True)
    st.caption(f"Avanzamento temporale: {percent}% · Termini indicativi, non conferma di erogazione. Calendario da adeguare alle festività della sede bancaria spagnola.")
    if today > target and loan["status"] not in ("Accredito confermato", "Annullata"):
        st.warning("La data indicativa è trascorsa. Richiedi un aggiornamento all'amministrazione.")
    if loan["status"] == "Accredito confermato":
        st.success("Accredito confermato dall'amministrazione sulla base della documentazione disponibile.")


def load_bank(loan_id):
    rows = query("cd_bank_details", {"select": "loan_id,iban_encrypted,iban_masked,holder,status,updated_at", "loan_id": f"eq.{loan_id}", "limit": 1})
    return rows[0] if rows else None


def bank_client(loan):
    st.subheader("Coordinate per l'accredito")
    bank = load_bank(loan["id"])
    if bank:
        st.info(f"IBAN: {bank['iban_masked']} · Intestatario: {bank['holder']} · Stato: {bank['status']}")
        if loan["bank_change_allowed"]:
            st.success("L'amministrazione ha autorizzato la sostituzione delle coordinate.")
        elif loan["bank_change_requested"]:
            st.warning("Richiesta di modifica inviata. Attendi autorizzazione.")
        elif loan["status"] not in ("Erogazione disposta", "Accredito confermato", "Annullata"):
            if st.button("Richiedi modifica IBAN", key=f"change_{loan['id']}"):
                try:
                    rpc("cd_request_iban_change", {"p_loan_id": loan["id"]})
                    st.success("Richiesta registrata.")
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))
    if loan["status"] in ("Erogazione disposta", "Accredito confermato", "Annullata"):
        return
    if bank and not loan["bank_change_allowed"]:
        return
    with st.form(f"bank_form_{loan['id']}"):
        holder = st.text_input("Intestatario del conto", help="Deve rispettare le condizioni comunicate dal finanziatore.")
        iban = st.text_input("IBAN per l'accredito")
        confirmation = st.checkbox("Confermo la correttezza delle coordinate e la mia autorizzazione a comunicarle ai fini dell'accredito.")
        submitted = st.form_submit_button("INVIA COORDINATE", type="primary")
    if submitted:
        if not iban_valid(iban):
            st.error("IBAN formalmente non valido.")
        elif not holder.strip() or not confirmation:
            st.error("Compila l'intestatario e conferma i dati.")
        else:
            try:
                clean = iban_clean(iban)
                encrypted = cipher().encrypt(clean.encode()).decode()
                rpc("cd_submit_iban", {"p_loan_id": loan["id"], "p_encrypted": encrypted,
                    "p_masked": clean[:2] + "••" + clean[-4:], "p_holder": holder.strip()})
                st.success("Coordinate registrate. La verifica amministrativa è in attesa.")
                st.rerun()
            except (RuntimeError, ValueError) as ex:
                st.error(f"Impossibile registrare le coordinate: {ex}")


def customer_app():
    profile = st.session_state["cd_profile"]
    with st.sidebar:
        brand()
        st.caption(profile["full_name"] or profile["email"])
        page = st.radio("Menu", ["La mia pratica", "Nuova richiesta", "Le mie soluzioni", "Assistenza"])
        if st.button("Esci"):
            logout()
    loans = query("cd_loans", {"select": "*", "client_id": f"eq.{user_id()}", "order": "created_at.desc"})
    if page == "La mia pratica":
        st.title("La mia pratica")
        if not loans:
            st.info("Nessun finanziamento deliberato associato a questo account. Se hai firmato una proposta, l'amministrazione deve collegarla al tuo profilo.")
            return
        loan = st.selectbox("Finanziamento", loans, format_func=lambda x: x["reference"] + " · " + x["lender"])
        st.success(f"Stato registrato: {loan['status']}") if loan["status"] == "Accredito confermato" else st.info(f"Stato amministrativo: {loan['status']}")
        c1,c2,c3 = st.columns(3)
        c1.metric("Importo deliberato", money(loan["amount"]))
        c2.metric("Rata mensile", money(loan["installment"]))
        c3.metric("Durata", f"{loan['duration_months']} mesi")
        st.caption(f"Istituto: {loan['lender']} · Proposta firmata: {nice_date(loan['signed_at'])} · TAN: {loan.get('tan') if loan.get('tan') is not None else 'n.d.'}% · TAEG: {loan.get('taeg') if loan.get('taeg') is not None else 'n.d.'}%")
        st.subheader("Monitoraggio dell'erogazione")
        progress(loan)
        st.caption("Lo stato dell'operazione è aggiornato dall'amministrazione dopo riscontri documentati dell'istituto. La barra temporale non certifica l'invio dei fondi.")
        if loan.get("status_note"):
            st.info(loan["status_note"])
        st.divider()
        bank_client(loan)
    elif page == "Nuova richiesta":
        st.title("Nuova richiesta di finanziamento")
        with st.form("new_request", clear_on_submit=True):
            amount = st.number_input("Importo richiesto (€)", min_value=100.0, max_value=2000000.0, step=500.0)
            purpose = st.selectbox("Finalità", ["Liquidità", "Consolidamento", "Acquisto", "Attività", "Altro"])
            duration = st.selectbox("Durata desiderata (mesi)", [12, 24, 36, 48, 60, 72, 84, 120, 180])
            employment = st.selectbox("Situazione lavorativa", ["Non specificata", "Dipendente", "Autonomo", "Pensionato", "Altro"])
            note = st.text_area("Note (facoltative)")
            go = st.form_submit_button("INVIA RICHIESTA", type="primary")
        if go:
            try:
                insert("cd_requests", {"client_id": user_id(), "amount": amount, "purpose": purpose,
                    "duration_months": duration, "employment": employment, "note": note.strip()})
                st.success("Richiesta acquisita. L'amministrazione valuterà eventuali soluzioni.")
                st.rerun()
            except RuntimeError as ex:
                st.error(str(ex))
        reqs = query("cd_requests", {"select": "*", "client_id": f"eq.{user_id()}", "order": "created_at.desc"})
        if reqs:
            st.dataframe([{"Data": nice_date(x["created_at"]), "Importo": money(x["amount"]), "Finalità": x["purpose"], "Stato": x["status"]} for x in reqs], hide_index=True, use_container_width=True)
    elif page == "Le mie soluzioni":
        st.title("Le mie soluzioni")
        reqs = query("cd_requests", {"select": "*", "client_id": f"eq.{user_id()}"})
        if not reqs:
            st.info("Non ci sono richieste presentate.")
            return
        sols = query("cd_solutions", {"select": "*", "order": "created_at.desc"})
        if not sols:
            st.info("L'amministrazione non ha ancora pubblicato soluzioni per le tue richieste.")
        for s in sols:
            st.markdown(f"### {html.escape(s['lender'])} · {money(s['amount'])}")
            st.write(f"Rata: {money(s['installment'])} · Durata: {s['duration_months']} mesi · TAN: {s.get('tan') if s.get('tan') is not None else 'n.d.'}% · TAEG: {s.get('taeg') if s.get('taeg') is not None else 'n.d.'}%")
            st.caption(s.get("notes") or "Le condizioni sono soggette alla documentazione del finanziatore e alle verifiche previste.")
            st.divider()
    else:
        st.title("Contatti con l'amministrazione")
        with st.form("new_message", clear_on_submit=True):
            category = st.selectbox("Motivo", ["Stato pratica", "Erogazione", "IBAN", "Soluzioni", "Generale"])
            loan_id = st.selectbox("Pratica associata", [None] + [x["id"] for x in loans], format_func=lambda v: "Nessuna / richiesta generale" if v is None else next(x["reference"] for x in loans if x["id"] == v))
            body = st.text_area("Messaggio")
            go = st.form_submit_button("INVIA MESSAGGIO", type="primary")
        if go:
            if not body.strip():
                st.warning("Scrivi un messaggio.")
            else:
                try:
                    insert("cd_messages", {"client_id": user_id(), "loan_id": loan_id, "sender": "client", "category": category, "body": body.strip()})
                    st.success("Messaggio registrato.")
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))
        messages = query("cd_messages", {"select": "*", "client_id": f"eq.{user_id()}", "order": "created_at.asc"})
        for msg in messages:
            with st.chat_message("user" if msg["sender"] == "client" else "assistant"):
                st.caption(f"{msg['sender']} · {msg['category']} · {msg['created_at'][:16].replace('T',' ')}")
                st.write(msg["body"])


def admin_app():
    with st.sidebar:
        brand()
        st.caption("Pannello amministrazione")
        page = st.radio("Menu", ["Dashboard", "Richieste e soluzioni", "Pratiche deliberate", "Erogazioni e IBAN", "Assistenza"])
        if st.button("Esci"):
            logout()
    profiles = query("cd_profiles", {"select": "id,full_name,email,role", "order": "created_at.desc"})
    client_map = {p["id"]: p for p in profiles}
    clients = [p for p in profiles if p["role"] == "client"]
    loans = query("cd_loans", {"select": "*", "order": "created_at.desc"})
    reqs = query("cd_requests", {"select": "*", "order": "created_at.desc"})
    if page == "Dashboard":
        st.title("Dashboard amministrativa")
        c1,c2,c3 = st.columns(3)
        c1.metric("Clienti registrati", len(clients))
        c2.metric("Richieste di finanziamento", len(reqs))
        c3.metric("Pratiche deliberate", len(loans))
        if loans:
            st.dataframe([{"Riferimento": l["reference"], "Cliente": client_map.get(l["client_id"], {}).get("full_name", ""), "Importo": money(l["amount"]), "Stato": l["status"]} for l in loans], hide_index=True, use_container_width=True)
    elif page == "Richieste e soluzioni":
        st.title("Richieste e soluzioni")
        if not reqs:
            st.info("Nessuna richiesta ricevuta.")
            return
        st.dataframe([{"Cliente": client_map.get(r["client_id"], {}).get("full_name", ""), "Importo": money(r["amount"]), "Finalità": r["purpose"], "Stato": r["status"]} for r in reqs], hide_index=True, use_container_width=True)
        rid = st.selectbox("Richiesta", [r["id"] for r in reqs], format_func=lambda v: next(f"{client_map.get(r['client_id'],{}).get('full_name','')} · {money(r['amount'])}" for r in reqs if r["id"] == v))
        req = next(r for r in reqs if r["id"] == rid)
        state = st.selectbox("Aggiorna stato richiesta", REQUEST_STATES, index=REQUEST_STATES.index(req["status"]))
        if st.button("Salva stato richiesta"):
            try:
                patch("cd_requests", {"id": f"eq.{rid}"}, {"status": state})
                st.rerun()
            except RuntimeError as ex:
                st.error(str(ex))
        st.subheader("Inserisci soluzione manualmente")
        with st.form("solution_form", clear_on_submit=True):
            lender = st.text_input("Finanziatore")
            x,y,z = st.columns(3)
            amount = x.number_input("Importo offerto", min_value=1.0, value=float(req["amount"]))
            installment = y.number_input("Rata mensile", min_value=0.01, value=100.0)
            duration = z.number_input("Durata mesi", min_value=1, max_value=360, value=int(req["duration_months"]))
            tan = st.number_input("TAN %", min_value=0.0, max_value=100.0, value=0.0)
            taeg = st.number_input("TAEG %", min_value=0.0, max_value=100.0, value=0.0)
            fees = st.number_input("Spese istruttoria €", min_value=0.0)
            notes = st.text_area("Note e condizioni")
            submit = st.form_submit_button("PUBBLICA SOLUZIONE", type="primary")
        if submit:
            if not lender.strip():
                st.error("Inserisci il nome del finanziatore.")
            else:
                try:
                    insert("cd_solutions", {"request_id": rid, "lender": lender.strip(), "amount": amount,
                        "installment": installment, "duration_months": duration, "tan": tan, "taeg": taeg, "setup_fees": fees, "notes": notes})
                    patch("cd_requests", {"id": f"eq.{rid}"}, {"status": "Soluzione disponibile"})
                    st.success("Soluzione pubblicata nell'area del cliente.")
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))
    elif page == "Pratiche deliberate":
        st.title("Pratiche deliberate")
        if not clients:
            st.warning("Prima fai registrare il cliente con email e password; poi potrai associargli la pratica.")
            return
        st.subheader("Registra una pratica già deliberata")
        with st.form("new_loan", clear_on_submit=True):
            client_id = st.selectbox("Cliente registrato", [p["id"] for p in clients], format_func=lambda x: client_map[x]["full_name"] + " · " + client_map[x]["email"])
            ref = st.text_input("Riferimento pratica", placeholder="CD-2026-000001")
            lender = st.text_input("Istituto finanziatore")
            a,b,c = st.columns(3)
            amount = a.number_input("Importo deliberato (€)", min_value=1.0, step=100.0)
            installment = b.number_input("Rata mensile (€)", min_value=0.01, step=10.0)
            duration = c.number_input("Durata mesi", min_value=1, max_value=360, value=120)
            x,y,z = st.columns(3)
            tan = x.number_input("TAN %", min_value=0.0, max_value=100.0)
            taeg = y.number_input("TAEG %", min_value=0.0, max_value=100.0)
            signed = z.date_input("Data firma proposta", value=date(2026,11,2), format="DD/MM/YYYY")
            days = st.number_input("Termine lavorativo indicativo (giorni)", min_value=1, max_value=90, value=8)
            expected = st.date_input("Data stimata (modificabile)", value=add_workdays(signed,days), format="DD/MM/YYYY")
            confirm = st.checkbox("Confermo che esiste una delibera documentata e una proposta sottoscritta.")
            submitted = st.form_submit_button("REGISTRA PRATICA", type="primary")
        if submitted:
            if not ref.strip() or not lender.strip() or not confirm:
                st.warning("Inserisci riferimento, istituto e conferma la documentazione.")
            else:
                try:
                    insert("cd_loans", {"client_id": client_id, "reference": ref.strip(), "lender": lender.strip(),
                        "amount": amount, "installment": installment, "duration_months": duration, "tan": tan,
                        "taeg": taeg, "signed_at": signed.isoformat(), "planned_workdays": int(days),
                        "expected_disbursement_date": expected.isoformat(), "status": "Deliberata"})
                    st.success("Pratica collegata all'account cliente.")
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))
        if loans:
            st.divider()
            st.subheader("Aggiorna una pratica")
            loan_id = st.selectbox("Pratica", [l["id"] for l in loans], format_func=lambda x: next(l["reference"] for l in loans if l["id"] == x))
            loan = next(l for l in loans if l["id"] == loan_id)
            with st.form("update_loan"):
                state = st.selectbox("Stato verificato", LOAN_STATES, index=LOAN_STATES.index(loan["status"]))
                note = st.text_area("Aggiornamento per il cliente", value=loan.get("status_note") or "")
                expected = st.date_input("Data prevista erogazione", value=date.fromisoformat(loan["expected_disbursement_date"]) if loan.get("expected_disbursement_date") else add_workdays(date.fromisoformat(loan["signed_at"]), loan["planned_workdays"]))
                evidence = st.checkbox("Confermo che lo stato selezionato è supportato da una comunicazione o prova documentale.")
                go = st.form_submit_button("SALVA STATO")
            if go:
                if not evidence:
                    st.warning("Conferma il riscontro documentale prima di cambiare lo stato.")
                else:
                    try:
                        patch("cd_loans", {"id": f"eq.{loan_id}"}, {"status": state, "status_note": note.strip(),
                            "expected_disbursement_date": expected.isoformat(),
                            "disbursed_at": datetime.now(TZ).date().isoformat() if state == "Accredito confermato" else loan.get("disbursed_at")})
                        st.success("Pratica aggiornata.")
                        st.rerun()
                    except RuntimeError as ex:
                        st.error(str(ex))
    elif page == "Erogazioni e IBAN":
        st.title("Erogazioni e IBAN")
        if not loans:
            st.info("Nessuna pratica registrata.")
            return
        loan_id = st.selectbox("Pratica", [l["id"] for l in loans], format_func=lambda x: next(l["reference"] for l in loans if l["id"] == x))
        loan = next(l for l in loans if l["id"] == loan_id)
        progress(loan)
        st.divider()
        bank = load_bank(loan_id)
        if not bank:
            st.info("Il cliente non ha ancora comunicato l'IBAN.")
        else:
            st.write(f"**Intestatario:** {bank['holder']} · **Stato:** {bank['status']}")
            st.write(f"**IBAN mascherato:** {bank['iban_masked']}")
            try:
                iban = cipher().decrypt(bank["iban_encrypted"].encode()).decode()
                with st.expander("Visualizza IBAN completo (solo amministrazione)"):
                    st.code(iban)
            except (RuntimeError, InvalidToken):
                st.error("Impossibile decifrare l'IBAN. Controllare la chiave di cifratura.")
            status = st.selectbox("Esito verifica", ["Da verificare", "Verificato", "Respinto"], index=["Da verificare", "Verificato", "Respinto"].index(bank["status"]))
            if st.button("Salva esito verifica"):
                try:
                    patch("cd_bank_details", {"loan_id": f"eq.{loan_id}"}, {"status": status,
                          "verified_at": datetime.now(TZ).isoformat() if status == "Verificato" else None})
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))
        if loan["bank_change_requested"]:
            st.warning("Il cliente ha richiesto di modificare le coordinate bancarie.")
            if st.button("AUTORIZZA NUOVO INSERIMENTO IBAN", type="primary"):
                try:
                    patch("cd_loans", {"id": f"eq.{loan_id}"}, {"bank_change_allowed": True, "bank_change_requested": False})
                    st.success("Cliente autorizzato a sostituire l'IBAN; il nuovo IBAN sarà nuovamente da verificare.")
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))
    else:
        st.title("Assistenza clienti")
        messages = query("cd_messages", {"select": "*", "order": "created_at.asc"})
        if not clients:
            st.info("Nessun cliente registrato.")
            return
        customer = st.selectbox("Cliente", [p["id"] for p in clients], format_func=lambda x: client_map[x]["full_name"] + " · " + client_map[x]["email"])
        for msg in [m for m in messages if m["client_id"] == customer]:
            with st.chat_message("assistant" if msg["sender"] == "admin" else "user"):
                st.caption(f"{msg['sender']} · {msg['category']} · {msg['created_at'][:16].replace('T',' ')}")
                st.write(msg["body"])
        with st.form("admin_reply", clear_on_submit=True):
            response = st.text_area("Risposta amministrazione")
            send = st.form_submit_button("INVIA RISPOSTA", type="primary")
        if send:
            if not response.strip():
                st.warning("Inserisci una risposta.")
            else:
                try:
                    insert("cd_messages", {"client_id": customer, "sender": "admin", "category": "Risposta amministrazione", "body": response.strip()})
                    st.success("Risposta inviata.")
                    st.rerun()
                except RuntimeError as ex:
                    st.error(str(ex))


try:
    if not ensure_session():
        signup_login()
    elif st.session_state["cd_profile"]["role"] == "admin":
        admin_app()
    else:
        customer_app()
except requests.RequestException:
    st.error("Connessione a Supabase temporaneamente non disponibile.")
except RuntimeError as exc:
    st.error(f"Configurazione o autorizzazione: {exc}")
