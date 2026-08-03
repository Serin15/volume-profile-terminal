"""
Aplicatie Streamlit: Volume Profile avansat (stil DeepCharts/ATAS) pentru NQ.

Layout: chart de LUMANARI (pret in timp) + Volume Profile atasat pe axa de pret,
cu barile impartite BUY/SELL (bid/ask). POC / Value Area se intind peste tot chart-ul.

Lanseaza (din D:\\Volume Profile):
    .venv\\Scripts\\python -m streamlit run app\\streamlit_app.py
"""

import os
import math
import glob
from collections import defaultdict

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core import VolumeProfileEngine, DeltaEngine
from data import load_ticks
from data.loader import PARQUET_DIR, RAW_DIR

st.set_page_config(page_title="Volume Profile — NQ", layout="wide")

TICK_SIZE = 0.25

# Paleta (dark terminal / TradingView)
C_BUY = "#26a69a"
C_SELL = "#ef5350"
C_POC = "#f7c948"
C_VA_LINE = "#7f8794"
C_VA_BAND = "rgba(76,143,255,0.07)"
C_GRID = "#222631"
C_TEXT = "#d1d4dc"
C_UP = "#26a69a"
C_DOWN = "#ef5350"

REGIME = {
    "20260706": "range-bound", "20260707": "range-bound", "20260708": "range-bound",
    "20260709": "range-bound", "20260710": "range-bound",
    "20260720": "bearish", "20260721": "bearish", "20260722": "bearish",
    "20260723": "bearish", "20260724": "bearish",
}


def discover_files():
    files = glob.glob(os.path.join(PARQUET_DIR, "*.parquet"))
    if not files:
        files = glob.glob(os.path.join(RAW_DIR, "*.csv"))
    return sorted(os.path.basename(f) for f in files)


def date_from_name(name):
    for part in name.replace(".", "-").split("-"):
        if len(part) == 8 and part.isdigit():
            return part
    return name


def nice_label(name):
    d = date_from_name(name)
    if len(d) == 8:
        regime = REGIME.get(d, "")
        pretty = f"{d[6:8]}.{d[4:6]}.{d[0:4]}"
        return f"{pretty}  ({regime})" if regime else pretty
    return name


@st.cache_data(show_spinner="Calculez profilul...")
def compute_profile(filename, va_percent):
    """Engine la 0.25 (precis). Intoarce profil + buy/sell per nivel + POC/VA/HVN/LVN."""
    tk = load_ticks(filename)

    vp = VolumeProfileEngine(tick_size=TICK_SIZE)
    vp.add_ticks_bulk(tk.price_volume())
    vpr = vp.result(va_percent=va_percent)

    de = DeltaEngine(tick_size=TICK_SIZE)
    de.add_ticks_bulk(tk.price_volume_side())
    der = de.result()

    prices = sorted(vpr.profile.keys())
    buys = [der.buy_volume_per_level.get(p, 0.0) for p in prices]
    sells = [der.sell_volume_per_level.get(p, 0.0) for p in prices]
    return {
        "symbol": tk.symbol, "n_ticks": len(tk),
        "prices": prices, "buys": buys, "sells": sells,
        "poc": vpr.poc, "vah": vpr.vah, "val": vpr.val,
        "hvn": vpr.hvn_peaks, "lvn": vpr.lvn_peaks,
        "total_volume": vpr.total_volume, "cum_delta": der.cumulative_delta,
        "buy_total": der.total_buy_volume, "sell_total": der.total_sell_volume,
    }


@st.cache_data(show_spinner=False)
def compute_candles(filename, interval):
    """Resampleaza tick-urile in lumanari OHLC + volum, pe intervalul cerut."""
    tk = load_ticks(filename)
    df = tk.df.set_index("ts")
    ohlc = df["price"].resample(interval).ohlc()
    ohlc["volume"] = df["size"].resample(interval).sum()
    ohlc = ohlc.dropna(subset=["open"])  # scoate pauza de mentenanta (fara tick-uri)
    return ohlc.reset_index()


def aggregate_split(prices, buys, sells, row_size):
    """Grupeaza nivelele fine in randuri de afisare, pastrand split buy/sell."""
    buy_b, sell_b = defaultdict(float), defaultdict(float)
    for p, bv, sv in zip(prices, buys, sells):
        b = round(math.floor(p / row_size) * row_size + row_size / 2, 4)
        buy_b[b] += bv
        sell_b[b] += sv
    bins = sorted(set(buy_b) | set(sell_b))
    return bins, [buy_b[b] for b in bins], [sell_b[b] for b in bins]


