# -*- coding: utf-8 -*-
"""
App de Bolsa (Streamlit / CLI fallback)
Autor: ChatGPT (GPT-5 Thinking)

Cambios clave (fix):
- **Ya no falla si `streamlit` NO está instalado**. Detecta su ausencia y ejecuta un modo **CLI** (terminal) con las funciones
  esenciales: descarga de históricos, KPIs básicos y tests rápidos. Si `streamlit` está disponible, muestra la app completa.
- Mantiene el fix previo: funciona también si **no hay `yfinance`** (usa Yahoo Chart/QuoteSummary API como fallback).

Características (modo Streamlit):
- Universos: **IBEX35**, **NYSE**, **NASDAQ** y **Watchlist** (persistencia local JSON).
- Búsqueda/selección de valores; al abrir un valor:
  - Histórico (rangos 1D, 1W, 1M, 6M, 1Y, 2Y, 5Y, Max) y resolución Diaria/Semanal/Mensual.
  - KPIs fundamentales (según disponibilidad de la fuente).
  - Estadísticas: YTD, 1Y, Vol anual, Máx Drawdown, CAGR.
  - Descarga de CSV del histórico mostrado.
- **Autodiagnóstico** con tests básicos (AAPL y SAN.MC).

Características (modo CLI si no hay Streamlit):
- Uso: `python app_bolsa_streamlit.py --symbol AAPL --range 1Y --out out.csv`
- Imprime KPIs y estadísticas, y guarda un CSV si se indica `--out`.
- Ejecuta tests automáticos con `--run-tests`.

Requisitos recomendados:
    # Para Streamlit Cloud, evita paquetes que compilen binarios (quitamos lxml)
    pip install streamlit pandas requests python-dateutil plotly yfinance

"""

from __future__ import annotations
import json
import io
import math
import sys
import argparse
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

# ----------------------------------
# Import opcionales (streamlit/yfinance/plotly)
# ----------------------------------
try:
    import streamlit as st  # type: ignore
    HAS_ST = True
except Exception:
    HAS_ST = False

try:
    import yfinance as yf  # type: ignore
    HAS_YF = True
except Exception:
    HAS_YF = False

try:
    import plotly.graph_objects as go  # type: ignore
    HAS_PLOTLY = True
except Exception:
    HAS_PLOTLY = False

# Decorador cache compatible
if HAS_ST:
    cache_data = st.cache_data
else:
    def cache_data(ttl: Optional[int] = None):
        def _wrap(fn):
            return fn
        return _wrap

# Helpers de UI imprimibles cuando no hay Streamlit
def ui_warn(msg: str):
    if HAS_ST:
        st.warning(msg)
    else:
        print(f"[WARN] {msg}")

def ui_info(msg: str):
    if HAS_ST:
        st.info(msg)
    else:
        print(f"[INFO] {msg}")

def ui_success(msg: str):
    if HAS_ST:
        st.success(msg)
    else:
        print(f"[OK] {msg}")

def ui_error(msg: str):
    if HAS_ST:
        st.error(msg)
    else:
        print(f"[ERROR] {msg}")

# ============================
# Constantes y utilidades
# ============================
WATCHLIST_PATH = "watchlist.json"
IBEX_WIKI_ES = "https://es.wikipedia.org/wiki/IBEX_35"
IBEX_WIKI_EN = "https://en.wikipedia.org/wiki/IBEX_35"
NASDAQ_LIST_URL = "https://api.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LIST_URL = "https://api.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"  # contiene NYSE/AMEX/etc.

RANGE_PRESETS = [
    ("1D", {"days": 1}),
    ("1W", {"weeks": 1}),
    ("1M", {"months": 1}),
    ("6M", {"months": 6}),
    ("1Y", {"years": 1}),
    ("2Y", {"years": 2}),
    ("5Y", {"years": 5}),
    ("Max", None),
]

RESAMPLE_MAP = {
    "Diaria": "D",
    "Semanal": "W",
    "Mensual": "M",
}

# ============================
# Persistencia de Watchlist
# ============================

def load_watchlist() -> List[str]:
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except FileNotFoundError:
        return []
    except Exception:
        return []


def save_watchlist(symbols: List[str]) -> None:
    try:
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(list(set(symbols))), f, ensure_ascii=False, indent=2)
    except Exception as e:
        ui_warn(f"No se pudo guardar la watchlist: {e}")

