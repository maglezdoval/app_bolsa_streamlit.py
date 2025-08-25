# -*- coding: utf-8 -*-
"""
Mini App IBEX35 → Última Cotización (EODHD)
Autor: ChatGPT (GPT-5 Thinking)

Objetivo: app mínima que selecciona una empresa del IBEX35 y muestra su **última
cotización** usando **EODHD.com** (tu clave API).

Dependencias mínimas para Streamlit Cloud:
    streamlit==1.37.1
    requests==2.32.3

Cómo usar en Streamlit Cloud:
- En la barra lateral introduce tu **API Key** de EODHD (o usa st.secrets / env).
- Selecciona una empresa del IBEX35 y verás precio, cambio y hora.

Notas:
- Endpoint usado: `GET https://eodhd.com/api/real-time/{symbol}?api_token=...&fmt=json`
- Símbolos de IBEX en EODHD usan sufijo **.MC** (Madrid).
- Si `eodhd.com` falla, hay fallback a `eodhistoricaldata.com`.
- Botón "Actualizar" limpia caché para reintentar.
- Modo Debug muestra JSON crudo.
"""

from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional
import os
import json
import requests
import streamlit as st

# ============================
# Configuración
# ============================
st.set_page_config(page_title="IBEX35 · Última Cotización", page_icon="💶", layout="centered")

# Lista estática IBEX35 (símbolo EOD/Yahoo + nombre). Última revisión: 2025-08-25.
IBEX35: List[Tuple[str, str]] = [
    ("ACS.MC", "ACS"), ("ACX.MC", "Acerinox"), ("AENA.MC", "Aena"), ("ALM.MC", "Almirall"),
    ("ANA.MC", "Acciona"), ("BBVA.MC", "BBVA"), ("BKT.MC", "Bankinter"), ("CABK.MC", "CaixaBank"),
    ("CLNX.MC", "Cellnex"), ("COL.MC", "Colonial"), ("ELE.MC", "Endesa"), ("ENG.MC", "Enagás"),
    ("FER.MC", "Ferrovial"), ("GRF.MC", "Grifols"), ("IBE.MC", "Iberdrola"), ("ITX.MC", "Inditex"),
    ("IAG.MC", "IAG"), ("LOG.MC", "Logista"), ("MAP.MC", "Mapfre"), ("MEL.MC", "Meliá Hotels"),
    ("MRL.MC", "Merlin Properties"), ("NTGY.MC", "Naturgy"), ("PHM.MC", "PharmaMar"),
    ("REE.MC", "Redeia (REE)"), ("ROVI.MC", "Laboratorios Rovi"), ("SAB.MC", "Banco Sabadell"),
    ("SAN.MC", "Banco Santander"), ("SLR.MC", "Solaria"), ("TEF.MC", "Telefónica"), ("VIS.MC", "Viscofan"),
]

# ============================
# EODHD endpoints y helpers
# ============================
UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

EOD_BASES = [
    "https://eodhd.com/api/real-time/{symbol}",
    "https://eodhistoricaldata.com/api/real-time/{symbol}",  # fallback alias
]


def _get_json(url: str, params: Optional[Dict] = None, timeout: int = 15) -> tuple[Optional[Dict], Optional[str]]:
    try:
        r = requests.get(url, params=params, headers=UA_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, f"HTTP error: {e}"


@st.cache_data(ttl=30)
def fetch_quote_eod(symbol: str, api_key: str) -> Dict:
    """Obtiene la última cotización desde EODHD con fallback de dominio.
    Devuelve dict normalizado:
        price, currency, change, change_pct, prev_close, ts, source, raw
    """
    if not api_key:
        return {}
    params = {"api_token": api_key, "fmt": "json"}
    last_err = None
    for base in EOD_BASES:
        url = base.format(symbol=symbol)
        js, err = _get_json(url, params=params)
        if js and isinstance(js, dict) and js.get("code") or js.get("close") or js.get("timestamp"):
            # Normaliza campos típicos de EODHD
            price = js.get("close") if js.get("close") is not None else js.get("last")
            return {
                "price": price,
                "currency": js.get("currency"),
                "change": js.get("change"),
                "change_pct": js.get("change_p"),
                "prev_close": js.get("previousClose"),
                "ts": js.get("timestamp"),
                "source": "eodhd_realtime",
                "raw": js,
            }
        last_err = err or "Respuesta vacía"
    # Si llega aquí, no se pudo
    return {}

# ============================
# UI
# ============================
st.title("IBEX35 → Última cotización (EODHD)")
st.caption("Fuente: EODHD.com (requiere API Key).")

# Barra lateral: API Key
with st.sidebar:
    st.subheader("🔑 EODHD API Key")
    default_key = st.secrets.get("EODHD_API_KEY", "") or os.getenv("EODHD_API_KEY", "") or "68acad3b6e47d5.39244974"
    api_key = st.text_input("Introduce tu API Key", value=default_key, type="password")
    st.caption("Puedes guardarla en st.secrets como EODHD_API_KEY o en la variable de entorno EODHD_API_KEY.")
    col_a, col_b = st.columns(2)
    with col_a:
        refresh = st.button("Actualizar", use_container_width=True)
    with col_b:
        debug = st.toggle("Debug")

if refresh:
    st.cache_data.clear()

# Selector de empresa
names = [name for _, name in IBEX35]
name_to_symbol = {name: sym for sym, name in IBEX35}
selected_name = st.selectbox("Elige empresa", options=sorted(names), index=names.index("Inditex") if "Inditex" in names else 0)

if selected_name:
    symbol = name_to_symbol[selected_name]
    data = fetch_quote_eod(symbol, api_key)

    if not data:
        st.error("No se pudo obtener la cotización desde EODHD. Verifica la API Key o inténtalo de nuevo.")
        if debug:
            st.info("Comprueba que el símbolo existe en EODHD (formato TICKER.MC) y que tu plan permite tiempo real.")
        st.stop()

    price = data.get("price")
    currency = data.get("currency")
    change = data.get("change")
    change_pct = data.get("change_pct")
    prev_close = data.get("prev_close")
    ts = data.get("ts")
    source = data.get("source")

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
        if (change is None) and (change_pct is None):
            st.metric("Cambio", "—")
        else:
            parts = []
            if change is not None:
                try:
                    parts.append(f"{float(change):+,.2f}")
                except Exception:
                    parts.append(str(change))
            if change_pct is not None:
                try:
                    parts.append(f"({float(change_pct):+,.2f}%)")
                except Exception:
                    parts.append(f"({change_pct}%)")
            st.metric("Cambio", " ".join(parts))
    with k3:
        st.metric("Cierre previo", prev_close if prev_close is not None else "—")

    st.caption(f"Hora de mercado: {when_str} · Fuente: {source}")

    if debug:
        with st.expander("Detalles técnicos (JSON crudo)"):
            st.code(json.dumps(data.get("raw", {}), ensure_ascii=False, indent=2))

# ============================
# Tests rápidos
# ============================
st.divider()
st.markdown("### 🧪 Test rápido EODHD")
if st.button("Probar SAN.MC e ITX.MC"):
    st.cache_data.clear()
    res = {sym: bool(fetch_quote_eod(sym, api_key)) for sym in ("SAN.MC", "ITX.MC")}
    st.write({k: ("OK" if v else "FAIL") for k,v in res.items()})
    if all(res.values()):
        st.success("Tests OK: EODHD devolvió cotizaciones.")
    else:
        st.warning("Alguno de los símbolos no devolvió datos. Revisa la API Key o la disponibilidad.")
