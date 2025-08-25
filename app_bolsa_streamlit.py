# -*- coding: utf-8 -*-
"""
Mini App IBEX35 → Última Cotización (SOLO Alpha Vantage)
Autor: ChatGPT (GPT-5 Thinking)

⚠️ Esta versión **elimina por completo EODHD**. Solo usa **Alpha Vantage**.

Dependencias mínimas:
    streamlit==1.37.1
    requests==2.32.3

Notas:
- Endpoint: GLOBAL_QUOTE → https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=...&apikey=...
- Límite plan gratuito: ~5 req/min y ~500 req/día → he puesto `st.cache_data(ttl=60)` para ahorrar llamadas.
- Para símbolos IBEX (`.MC`) pruebo variantes si la respuesta viene vacía: `SAN.MC` → `SAN` → `BME:SAN`.
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

# Lista estática IBEX35 (símbolo + nombre). Última revisión: 2025-08-25.
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
# HTTP helpers
# ============================
UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

AV_URL = "https://www.alphavantage.co/query"


def _get_json(url: str, params: Optional[Dict] = None, timeout: int = 15) -> tuple[Optional[Dict], Optional[str]]:
    try:
        r = requests.get(url, params=params, headers=UA_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, f"HTTP error: {e}"


def _get_secret(name: str, default: str = "") -> str:
    return st.secrets.get(name, "") or os.getenv(name, "") or default

# ============================
# Alpha Vantage
# ============================
@st.cache_data(ttl=60)
def fetch_quote_av(symbol: str, api_key: str, try_variants: bool = True) -> Dict:
    if not api_key:
        return {}

    def _parse_pct(txt: Optional[str]) -> Optional[float]:
        if not txt:
            return None
        try:
            return float(txt.strip().replace("%", ""))
        except Exception:
            return None

    def _call_av(sym: str) -> Dict:
        params = {"function": "GLOBAL_QUOTE", "symbol": sym, "apikey": api_key}
        js, _ = _get_json(AV_URL, params=params)
        if not js:
            return {}
        if js.get("Note") or js.get("Information") or js.get("Error Message"):
            return {"_notice": js}
        gq = js.get("Global Quote") or {}
        price = gq.get("05. price")
        out = {
            "price": float(price) if price is not None else None,
            "currency": "EUR" if sym.endswith(".MC") or sym.startswith("BME:") else None,
            "change": float(gq.get("09. change")) if gq.get("09. change") is not None else None,
            "change_pct": _parse_pct(gq.get("10. change percent")),
            "prev_close": float(gq.get("08. previous close")) if gq.get("08. previous close") is not None else None,
            "ts": None,  # GLOBAL_QUOTE no trae epoch
            "source": f"alphavantage_global_quote:{sym}",
            "raw": js,
        }
        return out if out["price"] is not None else {}

    attempts = [symbol]
    if try_variants:
        base = symbol[:-3] if symbol.endswith(".MC") else symbol
        if base != symbol:
            attempts.append(base)
        attempts.append(f"BME:{base}")

    for sym in attempts:
        res = _call_av(sym)
        if res and res.get("price") is not None:
            return res
    return {}

# ============================
# UI
# ============================
st.title("IBEX35 → Última cotización")
st.caption("Fuente: Alpha Vantage (GLOBAL_QUOTE)")

# Sidebar: API key (persistente en session_state)
if "av_key" not in st.session_state:
    st.session_state.av_key = _get_secret("ALPHAVANTAGE_API_KEY", "")

with st.sidebar:
    st.subheader("🔑 Alpha Vantage API Key")
    st.text_input("API Key (Alpha Vantage)", value=st.session_state.av_key, type="password", key="av_key")
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
    data = fetch_quote_av(symbol, st.session_state.av_key)

    if not data:
        st.error("No se pudo obtener la cotización desde Alpha Vantage. Verifica la API Key o inténtalo de nuevo.")
        if debug:
            st.info("Activa una clave válida y asegúrate de no exceder los límites del plan gratuito (5 req/min).")
        st.stop()

    price = data.get("price")
    currency = data.get("currency")
    change = data.get("change")
    change_pct = data.get("change_pct")
    prev_close = data.get("prev_close")
    ts = data.get("ts")
    source_used = data.get("source")

    when_str = "—"  # AV no trae timestamp en GLOBAL_QUOTE

    st.subheader(f"{selected_name} ({symbol})")
    st.caption(f"**Fuente real**: {source_used}")
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

    st.caption(f"Hora de mercado: {when_str}")

    if debug:
        with st.expander("Detalles técnicos (JSON crudo)"):
            st.code(json.dumps(data.get("raw", {}), ensure_ascii=False, indent=2))

# ============================
# Tests rápidos
# ============================
st.divider()
st.markdown("### 🧪 Test rápido (Alpha Vantage)")
col_t1, col_t2 = st.columns(2)
with col_t1:
    if st.button("Probar SAN.MC e ITX.MC"):
        st.cache_data.clear()
        res = {sym: bool(fetch_quote_av(sym, st.session_state.av_key)) for sym in ("SAN.MC", "ITX.MC")}
        st.write({k: ("OK" if v else "FAIL") for k,v in res.items()})
        if all(res.values()):
            st.success("Tests OK: Alpha Vantage devolvió cotizaciones.")
        else:
            st.warning("Alguno de los símbolos no devolvió datos. Revisa la API Key / límites / soporte de símbolos.")
with col_t2:
    if st.button("Probar variantes de SAN (SAN.MC → SAN → BME:SAN)"):
        st.cache_data.clear()
        variants = ["SAN.MC", "SAN", "BME:SAN"]
        res = {sym: bool(fetch_quote_av(sym, st.session_state.av_key, try_variants=False)) for sym in variants}
        st.write({k: ("OK" if v else "FAIL") for k,v in res.items()})
