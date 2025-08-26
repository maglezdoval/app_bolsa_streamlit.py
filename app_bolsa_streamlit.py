# -*- coding: utf-8 -*-
"""
Mini App → Cotizaciones por índice **vía Web Scraping**
Autor: ChatGPT (GPT-5 Thinking)

⚠️ Estrategia: **solo scraping** (sin APIs externas). 
Fuentes:
  - **S&P 500** → slickcharts.com/sp500
  - **NASDAQ 100** → slickcharts.com/nasdaq100
  - **IBEX 35** → tradingview.com/symbols/BME-IBC/components/

Notas importantes:
- Sin `pandas.read_html` ni `bs4` para evitar dependencias pesadas (y problemas de deploy).
- Parseo con **regex** sobre el HTML (estructura observada el 2025-08-26).
- Los sitios pueden cambiar su marcado; si algo rompe, activa **Debug** para ver el HTML parcial.
- Límite llamadas: caché `ttl=60s` y botón **Actualizar** para forzar refresco.

Dependencias mínimas:
    streamlit==1.37.1
    requests==2.32.3

"""

from __future__ import annotations
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import os
import requests
import streamlit as st

# ============================
# Configuración general
# ============================
st.set_page_config(page_title="Scraping Cotizaciones (IBEX · NASDAQ100 · S&P500)", page_icon="📈", layout="wide")

MAD = ZoneInfo("Europe/Madrid")
UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

@dataclass
class Row:
    symbol: str
    price: Optional[float]
    pct: Optional[float] = None
    name: Optional[str] = None

# ============================
# HTTP util
# ============================
@st.cache_data(ttl=60)
def fetch_html(url: str, timeout: int = 20) -> str:
    r = requests.get(url, headers=UA_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

# ============================
# Parsers
# ============================
SLICK_PATTERN = re.compile(
    r"\u3011\s*([A-Z][A-Z0-9\.]{0,9})\s*\u3011.*?\s([0-9][0-9,]*\.?[0-9]*)\s[+\-0-9\.,]+\s*\([+\-0-9\.,]+%\)",
    re.S,
)
# Explicación: "】SYMBOL】 ...   PRICE  CHG (PCT%)" en Slickcharts (ver HTML visible)

TRADINGVIEW_ROW = re.compile(
    r"\u3011\s*([A-Z]{1,6})\s*\u3011.*?\s([0-9]+(?:\.[0-9]+)?)\sEUR",
    re.S,
)
# Explicación: "】ITX】 ... 43.46 EUR ..." en TradingView components IBEX


def parse_slickcharts(html: str) -> List[Row]:
    rows: List[Row] = []
    for m in SLICK_PATTERN.finditer(html):
        sym = m.group(1).strip()
        price_txt = m.group(2).replace(",", "")
        try:
            price = float(price_txt)
        except Exception:
            price = None
        rows.append(Row(symbol=sym, price=price))
    # Deduplicar conservando orden (por si aparecen símbolos repetidos)
    seen = set()
    out: List[Row] = []
    for r in rows:
        if r.symbol not in seen:
            seen.add(r.symbol)
            out.append(r)
    return out


def parse_tradingview_ibex(html: str) -> List[Row]:
    rows: List[Row] = []
    for m in TRADINGVIEW_ROW.finditer(html):
        sym = m.group(1).strip()
        try:
            price = float(m.group(2))
        except Exception:
            price = None
        rows.append(Row(symbol=f"{sym}.MC", price=price))  # anota sufijo .MC útil para otras vistas
    # Deduplicar
    seen = set()
    out: List[Row] = []
    for r in rows:
        if r.symbol not in seen:
            seen.add(r.symbol)
            out.append(r)
    return out

# ============================
# Data providers por índice
# ============================
SOURCES = {
    "S&P 500": "https://www.slickcharts.com/sp500",
    "NASDAQ 100": "https://www.slickcharts.com/nasdaq100",
    "IBEX 35": "https://www.tradingview.com/symbols/BME-IBC/components/",
}

@st.cache_data(ttl=60)
def get_market_rows(market: str) -> List[Row]:
    url = SOURCES[market]
    html = fetch_html(url)
    if market in ("S&P 500", "NASDAQ 100"):
        return parse_slickcharts(html)
    else:
        return parse_tradingview_ibex(html)

# ============================
# UI
# ============================
st.title("📊 Cotizaciones por índice · Web Scraping")
st.caption("Fuentes: Slickcharts (S&P 500, Nasdaq 100) · TradingView (IBEX 35). Los sitios pueden cambiar su HTML.")

with st.sidebar:
    market = st.radio("Elige mercado", ["IBEX 35", "NASDAQ 100", "S&P 500"], index=0)
    refresh = st.button("Actualizar", use_container_width=True)
    debug = st.toggle("Debug")

if refresh:
    st.cache_data.clear()

try:
    rows = get_market_rows(market)
except Exception as e:
    st.error(f"No se pudo obtener datos de {market}: {e}")
    rows = []

st.subheader(f"{market} — {len(rows)} valores")

# Filtro rápido por símbolo
q = st.text_input("Filtrar por símbolo (p. ej., AAPL, MSFT, ITX.MC)", "")
if q:
    qq = q.strip().upper()
    rows = [r for r in rows if qq in r.symbol.upper()]

# Tabla
import pandas as pd  # pandas forma parte del entorno de Streamlit Cloud por defecto

if rows:
    df = pd.DataFrame([{"Símbolo": r.symbol, "Precio": r.price} for r in rows])
    st.dataframe(df, use_container_width=True)
else:
    st.warning("No se obtuvieron filas. Pulsa Actualizar o activa Debug para inspeccionar HTML.")

# Debug
if debug:
    st.divider()
    st.markdown("### Debug")
    st.code(f"Fuente: {SOURCES[market]}")
    try:
        html = fetch_html(SOURCES[market])
        # Muestra solo un fragmento para no saturar
        snippet = html[:2000]
        st.code(snippet)
    except Exception as e:
        st.error(f"Fetch HTML falló: {e}")

# ============================
# Tests rápidos (scrapers)
# ============================
st.divider()
st.markdown("### 🧪 Tests de scraping")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Test S&P 500 (>= 50)"):
        st.cache_data.clear()
        try:
            n = len(get_market_rows("S&P 500"))
            st.write({"count": n})
            st.success("OK" if n >= 50 else "Demasiado pocos; puede haber cambio de HTML")
        except Exception as e:
            st.error(str(e))
with col2:
    if st.button("Test NASDAQ 100 (>= 30)"):
        st.cache_data.clear()
        try:
            n = len(get_market_rows("NASDAQ 100"))
            st.write({"count": n})
            st.success("OK" if n >= 30 else "Demasiado pocos; puede haber cambio de HTML")
        except Exception as e:
            st.error(str(e))
with col3:
    if st.button("Test IBEX 35 (>= 20)"):
        st.cache_data.clear()
        try:
            n = len(get_market_rows("IBEX 35"))
            st.write({"count": n})
            st.success("OK" if n >= 20 else "Demasiado pocos; puede haber cambio de HTML")
        except Exception as e:
            st.error(str(e))

# EOF
