import streamlit as st
import json, re, uuid, hashlib, secrets, requests
from pathlib import Path
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

st.set_page_config(page_title="VIL Private", page_icon="V", layout="wide")

BASE = Path(__file__).parent
CLIENTS_FILE = BASE / "clients.json"
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SECRET_KEY = st.secrets.get("SUPABASE_SECRET_KEY", "")
