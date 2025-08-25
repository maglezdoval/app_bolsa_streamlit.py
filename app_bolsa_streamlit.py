# -*- coding: utf-8 -*-
"""
Mini App IBEX35 → Última Cotización
Autor: ChatGPT (GPT-5 Thinking)

Objetivo: **una app muy sencilla** que permita seleccionar una empresa del IBEX35
(en formato Yahoo Finance, sufijo `.MC`) y mostrar su **última cotización**.

Dependencias mínimas (para Streamlit Cloud sin bloqueos):
    streamlit, requests  
Sugerencia de requirements.txt:
    streamlit==1.37.1
    requests==2.32.3

Notas:
- Fuente de precio: Yahoo Finance Quote API (no requiere yfinance).
- "Última cotización" se muestra con `regularMarketPrice`, además del cambio y
  hora de mercado (`regularMarketTime`).
- TTL de caché corto (60s) para no saturar la API.

Preguntas abiertas (para afinar comportamiento):
1) ¿Quieres que la lista IBEX35 sea **dinámica** (p.ej. Wikipedia) o está bien
   mantenerla **estática** para despliegues más fiables?
2) ¿Prefieres mostrar **solo precio** o también **cambio** y **%**?
3) ¿Mostramos además `previousClose` por claridad?
"""

from __future__ import annotations
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional

import requests
import streamlit as st

# ============================
# Configuración
# ============================
st.set_page_config(page_title="IBEX35 · Última Cotización", page_icon="💶", layout="centered")

# Lista estática IBEX35 (símbolo Yahoo + nombre). Última revisión: 2025-08-25.
# Nota: La composición puede variar con el tiempo; esto es un arranque sencillo.
IBEX35: List[Tuple[str, str]] = [
    ("ACS.MC", "ACS"),
    ("ACX.MC", "Acerinox"),
    ("AENA.MC", "Aena"),
    ("ALM.MC", "Almirall"),
    ("ANA.MC", "Acciona"),
    ("BBVA.MC", "BBVA"),
    ("BKT.MC", "Bankinter"),
    ("CABK.MC", "CaixaBank"),
    ("CLNX.MC", "Cellnex"),
    ("COL.MC", "Colonial"),
    ("ELE.MC", "Endesa"),
    ("ENG.MC", "Enagás"),
    ("FER.MC", "Ferrovial"),
    ("GRF.MC", "Grifols"),
    ("IBE.MC", "Iberdrola"),
    ("ITX.MC", "Inditex"),
    ("IAG.MC", "IAG"),
    ("LOG.MC", "Logista"),
    ("MAP.MC", "Mapfre"),
    ("MEL.MC", "Meliá Hotels"),
    ("MRL.MC", "Merlin Properties"),
    ("NTGY.MC", "Naturgy"),
    ("PHM.MC", "PharmaMar"),
    ("REE.MC", "Redeia (REE)"),
    ("ROVI.MC", "Laboratorios Rovi"),
    ("SAB.MC", "Banco Sabadell"),
    ("SAN.MC", "Banco Santander"),
    ("SLR.MC", "Solaria"),
    ("TEF.MC", "Telefónica"),
    ("VIS.MC", "Viscofan"),
]

# ============================
# Datos
# ============================
YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

@st.cache_data(ttl=60)
def fetch_quote(symbol: str) -> Dict:
    """Consulta la Yahoo Quote API para un símbolo y devuelve el primer resultado.
    Devuelve dict vacío si no hay datos.
    """
    try:
        r = requests.get(YF_QUOTE_URL, params={"symbols": symbol}, timeout=15)
        r.raise_for_status()
        js = r.json()
        result = (((js or {}).get("quoteResponse") or {}).get("result") or [])
        return result[0] if result else {}
    except Exception as e:
        # No usamos st.error dentro de caché para no memorizar el estado visual
        return {}

# ============================
# UI
# ============================
st.title("IBEX35 → Última cotización")
st.caption("Fuente: Yahoo Finance (API pública no oficial).")

# Selector de empresa
names = [name for _, name in IBEX35]
name_to_symbol = {name: sym for sym, name in IBEX35}

col_sel, col_btn = st.columns([0.7, 0.3])
with col_sel:
    selected_name = st.selectbox("Elige empresa", options=sorted(names), index=names.index("Inditex") if "Inditex" in names else 0)
with col_btn:
    refresh = st.button("Actualizar", use_container_width=True)

if selected_name:
    symbol = name_to_symbol[selected_name]
    data = fetch_quote(symbol)

    if not data:
        st.error("No se pudo obtener la cotización ahora mismo. Prueba de nuevo en unos segundos.")
        st.stop()

    price = data.get("regularMarketPrice")
    currency = data.get("currency")
    change = data.get("regularMarketChange")
    change_pct = data.get("regularMarketChangePercent")
    prev_close = data.get("regularMarketPreviousClose")
    ts = data.get("regularMarketTime")  # epoch seconds

    # Formatea hora en Europa/Madrid
    when_str = "—"
    try:
        if ts:
            when = datetime.fromtimestamp(int(ts), tz=ZoneInfo("Europe/Madrid"))
            when_str = when.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        pass

    st.subheader(f"{selected_name} ({symbol})")
    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric("Último", f"{price if price is not None else '—'} {currency or ''}")
    with k2:
        # Evita mostrar None
        delta_txt = "—"
        if (change is not None) and (change_pct is not None):
            delta_txt = f"{change:+.2f} ({change_pct:+.2f}%)"
        elif change is not None:
            delta_txt = f"{change:+.2f}"
        elif change_pct is not None:
            delta_txt = f"({change_pct:+.2f}%)"
        st.metric("Cambio", delta_txt)
    with k3:
        st.metric("Cierre previo", prev_close if prev_close is not None else "—")

    st.caption(f"Hora de mercado: {when_str}")

# ============================
# Tests básicos (opcionales)
# ============================
st.divider()
st.markdown("### 🧪 Test rápido")
if st.button("Probar SAN.MC e ITX.MC"):
    ok_san = bool(fetch_quote("SAN.MC"))
    ok_itx = bool(fetch_quote("ITX.MC"))
    st.write({"SAN.MC": "OK" if ok_san else "FAIL", "ITX.MC": "OK" if ok_itx else "FAIL"})
    if ok_san and ok_itx:
        st.success("Tests OK: se pudieron obtener cotizaciones.")
    else:
        st.warning("Alguno de los símbolos no devolvió datos ahora mismo.")
