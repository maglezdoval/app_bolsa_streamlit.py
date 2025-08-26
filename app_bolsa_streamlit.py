# -*- coding: utf-8 -*-
"""
Mini App → Cotizaciones por índice usando **Yahoo Finance (scraping)**
Autor: ChatGPT (GPT-5 Thinking)

Estrategia:
- Obtenemos **la lista de componentes** de cada índice **scrapeando la página de componentes** de Yahoo Finance
  (S&P 500 = ^GSPC, NASDAQ 100 = ^NDX, IBEX 35 = ^IBEX) intentando `?count=` grande.
- Después pedimos las **cotizaciones en lote** a un endpoint JSON público de Yahoo (`/v7/finance/quote`) para
  esos símbolos (también es scraping de Yahoo, sin API key).

Fuentes (páginas de componentes de Yahoo):
  - S&P 500 → https://finance.yahoo.com/quote/%5EGSPC/components
  - NASDAQ 100 → https://finance.yahoo.com/quote/%5ENDX/components
  - IBEX 35 → https://finance.yahoo.com/quote/%5EIBEX/components

Notas importantes:
- Sin `bs4`/`lxml`: parseamos **JSON embebido** en el HTML (clave `components`).
- Si Yahoo solo entrega ~30 visibles, intentamos con `?count=600` (S&P), `?count=200` (NDX), `?count=60` (IBEX).
- Si falla la extracción, hacemos **fallback** a una lista estática mínima por índice para no dejar en blanco.
- Cacheamos 60s (`st.cache_data`) y permitimos **Actualizar** para limpiar caché.

Dependencias mínimas:
    streamlit==1.37.1
    requests==2.32.3
(opcional) pandas si quieres mejores tablas (suele venir en Streamlit Cloud)
"""

from __future__ import annotations
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re
import json
import math
import requests
import streamlit as st

# =============== Config general ===============
st.set_page_config(page_title="Scraping Yahoo · IBEX · NDX · S&P500", page_icon="🟣", layout="wide")
MAD = ZoneInfo("Europe/Madrid")
UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

YF_COMPONENTS = {
    "S&P 500": [
        "https://finance.yahoo.com/quote/%5EGSPC/components?count=600",
        "https://finance.yahoo.com/quote/%5EGSPC/components",
    ],
    "NASDAQ 100": [
        "https://finance.yahoo.com/quote/%5ENDX/components?count=200",
        "https://finance.yahoo.com/quote/%5ENDX/components",
    ],
    "IBEX 35": [
        "https://finance.yahoo.com/quote/%5EIBEX/components?count=60",
        "https://finance.yahoo.com/quote/%5EIBEX/components",
    ],
}

# Fallbacks mínimos por si Yahoo cambia el HTML y no podemos extraer símbolos
FALLBACK_SYMBOLS = {
    "IBEX 35": ["ITX.MC","SAN.MC","BBVA.MC","TEF.MC","IBE.MC","CABK.MC","SAB.MC","FER.MC","CLNX.MC","MAP.MC"],
    "NASDAQ 100": ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","COST"],
    "S&P 500": ["AAPL","MSFT","AMZN","NVDA","META","GOOGL","BRK-B","LLY","AVGO","JPM"],
}

@dataclass
class Quote:
    symbol: str
    name: Optional[str]
    price: Optional[float]
    change_pct: Optional[float]
    currency: Optional[str]