def build_figure(d, candles, row_size):
    bins, buys, sells = aggregate_split(d["prices"], d["buys"], d["sells"], row_size)
    poc, vah, val = d["poc"], d["vah"], d["val"]

    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.008,
        column_widths=[0.74, 0.26],
        subplot_titles=("PRET", "VOLUME PROFILE  (buy / sell)"),
    )

    # --- col 1: lumanari ---
    fig.add_trace(go.Candlestick(
        x=candles["ts"], open=candles["open"], high=candles["high"],
        low=candles["low"], close=candles["close"],
        increasing_line_color=C_UP, decreasing_line_color=C_DOWN,
        increasing_fillcolor=C_UP, decreasing_fillcolor=C_DOWN,
        line_width=1, name="Pret", showlegend=False,
    ), row=1, col=1)

    # --- col 2: profil split buy/sell (stacked orizontal) ---
    fig.add_trace(go.Bar(
        x=buys, y=bins, orientation="h", width=row_size * 0.9,
        marker_color=C_BUY, name="Buy", legendgroup="buy",
        hovertemplate="Pret %{y:.2f}<br>Buy %{x:,.0f}<extra></extra>"), row=1, col=2)
    fig.add_trace(go.Bar(
        x=sells, y=bins, orientation="h", width=row_size * 0.9,
        marker_color=C_SELL, name="Sell", legendgroup="sell",
        hovertemplate="Pret %{y:.2f}<br>Sell %{x:,.0f}<extra></extra>"), row=1, col=2)

    # --- POC / VA peste ambele panouri ---
    for col in (1, 2):
        fig.add_hrect(y0=val, y1=vah, fillcolor=C_VA_BAND, line_width=0, row=1, col=col)
        fig.add_hline(y=poc, line=dict(color=C_POC, width=1.3), row=1, col=col)
        fig.add_hline(y=vah, line=dict(color=C_VA_LINE, width=1, dash="dot"), row=1, col=col)
        fig.add_hline(y=val, line=dict(color=C_VA_LINE, width=1, dash="dot"), row=1, col=col)

    # Etichete POC/VAH/VAL pe marginea dreapta
    for y, txt, color in [(poc, "POC", C_POC), (vah, "VAH", "#aeb4bf"), (val, "VAL", "#aeb4bf")]:
        fig.add_annotation(x=1, xref="x2 domain", y=y, yref="y", text=f"{txt} {y:.0f} ",
                           showarrow=False, xanchor="right", font=dict(color=color, size=11),
                           bgcolor="rgba(14,17,23,0.75)")

    fig.update_layout(
        height=800, barmode="stack", bargap=0.05,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C_TEXT, size=12),
        margin=dict(l=8, r=8, t=48, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.015, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(showgrid=True, gridcolor=C_GRID, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=C_GRID, title_text="Pret", row=1, col=1)
    fig.update_yaxes(showgrid=False, row=1, col=2)
    return fig


# ============================ UI ============================

st.markdown(
    "<h2 style='margin-bottom:0'>Volume Profile — NQ</h2>"
    "<p style='color:#8a8f99;margin-top:2px'>Pret + profil split buy/sell · date Databento · engine propriu</p>",
    unsafe_allow_html=True)

files = discover_files()
if not files:
    st.error(f"Niciun fisier de date gasit in {PARQUET_DIR} sau {RAW_DIR}.")
    st.stop()

with st.sidebar:
    st.header("Setari")
    filename = st.selectbox("Ziua de tranzactionare", files, format_func=nice_label)
    interval = st.select_slider("Interval lumanari",
                                options=["1min", "5min", "15min", "30min"], value="5min")
    va_percent = st.slider("Value Area %", 50, 90, 70, 5) / 100.0
    row_size = st.select_slider("Rezolutie profil (puncte / rand)",
                                options=[0.25, 0.5, 1.0, 2.0, 3.0, 5.0], value=2.0)
    st.caption("Engine-ul calculeaza la 0.25 (tick real NQ); rezolutia profilului "
               "grupeaza doar vizual barile. Verde = cumparare agresiva, rosu = vanzare.")

d = compute_profile(filename, va_percent)
candles = compute_candles(filename, interval)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Simbol", d["symbol"])
c2.metric("POC", f"{d['poc']:.2f}")
c3.metric("VAH / VAL", f"{d['vah']:.0f} / {d['val']:.0f}")
c4.metric("Volum total", f"{d['total_volume']:,.0f}")
c5.metric("Cumulative Delta", f"{d['cum_delta']:+,.0f}",
          delta="buy > sell" if d["cum_delta"] >= 0 else "sell > buy")

st.plotly_chart(build_figure(d, candles, row_size), width="stretch",
                config={"displayModeBar": True, "scrollZoom": True})

with st.expander("Zone HVN / LVN (volum mare / mic)"):
    a, b = st.columns(2)
    a.markdown("**HVN** — suporturi/rezistente puternice (magneti de pret)")
    a.write(sorted(d["hvn"], reverse=True))
    b.markdown("**LVN** — zone traversate rapid (goluri de volum)")
    b.write(sorted(d["lvn"]))

st.caption(f"{d['n_ticks']:,} tick-uri  ·  buy agresiv {d['buy_total']:,.0f}  ·  "
           f"sell agresiv {d['sell_total']:,.0f}")