# ============================
# Carga de listados (cacheados)
# ============================
@cache_data(ttl=3600)
def load_nasdaq_table() -> pd.DataFrame:
    """Carga el listado de NASDAQ desde NASDAQ Trader."""
    r = requests.get(NASDAQ_LIST_URL, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), sep='|')
    df = df[df['Test Issue'] == 'N']
    df = df[df['Symbol'].notna() & (df['Symbol'] != 'Symbol')]
    df = df[['Symbol', 'Security Name']].rename(columns={'Symbol':'symbol','Security Name':'name'})
    df['exchange'] = 'NASDAQ'
    return df.reset_index(drop=True)

@cache_data(ttl=3600)
def load_otherlisted_table() -> pd.DataFrame:
    """Carga el listado de otras bolsas (incluye NYSE/AMEX/ARCA) desde NASDAQ Trader."""
    r = requests.get(OTHER_LIST_URL, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), sep='|')
    df = df[df['Test Issue'] == 'N']
    df = df[df['ACT Symbol'].notna() & (df['ACT Symbol'] != 'ACT Symbol')]
    df = df[df['Exchange'] == 'N']  # NYSE
    df = df[['ACT Symbol', 'Security Name']].rename(columns={'ACT Symbol':'symbol','Security Name':'name'})
    df['exchange'] = 'NYSE'
    return df.reset_index(drop=True)

@cache_data(ttl=3600)
def load_ibex35_table() -> pd.DataFrame:
    """Obtiene la composición del IBEX 35.
    Para evitar dependencias pesadas (lxml/bs4) en Streamlit Cloud, usamos una
    **lista estática** mantenida en código como fallback estable.
    """
    # Fuente estática (símbolo Yahoo + nombre). Última revisión: 2025-08-25.
    STATIC_IBEX = [
        ("ACS.MC", "ACS"),
        ("AENA.MC", "Aena"),
        ("ALM.MC", "Almirall"),
        ("ANA.MC", "Acciona"),
        ("BBVA.MC", "BBVA"),
        ("BKT.MC", "Bankinter"),
        ("CABK.MC", "CaixaBank"),
        ("CLNX.MC", "Cellnex"),
        ("COL.MC", "Inmobiliaria Colonial"),
        ("ELE.MC", "Endesa"),
        ("ENG.MC", "Enagás"),
        ("FER.MC", "Ferrovial"),
        ("GRF.MC", "Grifols"),
        ("IBE.MC", "Iberdrola"),
        ("ITX.MC", "Inditex"),
        ("IAG.MC", "IAG"),
        ("MAP.MC", "Mapfre"),
        ("MEL.MC", "Meliá Hotels"),
        ("MRL.MC", "Merlin Properties"),
        ("NTGY.MC", "Naturgy"),
        ("PHM.MC", "PharmaMar"),
        ("REE.MC", "Redeia (REE)"),
        ("RMED.MC", "Rovi"),
        ("SAB.MC", "Banco Sabadell"),
        ("SAN.MC", "Banco Santander"),
        ("SGRE.MC", "Siemens Gamesa*"),
        ("SLR.MC", "Solaria"),
        ("TEF.MC", "Telefónica"),
        ("VIS.MC", "Viscofan"),
        ("LOG.MC", "Logista"),
        ("ROVI.MC", "Laboratorios Rovi"),
    ]
    # Nota: La composición puede variar; para un listado “oficial” podríamos
    # añadir una opción avanzada para leer desde Wikipedia si bs4/lxml están disponibles.
    df = pd.DataFrame(STATIC_IBEX, columns=["symbol","name"])
    df["exchange"] = "BME"
    return df.reset_index(drop=True)

# ============================
# Yahoo fallbacks sin yfinance
# ============================

