# -*- coding: utf-8 -*-
"""
Mini App IBEX35 → Última Cotización (robusta)
Autor: ChatGPT (GPT-5 Thinking)

Objetivo: app mínima que selecciona una empresa del IBEX35 y muestra su **última cotización**.

⚙️ Dependencias mínimas (para Streamlit Cloud sin bloqueos):
    streamlit==1.37.1
    requests==2.32.3

🔧 Mejoras para evitar el error "No se pudo obtener la cotización":
- Añadido **User-Agent** y cabeceras a las peticiones HTTP (algunos proxies bloquean
  `python-requests` por defecto).
- Tres **métodos de respaldo** a Yahoo:
  1) `quote` v7  → precio actual.
  2) `quoteSummary` v10 (módulo `price`) → precio actual.
  3) `chart` v8 (range=1d, interval=1d) → último cierre si lo anterior falla.
- Botón **Actualizar** que fuerza limpiar caché (`st.cache_data.clear()`).
- **Modo debug** para mostrar respuesta cruda y el método usado.

Notas:
- Fuente: Yahoo Finance (API pública no oficial). Puede tener límites/latencia.
- "Última cotización" = `regularMarketPrice` si está disponible; si no, último `close` del día (fallback `chart`).
"""

from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional

import json
import requests
import streamlit as st

# ============================
# Configuración
# ============================
st.set_page_config(page_title="IBEX35 · Última Cotización", page_icon="💶", layout="centered")

# Lista estática IBEX35 (símbolo Yahoo + nombre). Última revisión: 2025-08-25.
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

YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YF_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _get_json(url: str, params: Optional[Dict] = None, timeout: int = 15) -> tuple[Optional[Dict], Optional[str]]:
    try:
        r = requests.get(url, params=params, headers=UA_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, f"HTTP error: {e}"


@st.cache_data(ttl=60)
def fetch_quote(symbol: str) -> Dict:
    """Obtiene la última cotización con múltiples fallbacks.
    Devuelve un dict con:
        - price, currency, change, change_pct, prev_close, ts, source
    o {} si no hay datos.
    """
    # 1) v7 quote
    js, err1 = _get_json(YF_QUOTE_URL, params={"symbols": symbol})
    if js:
        result = (((js or {}).get("quoteResponse") or {}).get("result") or [])
        if result:
            q = result[0]
            price = q.get("regularMarketPrice")
            if price is not None:
                return {
                    "price": price,
                    "currency": q.get("currency"),
                    "change": q.get("regularMarketChange"),
                    "change_pct": q.get("regularMarketChangePercent"),
                    "prev_close": q.get("regularMarketPreviousClose"),
                    "ts": q.get("regularMarketTime"),
                    "source": "quote_v7",
                    "raw": q,
                }

    # 2) v10 quoteSummary (price)
    js2, err2 = _get_json(YF_QUOTE_SUMMARY_URL.format(symbol=symbol), params={"modules": "price"})
    if js2:
        res = (((js2 or {}).get("quoteSummary") or {}).get("result") or [None])[0] or {}
        price_mod = res.get("price") or {}
        price = (price_mod.get("regularMarketPrice") or {}).get("raw")
        if price is None:
            price = (price_mod.get("postMarketPrice") or {}).get("raw")
        if price is not None:
            return {
                "price": price,
                "currency": price_mod.get("currency"),
                "change": (price_mod.get("regularMarketChange") or {}).get("raw"),
                "change_pct": (price_mod.get("regularMarketChangePercent") or {}).get("raw"),
                "prev_close": (price_mod.get("regularMarketPreviousClose") or {}).get("raw"),
                "ts": (price_mod.get("regularMarketTime") or {}).get("raw"),
                "source": "quoteSummary_v10",
                "raw": price_mod,
            }

    # 3) v8 chart (último cierre del día)
    js3, err3 = _get_json(YF_CHART_URL.format(symbol=symbol), params={"range": "1d", "interval": "1d"})
    if js3:
        result = (js3.get("chart") or {}).get("result") or []
        if result:
            r0 = result[0]
            ts = (r0.get("timestamp") or [None])[-1]
            ind = r0.get("indicators") or {}
            quote = (ind.get("quote") or [{}])[0]
            close_list = quote.get("close") or []
            if close_list and close_list[-1] is not None:
                return {
                    "price": close_list[-1],
                    "currency": (r0.get("meta") or {}).get("currency"),
                    "change": None,
                    "change_pct": None,
                    "prev_close": None,
                    "ts": ts,
                    "source": "chart_v8_close",
                    "raw": r0,
                }

    # Si llega aquí, no se pudo.
    return {}

# ============================
# UI
# ============================
st.title("IBEX35 → Última cotización")
st.caption("Fuente: Yahoo Finance (API pública no oficial).")

# Selector de empresa
names = [name for _, name in IBEX35]
name_to_symbol = {name: sym for sym, name in IBEX35}

c1, c2 = st.columns([0.7, 0.3])
with c1:
    selected_name = st.selectbox("Elige empresa", options=sorted(names), index=names.index("Inditex") if "Inditex" in names else 0)
with c2:
    col_a, col_b = st.columns(2)
    with col_a:
        refresh = st.button("Actualizar", use_container_width=True)
    with col_b:
        debug = st.toggle("Debug")

if refresh:
    # Fuerza invalidar la caché para reintentar inmediatamente
    st.cache_data.clear()

if selected_name:
    symbol = name_to_symbol[selected_name]
    data = fetch_quote(symbol)

    if not data:
        st.error("No se pudo obtener la cotización ahora mismo. Prueba de nuevo en unos segundos.")
        if debug:
            st.info("Sugerencias: prueba otro símbolo, verifica conectividad y revisa si Yahoo está respondiendo.")
        st.stop()

    price = data.get("price")
    currency = data.get("currency")
    change = data.get("change")
    change_pct = data.get("change_pct")
    prev_close = data.get("prev_close")
    ts = data.get("ts")  # epoch seconds
    source = data.get("source")

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
        if (change is None) and (change_pct is None):
            st.metric("Cambio", "—")
        else:
            delta_txt = []
            if change is not None:
                delta_txt.append(f"{change:+.2f}")
            if change_pct is not None:
                delta_txt.append(f"({change_pct:+.2f}%)")
            st.metric("Cambio", " ".join(delta_txt))
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
st.markdown("### 🧪 Test rápido")
if st.button("Probar SAN.MC e ITX.MC"):
    st.cache_data.clear()
    ok_san = bool(fetch_quote("SAN.MC"))
    ok_itx = bool(fetch_quote("ITX.MC"))
    st.write({"SAN.MC": "OK" if ok_san else "FAIL", "ITX.MC": "OK" if ok_itx else "FAIL"})
    if ok_san and ok_itx:
        st.success("Tests OK: se pudieron obtener cotizaciones.")
    else:
        st.warning("Alguno de los símbolos no devolvió datos ahora mismo.")
