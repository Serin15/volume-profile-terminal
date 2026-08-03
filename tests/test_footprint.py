"""
Test de CORECTITUDINE pentru footprint pe DATE REALE.

Blocheaza: (1) suma tuturor celulelor = totalul real buy/sell (niciun tick pierdut
sau dublat); (2) o celula anume se potriveste cu recalcularea directa din tick-uri.

Se sare daca fisierul de date real lipseste.
"""

import os
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import load_day, _get_ticks

DATA_FILE = "glbx-mdp3-20260722.trades.parquet"
ROW = 2.0
INTERVAL = "5min"
INTERVAL_SEC = 300

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DATA_FILE)),
    reason="date reale lipsesc (data/parquet)",
)


def _load():
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    tk, _ = _get_ticks(DATA_FILE, "session")
    return d, tk.df


def test_footprint_totals_match_raw():
    """Suma buy/sell din toate celulele = totalul independent din tick-uri."""
    d, df = _load()
    fp_buy = sum(b for cells in d.footprint.values() for (b, s) in cells.values())
    fp_sell = sum(s for cells in d.footprint.values() for (b, s) in cells.values())
    ind_buy = float(df[df.side == "B"]["size"].sum())
    ind_sell = float(df[df.side == "A"]["size"].sum())
    assert abs(fp_buy - ind_buy) < 1e-6, f"buy: {fp_buy} != {ind_buy}"
    assert abs(fp_sell - ind_sell) < 1e-6, f"sell: {fp_sell} != {ind_sell}"


def test_cvd_last_equals_cumulative_delta():
    """Ultimul punct din CVD (developing) = Cumulative Delta al sesiunii; aliniat cu lumanarile."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    assert len(d.cvd) == len(d.t), "CVD trebuie aliniat cu lumanarile"
    assert abs(float(d.cvd[-1]) - d.cum_delta) < 1e-6, f"CVD final {d.cvd[-1]} != cum_delta {d.cum_delta}"


def test_footprint_delta_sums_to_cumulative():
    """Suma delta-urilor per lumanare (impulsul) = Cumulative Delta al sesiunii."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    total = sum(b - s for cells in d.footprint.values() for (b, s) in cells.values())
    assert abs(total - d.cum_delta) < 1e-6, f"delta footprint {total} != cum_delta {d.cum_delta}"


def test_footprint_cell_matches_raw():
    """Cea mai mare celula, recalculata direct din tick-uri, trebuie sa fie identica."""
    d, df = _load()
    best = max(((t, p, b, s) for t, cells in d.footprint.items()
                for p, (b, s) in cells.items()),
               key=lambda x: x[2] + x[3])
    t, p, b, s = best
    tsec = df["ts"].astype("int64") // 10**9
    candle = (tsec // INTERVAL_SEC) * INTERVAL_SEC
    pbin = (df["price"] / ROW).round() * ROW
    sub = df[(candle == t) & ((pbin - p).abs() < 1e-6)]
    raw_buy = float(sub[sub.side == "B"]["size"].sum())
    raw_sell = float(sub[sub.side == "A"]["size"].sum())
    assert abs(b - raw_buy) < 1e-6, f"buy celula: {b} != {raw_buy}"
    assert abs(s - raw_sell) < 1e-6, f"sell celula: {s} != {raw_sell}"
