"""
Teste de CORECTITUDINE pentru VWAP si Big Trades pe DATE REALE.

VWAP: developing, finit, in interval [low, high], = formula cumulativa documentata.
Big Trades: exact tranzactiile >= prag, cu pret/marime/side corecte din tick-uri brute.

Se sar daca fisierul real lipseste.
"""

import os
import numpy as np
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import load_day, resolve_ticks, _big_trades, BIG_TRADE_MIN, INTERVAL_SECONDS

DATA_FILE = "glbx-mdp3-20260722.trades.parquet"
INTERVAL = "5min"

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DATA_FILE)),
    reason="date reale lipsesc (data/parquet)",
)


def test_vwap_finite_and_bounded():
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=2.0)
    assert np.all(np.isfinite(d.vwap)), "VWAP are NaN/inf"
    assert d.vwap.min() >= d.low.min() - 1e-6
    assert d.vwap.max() <= d.high.max() + 1e-6


def test_vwap_matches_cumulative_formula():
    """VWAP = cumsum((H+L+C)/3 * vol) / cumsum(vol), aliniat cu lumanarile."""
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=2.0)
    typ = (d.high + d.low + d.close) / 3.0
    cv = np.cumsum(d.volume)
    expected = np.cumsum(typ * d.volume) / np.where(cv == 0, np.nan, cv)
    assert np.allclose(d.vwap, expected, equal_nan=True, atol=1e-6)


def test_big_trades_threshold_and_values():
    """Fiecare big trade >= prag; numarul = tick-urile brute >= prag; side valid."""
    tk, _ = resolve_ticks(DATA_FILE, "session", "day")
    df = tk.df
    bts = _big_trades(df, INTERVAL_SECONDS[INTERVAL])
    raw = df[df["size"] >= BIG_TRADE_MIN]
    assert len(bts) == len(raw), f"{len(bts)} != {len(raw)}"
    for (_, price, size, side) in bts:
        assert size >= BIG_TRADE_MIN
        assert side in ("B", "A", "N")
    # suma marimilor mari = suma din tick-urile brute filtrate
    assert abs(sum(b[2] for b in bts) - float(raw["size"].sum())) < 1e-6