# =============== HTTP util ===============
@st.cache_data(ttl=60)
def fetch_text(url: str, timeout: int = 20) -> str:
    r = requests.get(url, headers=UA_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

@st.cache_data(ttl=60)
def fetch_json(url: str, params: Optional[Dict[str,Any]] = None, timeout: int = 20) -> Dict[str,Any]:
    r = requests.get(url, params=params or {}, headers=UA_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

# =============== Parser de componentes (JSON embebido) ===============
COMP_ARRAY_KEY = '"components"\s*:'

def _extract_components_array_json(html: str) -> Optional[List[Dict[str,Any]]]:
    """Busca la clave "components": [ ... ] en el HTML y devuelve la lista de objetos (dicts).
    Implementa un pequeño parser de corchetes para capturar el array incluso si hay anidados.
    """
    m = re.search(COMP_ARRAY_KEY, html)
    if not m:
        return None
    # Posición del primer '[' tras la clave
    i = html.find('[', m.end())
    if i == -1:
        return None
    # Escaneo con control de comillas / escapes
    depth = 0
    in_str = False
    esc = False
    j = i
    while j < len(html):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    # j es la ']' de cierre del array components
                    arr_str = html[i:j+1]
                    try:
                        return json.loads(arr_str)
                    except Exception:
                        return None
        j += 1
    return None

@st.cache_data(ttl=300)
def get_components_from_yahoo(market: str) -> List[str]:
    """Intenta extraer la **lista de símbolos** del índice desde su página de Yahoo.
    Si falla, devuelve un fallback reducido.
    """
    urls = YF_COMPONENTS[market]
    for url in urls:
        try:
            html = fetch_text(url)
            arr = _extract_components_array_json(html)
            if arr and isinstance(arr, list):
                syms: List[str] = []
                for item in arr:
                    # Cada item debería ser un objeto con `symbol` y posiblemente `longName/shortName`
                    sym = item.get("symbol") if isinstance(item, dict) else None
                    if sym and isinstance(sym, str):
                        # Yahoo usa `BRK.B` como "BRK.B"; su endpoint JSON soporta el punto.
                        syms.append(sym)
                # Deduplicar conservando orden
                seen = set()
                ordered = []
                for s in syms:
                    if s not in seen and not s.startswith('^'):
                        seen.add(s)
                        ordered.append(s)
                if ordered:
                    return ordered
        except Exception:
            continue
    # Fallback mínimo
    return FALLBACK_SYMBOLS.get(market, [])

# =============== Cotizaciones (Yahoo JSON) ===============
YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

@st.cache_data(ttl=60)
def get_quotes_yahoo(symbols: List[str]) -> List[Quote]:
    """Descarga cotizaciones en lotes desde Yahoo v7 quote. Sin API key.
    Devuelve lista de Quote.
    """
    out: List[Quote] = []
    if not symbols:
        return out
    # Lotes de 50 para no pasarnos de querystring
    CHUNK = 50
    for k in range(0, len(symbols), CHUNK):
        chunk = symbols[k:k+CHUNK]
        params = {"symbols": ",".join(chunk)}
        try:
            js = fetch_json(YF_QUOTE_URL, params=params)
            results = (((js or {}).get("quoteResponse") or {}).get("result") or [])
            for r in results:
                out.append(Quote(
                    symbol=r.get("symbol"),
                    name=r.get("shortName") or r.get("longName"),
                    price=r.get("regularMarketPrice"),
                    change_pct=r.get("regularMarketChangePercent"),
                    currency=r.get("currency"),
                ))
        except Exception:
            continue
    # Dedup por símbolo (por si Yahoo devuelve duplicados)
    seen = set()
    dedup: List[Quote] = []
    for q in out:
        if q.symbol and q.symbol not in seen:
            seen.add(q.symbol)
            dedup.append(q)
    return dedup

# =============== UI ===============
st.title("📈 Cotizaciones por índice — Yahoo Finance (scraping)")
st.caption("Se extraen los **componentes** del índice desde la página de Yahoo y luego se piden **precios** al endpoint público /v7/finance/quote.")

with st.sidebar:
    market = st.radio("Elige mercado", ["IBEX 35", "NASDAQ 100", "S&P 500"], index=0)
    limit = st.slider("Límite de filas a mostrar", min_value=10, max_value=600, value=120, step=10)
    refresh = st.button("Actualizar (limpiar caché)")
    debug = st.toggle("Debug")

if refresh:
    st.cache_data.clear()

# 1) Símbolos del índice (scraping HTML de Yahoo)
syms = get_components_from_yahoo(market)

if not syms:
    st.error("No se pudieron extraer símbolos del índice desde Yahoo. Prueba más tarde o activa Debug.")
    st.stop()

st.subheader(f"{market} — {len(syms)} símbolos detectados")

# 2) Cotizaciones (Yahoo JSON v7)
quotes = get_quotes_yahoo(syms[:limit])

# Filtro
flt = st.text_input("Filtrar por símbolo o nombre", "").strip().lower()
if flt:
    quotes = [q for q in quotes if (q.symbol and flt in q.symbol.lower()) or (q.name and flt in q.name.lower())]

# Mostrar tabla
try:
    import pandas as pd
except Exception:
    pd = None

rows = [
    {
        "Símbolo": q.symbol,
        "Nombre": q.name,
        "Precio": q.price,
        "% Día": (round(q.change_pct, 2) if isinstance(q.change_pct, (float, int)) else None),
        "Divisa": q.currency,
    }
    for q in quotes
]

if pd is not None:
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
else:
    st.table(rows)

st.caption("Actualiza para refrescar datos (caché 60s). Yahoo puede limitar solicitudes.")

# =============== Debug ===============
if debug:
    st.divider()
    st.markdown("### Debug")
    st.write({"market": market, "symbols_detected": len(syms), "first_10": syms[:10]})
    # Enseña un fragmento del HTML de componentes de la primera URL que funcione
    for url in YF_COMPONENTS[market]:
        try:
            html = fetch_text(url)
            st.markdown(f"**Fuente componentes**: {url}")
            st.code(html[:1500])
            break
        except Exception as e:
            st.write({"error_fetch": str(e), "url": url})

# =============== Tests ===============
st.divider()
st.markdown("### 🧪 Tests de scraping Yahoo")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Test S&P 500 (>=100 símbolos)"):
        st.cache_data.clear()
        n = len(get_components_from_yahoo("S&P 500"))
        st.write({"count": n})
        st.success("OK" if n >= 100 else "Bajo: puede que Yahoo limite o cambie HTML")
with col2:
    if st.button("Test NASDAQ 100 (>=60 símbolos)"):
        st.cache_data.clear()
        n = len(get_components_from_yahoo("NASDAQ 100"))
        st.write({"count": n})
        st.success("OK" if n >= 60 else "Bajo: puede que Yahoo limite o cambie HTML")
with col3:
    if st.button("Test IBEX 35 (>=20 símbolos)"):
        st.cache_data.clear()
        n = len(get_components_from_yahoo("IBEX 35"))
        st.write({"count": n})
        st.success("OK" if n >= 20 else "Bajo: puede que Yahoo limite o cambie HTML")

# EOF
