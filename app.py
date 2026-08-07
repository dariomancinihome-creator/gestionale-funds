import streamlit as st
import json, re, uuid, hashlib, requests
from pathlib import Path
from datetime import datetime, timedelta, date

st.set_page_config(page_title='Gestionale Funds', page_icon='◈', layout='wide', initial_sidebar_state='expanded')
BASE = Path(__file__).parent
CLIENTS_FILE = BASE / 'clients.json'
SUPABASE_URL = st.secrets.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SECRET_KEY = st.secrets.get('SUPABASE_SECRET_KEY', '')

def load_clients():
    try:
        return json.loads(CLIENTS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []

def euro(v):
    return f'€ {float(v):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

def clean_iban(v):
    return re.sub(r'\s+', '', v or '').upper()

def valid_iban(v):
    v = clean_iban(v)
    if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{11,30}', v):
        return False
    moved = v[4:] + v[:4]
    digits = ''.join(str(ord(c)-55) if c.isalpha() else c for c in moved)
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

def password_ok(pwd):
    expected = st.secrets.get('APP_PASSWORD', 'Funds2026')
    return hashlib.sha256(pwd.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()

def headers(prefer=None):
    h = {'apikey': SUPABASE_SECRET_KEY, 'Authorization': f'Bearer {SUPABASE_SECRET_KEY}', 'Content-Type': 'application/json'}
    if prefer: h['Prefer'] = prefer
    return h

def ready():
    return bool(SUPABASE_URL and SUPABASE_SECRET_KEY)

def get_operations():
    try:
        r = requests.get(f'{SUPABASE_URL}/rest/v1/operations', headers=headers(), params={'select':'*','order':'created_at.desc'}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error('Impossibile leggere lo storico dal database.')
        st.caption(str(e))
        return []

def insert_operation(payload):
    try:
        r = requests.post(f'{SUPABASE_URL}/rest/v1/operations', headers=headers('return=representation'), json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        return True, data[0] if data else payload
    except Exception as e:
        return False, str(e)

def update_status(op_id, status):
    payload = {'status': status}
    if status in ('Accreditato','Completato'):
        payload['completed_at'] = datetime.utcnow().isoformat() + 'Z'
    try:
        r = requests.patch(f'{SUPABASE_URL}/rest/v1/operations', headers=headers('return=minimal'), params={'id':f'eq.{op_id}'}, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        st.error('Aggiornamento stato non riuscito.')
        st.caption(str(e))
        return False

def mark_expired(ops):
    today = date.today()
    changed = False
    for op in ops:
        if op.get('status') == 'In elaborazione' and op.get('estimated_date'):
            try: due = date.fromisoformat(op['estimated_date'][:10])
            except Exception: continue
            if due < today and update_status(op['id'], 'Da aggiornare'):
                changed = True
    return changed

def fmt_date(v, with_time=False):
    if not v: return ''
    try:
        dt = datetime.fromisoformat(v.replace('Z','+00:00'))
        return dt.strftime('%d/%m/%Y %H:%M' if with_time else '%d/%m/%Y')
    except Exception:
        try: return date.fromisoformat(v[:10]).strftime('%d/%m/%Y')
        except Exception: return v

st.markdown('''<style>
.stApp{background:linear-gradient(180deg,#f2f6fb 0%,#fbfcfe 100%)}
.block-container{padding-top:1.2rem;max-width:1400px}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#102f55,#174d82)}
[data-testid="stSidebar"] *{color:white}
[data-testid="stMetric"]{background:white;border:1px solid #e3e9f1;padding:18px;border-radius:17px;box-shadow:0 7px 22px rgba(16,47,85,.06)}
.gf-brand{font-size:1.45rem;font-weight:850;margin-bottom:1.6rem}.gf-title{font-size:2.05rem;font-weight:850;color:#102f55}.gf-sub{color:#667085;margin-bottom:1.4rem}.gf-ok{display:inline-block;background:#eaf8f2;color:#08734d;padding:7px 12px;border-radius:999px;font-weight:750}
div.stButton>button,div.stFormSubmitButton>button{background:#175b9c;color:white;border:0;border-radius:11px;font-weight:750;min-height:46px}
</style>''', unsafe_allow_html=True)

if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.markdown('<div class="gf-title">Gestionale Funds</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Accesso all’area gestionale</div>', unsafe_allow_html=True)
    with st.form('login'):
        pwd = st.text_input('Password', type='password')
        go = st.form_submit_button('ACCEDI', use_container_width=True)
    if go:
        if password_ok(pwd): st.session_state.authenticated=True; st.rerun()
        else: st.error('Password non corretta.')
    st.stop()

if not ready():
    st.error('Collegamento database non configurato.')
    st.info('Verifica SUPABASE_URL e SUPABASE_SECRET_KEY nei Secrets di Streamlit.')
    st.stop()

clients = load_clients()
operations = get_operations()
if mark_expired(operations): operations = get_operations()

with st.sidebar:
    st.markdown('<div class="gf-brand">◈ Gestionale Funds</div>', unsafe_allow_html=True)
    page = st.radio('Navigazione',['Dashboard','Nuova operazione','Clienti','Storico'], label_visibility='collapsed')
    st.divider()
    if st.button('Esci', use_container_width=True): st.session_state.authenticated=False; st.rerun()

if page == 'Dashboard':
    st.markdown('<div class="gf-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Situazione complessiva del gestionale</div>', unsafe_allow_html=True)
    a,b,c,d = st.columns(4)
    a.metric('Clienti attivi', len([x for x in clients if x['status']=='Attivo']))
    b.metric('Somme associate', euro(sum(float(x['balance']) for x in clients)))
    c.metric('Da gestire', sum(1 for o in operations if o.get('status') in ('In elaborazione','Da aggiornare')))
    d.metric('Totale ordinato', euro(sum(float(o.get('amount',0) or 0) for o in operations)))
    st.markdown('### Operazioni aperte')
    open_ops=[o for o in operations if o.get('status') in ('In elaborazione','Da aggiornare')]
    if open_ops:
        st.dataframe([{'ID':o['id'],'Data':fmt_date(o.get('created_at'),True),'Cliente':o['client_name'],'Importo':euro(o['amount']),'Stato':o['status'],'Data prevista':fmt_date(o.get('estimated_date'))} for o in open_ops], use_container_width=True, hide_index=True)
    else: st.success('Nessuna operazione aperta.')

elif page == 'Nuova operazione':
    st.markdown('<div class="gf-title">Nuova operazione</div>', unsafe_allow_html=True)
    code=st.selectbox('Codice cliente',['Seleziona']+[c['code'] for c in clients])
    client=next((c for c in clients if c['code']==code),None)
    if client:
        c1,c2,c3,c4=st.columns(4)
        c1.text_input('Cliente',client['name'],disabled=True); c2.text_input('Banca',client['bank'],disabled=True); c3.text_input('Somma associata',euro(client['balance']),disabled=True); c4.text_input('Stato',client['status'],disabled=True)
        amount=st.number_input('Importo da ordinare',min_value=0.01,max_value=float(client['balance']),value=min(1000.0,float(client['balance'])),step=100.0)
        residual=float(client['balance'])-float(amount)
        with st.form('operation_form'):
            x,y=st.columns(2); holder=x.text_input('Intestatario beneficiario'); iban=y.text_input('IBAN beneficiario')
            x2,y2=st.columns(2); x2.text_input('Importo selezionato',euro(amount),disabled=True); y2.text_input('Residuo previsto',euro(residual),disabled=True)
            reason=st.text_input('Causale'); confirm=st.checkbox('Confermo i dati inseriti'); submitted=st.form_submit_button('INVIA',use_container_width=True)
        if submitted:
            errs=[]
            if not holder.strip(): errs.append('Inserire l’intestatario.')
            if not valid_iban(iban): errs.append('L’IBAN non supera il controllo.')
            if not reason.strip(): errs.append('Inserire la causale.')
            if not confirm: errs.append('Confermare i dati prima dell’invio.')
            if errs:
                for e in errs: st.error(e)
            else:
                now=datetime.now(); estimated=add_workdays(now.date(),5)
                payload={'id':f'GF-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}','client_code':client['code'],'client_name':client['name'],'bank':client['bank'],'holder':holder.strip(),'iban':clean_iban(iban),'amount':round(float(amount),2),'reason':reason.strip(),'status':'In elaborazione','estimated_date':estimated.isoformat()}
                ok,saved=insert_operation(payload)
                if ok: st.success('Richiesta inviata'); st.rerun()
                else: st.error('Non è stato possibile registrare la richiesta.'); st.caption(saved)
    else: st.info('Seleziona il codice cliente per visualizzare i dati associati.')

elif page == 'Clienti':
    st.markdown('<div class="gf-title">Clienti</div>', unsafe_allow_html=True)
    st.dataframe([{'Codice':c['code'],'Cliente':c['name'],'Banca':c['bank'],'Somma associata':euro(c['balance']),'Stato':c['status']} for c in clients],use_container_width=True,hide_index=True)

else:
    st.markdown('<div class="gf-title">Storico operazioni</div>', unsafe_allow_html=True)
    st.markdown('<div class="gf-sub">Le operazioni rimangono archiviate anche dopo la data prevista</div>', unsafe_allow_html=True)
    if operations:
        search=st.text_input('Cerca per cliente, codice o ID'); filtered=operations
        if search.strip():
            q=search.lower().strip(); filtered=[o for o in operations if q in o['client_name'].lower() or q in o['client_code'].lower() or q in o['id'].lower()]
        st.dataframe([{'ID':o['id'],'Data':fmt_date(o.get('created_at'),True),'Codice':o['client_code'],'Cliente':o['client_name'],'Banca':o['bank'],'Importo':euro(o['amount']),'Stato':o['status'],'Data prevista':fmt_date(o.get('estimated_date'))} for o in filtered],use_container_width=True,hide_index=True)
        st.markdown('### Aggiorna stato')
        selected_id=st.selectbox('Operazione',[o['id'] for o in operations]); selected=next(o for o in operations if o['id']==selected_id)
        states=['In elaborazione','Da aggiornare','Accreditato','Completato','Annullato']; idx=states.index(selected.get('status')) if selected.get('status') in states else 0
        new_status=st.selectbox('Nuovo stato',states,index=idx)
        if st.button('AGGIORNA STATO',use_container_width=True):
            if update_status(selected_id,new_status): st.success('Stato aggiornato.'); st.rerun()
    else: st.info('Non risultano ancora operazioni registrate.')