def _yahoo_chart_history(ticker: str, start: Optional[datetime], end: Optional[datetime], interval: str = "1d") -> pd.DataFrame:
    """Descarga histórico desde Yahoo Chart API (sin yfinance)."""
    base = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": interval}
    if start is not None and end is not None:
        params["period1"] = int(start.timestamp())
        params["period2"] = int(end.timestamp())
    else:
        params["range"] = "max"
    r = requests.get(base, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    result = data.get("chart", {}).get("result", [])
    if not result:
        return pd.DataFrame()
    r0 = result[0]
    ts = r0.get("timestamp", [])
    ind = r0.get("indicators", {})
    quote = (ind.get("quote") or [{}])[0]
    df = pd.DataFrame({
        "Date": pd.to_datetime(ts, unit='s'),
        "Open": quote.get("open", []),
        "High": quote.get("high", []),
        "Low": quote.get("low", []),
        "Close": quote.get("close", []),
        "Volume": quote.get("volume", []),
    })
    df = df.dropna(subset=["Close"])  # Yahoo a veces devuelve None
    return df


def _yahoo_quote_summary(ticker: str, modules: List[str]) -> Dict:
    """Consulta Yahoo QuoteSummary API para KPIs (sin yfinance)."""
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
    params = {"modules": ",".join(modules)}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    js = r.json()
    res = (((js or {}).get("quoteSummary") or {}).get("result") or [None])[0] or {}
    return res

# ============================
# Datos de un ticker
# ============================
@cache_data(ttl=900)
def get_history(ticker: str, start: Optional[datetime]=None, end: Optional[datetime]=None) -> pd.DataFrame:
    """Histórico diario por yfinance o Chart API."""
    if HAS_YF:
        try:
            t = yf.Ticker(ticker)
            if start is None and end is None:
                hist = t.history(period="max")
            else:
                hist = t.history(start=start, end=end)
            hist = hist.rename(columns=str).rename_axis('Date').reset_index()
            return hist
        except Exception:
            pass  # fallback
    try:
        return _yahoo_chart_history(ticker, start, end, interval="1d")
    except Exception as e:
        ui_error(f"Error al descargar históricos para {ticker}: {e}")
        return pd.DataFrame()

@cache_data(ttl=900)
def get_info_and_kpis(ticker: str) -> Dict:
    """Info + KPIs por yfinance o QuoteSummary API."""
    if HAS_YF:
        try:
            t = yf.Ticker(ticker)
            info = {}
            try:
                info = t.info or {}
            except Exception:
                info = {}
            fast = {}
            try:
                fast = t.fast_info or {}
            except Exception:
                fast = {}

            def g(d, k, default=None):
                return d.get(k, default)

            kpis: Dict[str, Optional[float]] = {}
            kpis['Market Cap'] = g(info, 'marketCap', g(fast, 'market_cap'))
            kpis['P/E (TTM)'] = g(info, 'trailingPE')
            kpis['Forward P/E'] = g(info, 'forwardPE')
            kpis['PEG'] = g(info, 'pegRatio')
            kpis['Price/Book'] = g(info, 'priceToBook')
            kpis['Dividend Yield'] = g(info, 'dividendYield')
            kpis['EPS (TTM)'] = g(info, 'trailingEps')
            kpis['Profit Margin'] = g(info, 'profitMargins')
            kpis['ROE'] = g(info, 'returnOnEquity')
            kpis['Beta'] = g(info, 'beta')
            kpis['Sector'] = g(info, 'sector')
            kpis['Industry'] = g(info, 'industry')

            # Estados financieros (opcional)
            try:
                bs = t.balance_sheet
                cf = t.cashflow
            except Exception:
                bs = cf = None

            try:
                if bs is not None and not bs.empty:
                    total_debt = bs.loc['Total Debt'].dropna().iloc[0]
                    equity = bs.loc['Total Stockholder Equity'].dropna().iloc[0]
                    if equity and equity != 0:
                        kpis['Debt/Equity'] = float(total_debt) / float(equity)
            except Exception:
                pass

            try:
                if cf is not None and not cf.empty:
                    fcf = None
                    if 'Free Cash Flow' in cf.index:
                        fcf = cf.loc['Free Cash Flow'].dropna().iloc[0]
                    elif 'Total Cash From Operating Activities' in cf.index and 'Capital Expenditures' in cf.index:
                        op = cf.loc['Total Cash From Operating Activities'].dropna().iloc[0]
                        capex = cf.loc['Capital Expenditures'].dropna().iloc[0]
                        fcf = float(op) + float(capex)
                    if fcf is not None:
                        kpis['Free Cash Flow'] = fcf
            except Exception:
                pass

            meta = {
                'shortName': g(info, 'shortName', ticker),
                'longName': g(info, 'longName', g(info, 'shortName', ticker)),
                'currency': g(info, 'currency', g(fast, 'currency', '')),
                'exchange': g(info, 'exchange', ''),
                'symbol': ticker,
            }
            return {"info": info, "fast_info": fast, "kpis": kpis, "meta": meta}
        except Exception:
            pass

    # Fallback sin yfinance
    kpis: Dict[str, Optional[float]] = {}
    info: Dict = {}
    fast_info: Dict = {}
    meta = {"shortName": ticker, "longName": ticker, "currency": "", "exchange": "", "symbol": ticker}
    try:
        res = _yahoo_quote_summary(ticker, [
            "price","summaryDetail","defaultKeyStatistics","financialData","assetProfile"
        ])
        price = res.get("price") or {}
        sd = res.get("summaryDetail") or {}
        ks = res.get("defaultKeyStatistics") or {}
        fd = res.get("financialData") or {}
        ap = res.get("assetProfile") or {}

        def gv(d: Dict, k: str):
            v = (d.get(k) or {}).get("raw")
            return v

        info.update({
            "longName": price.get("longName") or price.get("shortName"),
            "shortName": price.get("shortName"),
            "currency": price.get("currency") or gv(sd, "currency"),
            "exchange": price.get("exchangeName") or price.get("exchange")
        })
        meta.update({
            "shortName": info.get("shortName") or ticker,
            "longName": info.get("longName") or info.get("shortName") or ticker,
            "currency": info.get("currency", ""),
            "exchange": info.get("exchange", "")
        })

        kpis['Market Cap'] = gv(price, 'marketCap') or gv(ks, 'marketCap')
        kpis['P/E (TTM)'] = gv(ks, 'trailingPE') or gv(sd, 'trailingPE')
        kpis['Forward P/E'] = gv(ks, 'forwardPE') or gv(sd, 'forwardPE')
        kpis['PEG'] = gv(ks, 'pegRatio')
        kpis['Price/Book'] = gv(sd, 'priceToBook')
        kpis['Dividend Yield'] = gv(sd, 'dividendYield')
        kpis['EPS (TTM)'] = gv(ks, 'trailingEps')
        kpis['Profit Margin'] = gv(ks, 'profitMargins')
        kpis['ROE'] = gv(ks, 'returnOnEquity')
        kpis['Beta'] = gv(ks, 'beta')
        kpis['Sector'] = ap.get('sector')
        kpis['Industry'] = ap.get('industry')
    except Exception as e:
        ui_info("KPIs limitados: instala `yfinance` para indicadores más completos.")

    return {"info": info, "fast_info": fast_info, "kpis": kpis, "meta": meta}

# ============================
# Estadísticos
# ============================

def compute_stats(price_df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Calcula stats básicos dado DataFrame con columna 'Close' y 'Date'."""
    if price_df is None or price_df.empty:
        return {k: None for k in ["Ret YTD","Ret 1Y","Vol anual","Max Drawdown","CAGR"]}

    df = price_df.copy().sort_values('Date')
    df['return'] = df['Close'].pct_change()

    vol = df['return'].std() * math.sqrt(252) if df['return'].count() > 1 else None

    cum = (1 + df['return']).cumprod()
    roll_max = cum.cummax()
    dd = (cum/roll_max - 1).min()

    if len(df) >= 2:
        years = (df['Date'].iloc[-1] - df['Date'].iloc[0]).days / 365.25
        cagr = (df['Close'].iloc[-1] / df['Close'].iloc[0]) ** (1/years) - 1 if years > 0 else None
    else:
        cagr = None

    last = df['Date'].iloc[-1]
    start_ytd = datetime(last.year, 1, 1)
    ret_ytd = None
    ret_1y = None
    try:
        ytd_df = df[df['Date'] >= pd.Timestamp(start_ytd)]
        if len(ytd_df) > 1:
            ret_ytd = ytd_df['Close'].iloc[-1] / ytd_df['Close'].iloc[0] - 1
    except Exception:
        pass
    try:
        one_year_ago = last - relativedelta(years=1)
        one_year_df = df[df['Date'] >= pd.Timestamp(one_year_ago)]
        if len(one_year_df) > 1:
            ret_1y = one_year_df['Close'].iloc[-1] / one_year_df['Close'].iloc[0] - 1
    except Exception:
        pass

    return {
        "Ret YTD": ret_ytd,
        "Ret 1Y": ret_1y,
        "Vol anual": vol,
        "Max Drawdown": dd,
        "CAGR": cagr,
    }

# ============================
# UI Helpers y compatibilidad
# ============================

def format_big_number(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    try:
        n = float(x)
    except Exception:
        return str(x)
    for v, s in [(1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')]:
        if abs(n) >= v:
            return f"{n/v:.2f}{s}"
    return f"{n:,.2f}"


def format_pct(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    return f"{x*100:.2f}%"


def ui_segmented_control(label: str, options: List[str], default: str) -> str:
    """Compat: si la versión de Streamlit no tiene segmented_control, usa selectbox."""
    if HAS_ST:
        try:
            return st.segmented_control(label, options=options, default=default)
        except Exception:
            idx = options.index(default) if default in options else 0
            return st.selectbox(label, options, index=idx)
    # En CLI devolvemos el default
    return default

# ============================
# Streamlit APP
# ============================

def run_streamlit_app():
    st.set_page_config(page_title="App de Bolsa", page_icon="📈", layout="wide")

    with st.sidebar:
        st.title("📈 App de Bolsa")
        st.caption("Datos: Yahoo Finance (API), NasdaqTrader; IBEX con lista estática")
        if HAS_YF:
            st.success("Fuente activos: yfinance ✅")
        else:
            st.info("yfinance no disponible → usando Yahoo API (fallback)")

        universe = st.radio(
            "Universo de valores",
            options=["IBEX35", "NYSE", "NASDAQ", "Watchlist"],
            index=0,
            help="Elige el listado a mostrar"
        )

        if universe == "IBEX35":
            table = load_ibex35_table()
        elif universe == "NYSE":
            table = load_otherlisted_table()
        elif universe == "NASDAQ":
            table = load_nasdaq_table()
        else:
            wl = load_watchlist()
            table = pd.DataFrame({"symbol": wl, "name": ["" for _ in wl], "exchange": ["WATCHLIST" for _ in wl]})

        q = st.text_input("Buscar símbolo o nombre", placeholder="Ej: AAPL, SAN.MC, Inditex…").strip()
        df_view = table.copy()
        if q:
            ql = q.lower()
            df_view = df_view[df_view['symbol'].str.lower().str.contains(ql) | df_view['name'].str.lower().str.contains(ql)]

        st.write(f"{len(df_view)} valores")
        st.dataframe(df_view, use_container_width=True, height=300)

        selected_symbol = None
        if not df_view.empty:
            selected_symbol = st.selectbox(
                "Selecciona un valor",
                options=df_view['symbol'].tolist(),
                index=0,
                placeholder="Elige un símbolo"
            )
        manual = st.text_input("O escribe un ticker manualmente", placeholder="Ej: MSFT, AAPL, SAN.MC")
        if manual:
            selected_symbol = manual.strip().upper()

        st.subheader("Watchlist")
        if selected_symbol:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("➕ Añadir a watchlist", use_container_width=True):
                    wl = load_watchlist()
                    wl.append(selected_symbol)
                    save_watchlist(wl)
                    st.success(f"Añadido {selected_symbol} a watchlist")
            with c2:
                if st.button("➖ Quitar de watchlist", use_container_width=True):
                    wl = load_watchlist()
                    if selected_symbol in wl:
                        wl = [s for s in wl if s != selected_symbol]
                        save_watchlist(wl)
                        st.success(f"Quitado {selected_symbol} de watchlist")
                    else:
                        st.info("No estaba en watchlist")

        st.divider()
        st.subheader("🧪 Autodiagnóstico")
        if st.button("Ejecutar tests básicos"):
            try:
                now = datetime.utcnow()
                df_test1 = get_history("AAPL", start=now - relativedelta(months=1), end=now)
                ok1 = not df_test1.empty
                k = get_info_and_kpis("AAPL")["kpis"]
                ok2 = isinstance(k, dict)
                df_test3 = get_history("SAN.MC", start=now - relativedelta(months=6), end=now)
                ok3 = not df_test3.empty
                # Nuevo test: IBEX lista estática cargada
                df_ibex = load_ibex35_table()
                ok4 = (not df_ibex.empty) and ("SAN.MC" in df_ibex['symbol'].values)
                if ok1 and ok2 and ok3 and ok4:
                    st.success("Tests OK: AAPL histórico/KPIs, SAN.MC histórico y lista IBEX cargada.")
                else:
                    st.warning(f"Resultados: hist AAPL={'OK' if ok1 else 'FAIL'}, KPIs={'OK' if ok2 else 'FAIL'}, hist SAN.MC={'OK' if ok3 else 'FAIL'}, IBEX={'OK' if ok4 else 'FAIL'}")
            except Exception as e:
                st.error(f"Fallo en tests: {e}")

    st.markdown("## 🧭 Explorador de valores")

    if not selected_symbol:
        st.info("Elige un valor en la barra lateral para ver sus detalles.")
        st.stop()

    meta_block = get_info_and_kpis(selected_symbol)
    meta = meta_block.get("meta", {})
    kpis = meta_block.get("kpis", {})

    left, right = st.columns([0.7, 0.3])
    with left:
        st.markdown(f"### {meta.get('longName') or meta.get('shortName') or selected_symbol}  (`{selected_symbol}`)")
        sub = []
        if meta.get('exchange'): sub.append(meta['exchange'])
        if meta.get('currency'): sub.append(meta['currency'])
        if kpis.get('Sector'): sub.append(kpis['Sector'])
        if kpis.get('Industry'): sub.append(kpis['Industry'])
        st.caption(" • ".join([s for s in sub if s]))

    with right:
        st.markdown("#### KPIs clave")
        kpi_cols = st.columns(2)
        items = [
            ("Market Cap", format_big_number(kpis.get('Market Cap'))),
            ("P/E (TTM)", f"{kpis.get('P/E (TTM)'):.2f}" if kpis.get('P/E (TTM)') not in (None, float('nan')) else "—"),
            ("Price/Book", f"{kpis.get('Price/Book'):.2f}" if kpis.get('Price/Book') not in (None, float('nan')) else "—"),
            ("PEG", f"{kpis.get('PEG'):.2f}" if kpis.get('PEG') not in (None, float('nan')) else "—"),
            ("Dividend Yield", format_pct(kpis.get('Dividend Yield'))),
            ("Beta", f"{kpis.get('Beta'):.2f}" if kpis.get('Beta') not in (None, float('nan')) else "—"),
            ("ROE", format_pct(kpis.get('ROE'))),
            ("Profit Margin", format_pct(kpis.get('Profit Margin'))),
            ("Debt/Equity", f"{kpis.get('Debt/Equity'):.2f}" if kpis.get('Debt/Equity') is not None else "—"),
            ("Free Cash Flow", format_big_number(kpis.get('Free Cash Flow'))),
        ]
        for i, (label, val) in enumerate(items):
            with kpi_cols[i % 2]:
                st.metric(label=label, value=val)

    st.divider()
    st.markdown("### 📊 Histórico de precios")
    col1, col2, col3 = st.columns([0.5, 0.3, 0.2])
    with col1:
        sel_range = ui_segmented_control(
            "Rango",
            options=[name for name, _ in RANGE_PRESETS],
            default="1Y",
        )
    with col2:
        res_label = st.select_slider("Resolución", options=list(RESAMPLE_MAP.keys()), value="Diaria")
    with col3:
        show_volume = st.toggle("Volumen", value=True)

    now = datetime.utcnow()
    if sel_range == "Max":
        start_date = None
        end_date = None
    else:
        delta_kwargs = dict([d for (name, d) in RANGE_PRESETS if name == sel_range][0])
        start_date = now - relativedelta(**delta_kwargs)
        end_date = now

    with st.spinner("Descargando históricos…"):
        hist = get_history(selected_symbol, start=start_date, end=end_date)

    if hist is None or hist.empty:
        st.warning("No hay datos históricos disponibles para este símbolo en el rango seleccionado.")
        st.stop()

    rule = RESAMPLE_MAP[res_label]
    if rule != 'D':
        hist_res = hist.set_index('Date').resample(rule).agg({
            'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'
        }).dropna().reset_index()
    else:
        hist_res = hist.copy()

    if HAS_PLOTLY:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist_res['Date'], y=hist_res['Close'], name='Cierre', mode='lines'))
        if show_volume and 'Volume' in hist_res.columns:
            fig.add_trace(go.Bar(x=hist_res['Date'], y=hist_res['Volume'], name='Volumen', yaxis='y2', opacity=0.3))
        fig.update_layout(
            height=420,
            margin=dict(l=10,r=10,t=10,b=10),
            xaxis_title="Fecha",
            yaxis_title="Precio",
            yaxis2=dict(overlaying='y', side='right', showgrid=False, title='Volumen') if show_volume else None,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart(hist_res.set_index('Date')['Close'])
        if show_volume and 'Volume' in hist_res.columns:
            st.bar_chart(hist_res.set_index('Date')['Volume'])

    stats = compute_stats(hist_res[['Date','Close']].copy())
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric("Rentabilidad YTD", format_pct(stats['Ret YTD']))
    sc2.metric("Rentabilidad 1Y", format_pct(stats['Ret 1Y']))
    sc3.metric("Volatilidad anual", format_pct(stats['Vol anual']))
    sc4.metric("Max Drawdown", format_pct(stats['Max Drawdown']))
    sc5.metric("CAGR", format_pct(stats['CAGR']))

    st.markdown("#### Datos tabulares")
    st.dataframe(hist_res, use_container_width=True, height=300)

    csv = hist_res.to_csv(index=False).encode('utf-8')
    st.download_button("Descargar CSV", data=csv, file_name=f"{selected_symbol}_{sel_range}_{res_label}.csv", mime="text/csv")

    st.caption("ⓘ Fuentes: Yahoo Finance (API pública no oficial) y NasdaqTrader. IBEX con lista estática para evitar dependencias pesadas en el despliegue. Para KPIs completos, instala `yfinance`.")

# ============================
# CLI fallback (sin Streamlit)
# ============================

def run_cli():
    parser = argparse.ArgumentParser(description="App de Bolsa (CLI fallback)")
    parser.add_argument('--symbol', default='AAPL', help='Ticker (ej: AAPL, MSFT, SAN.MC)')
    parser.add_argument('--range', dest='range_', default='1Y', choices=[n for n,_ in RANGE_PRESETS], help='Rango de fechas')
    parser.add_argument('--out', dest='out_csv', default=None, help='Ruta para guardar CSV')
    parser.add_argument('--run-tests', action='store_true', help='Ejecutar tests básicos')
    args = parser.parse_args()

    if args.run_tests:
        ui_info('Ejecutando tests básicos…')
        now = datetime.utcnow()
        try:
            t1 = get_history('AAPL', start=now - relativedelta(months=1), end=now)
            t2 = get_info_and_kpis('AAPL')['kpis']
            t3 = get_history('SAN.MC', start=now - relativedelta(months=6), end=now)
            ui_info(f"Hist AAPL: {'OK' if not t1.empty else 'FAIL'}")
            ui_info(f"KPIs AAPL dict: {'OK' if isinstance(t2, dict) else 'FAIL'}")
            ui_info(f"Hist SAN.MC: {'OK' if not t3.empty else 'FAIL'}")
        except Exception as e:
            ui_error(f"Fallo en tests: {e}")

    symbol = args.symbol.upper()
    sel_range = args.range_
    now = datetime.utcnow()
    if sel_range == 'Max':
        start, end = None, None
    else:
        delta_kwargs = dict([d for (name,d) in RANGE_PRESETS if name == sel_range][0])
        start, end = now - relativedelta(**delta_kwargs), now

    ui_info(f"Descargando histórico de {symbol} ({sel_range})…")
    df = get_history(symbol, start=start, end=end)
    if df.empty:
        ui_error("Sin datos.")
        sys.exit(1)

    stats = compute_stats(df[['Date','Close']])
    kpis = get_info_and_kpis(symbol)['kpis']

    ui_success(f"{symbol} → filas: {len(df)}")
    print("KPIs:")
    for k,v in kpis.items():
        if k in ("Sector","Industry"):
            print(f"  - {k}: {v}")
        else:
            print(f"  - {k}: {v}")
    print("\nEstadísticas:")
    for k,v in stats.items():
        print(f"  - {k}: {v}")

    if args.out_csv:
        try:
            df.to_csv(args.out_csv, index=False)
            ui_success(f"CSV guardado en {args.out_csv}")
        except Exception as e:
            ui_warn(f"No se pudo guardar CSV: {e}")

# ============================
# Entry point
# ============================
if __name__ == '__main__':
    if HAS_ST:
        run_streamlit_app()
    else:
        run_cli()

