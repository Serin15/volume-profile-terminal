"""
Test de CORECTITUDINE pentru navigarea in replay (backtesting).

Blocheaza:
  (1) seek_candle(j) formeaza exact lumanarile 0..j (nici una in plus/minus);
  (2) seek INAPOI (care restaureaza dintr-un checkpoint) da EXACT acelasi snapshot
      ca stepping-ul pur forward -> checkpoints corecte, fara drift;
  (3) ultima lumanare din replay = incarcarea full-day (developing ajunge la total).

Se sare daca fisierul de date real lipseste.
"""

import os
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import load_day, resolve_ticks
from app.desktop.replay import Replay

DATA_FILE = "glbx-mdp3-20260721.trades.parquet"
ROW = 2.0
INTERVAL = "5min"

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DATA_FILE)),
    reason="date reale lipsesc (data/parquet)",
)


def _replay():
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=ROW)
    tk, _ = resolve_ticks(DATA_FILE, "session", "day")
    return d, Replay(d, tk.df, va_percent=0.70, row_size=ROW)


def _sig(s):
    """Semnatura numerica a unui snapshot (invarianta cheie)."""
    fp = sum(b + se for cells in s.footprint.values() for (b, se) in cells.values())
    return (round(s.poc, 4), round(s.total_volume, 4), round(s.cum_delta, 4),
            round(float(s.vwap[-1]), 4), round(fp, 4), len(s.t))


def test_seek_forms_exact_candles():
    """seek_candle(j) -> snapshot cu exact j+1 lumanari, ultima = epoca lumanarii j."""
    d, r = _replay()
    for j in (0, 15, 137, r.n_candles - 1):
        s = r.seek_candle(j)
        assert len(s.t) == j + 1
        assert int(round(s.t[-1])) == int(round(d.t[j]))


def test_backward_seek_matches_forward():
    """Seek inapoi (via checkpoint) == stepping pur forward, la virgula."""
    d, r_ref = _replay()
    targets = [20, 60, 130, 200, min(300, r_ref.n_candles - 1)]
    ref = {}
    for j in targets:
        r_ref.reset()
        ref[j] = _sig(r_ref.seek_candle(j))     # de la 0, forward, fara checkpoints

    _, r = _replay()
    r.seek_candle(r.n_candles - 1)              # forteaza construirea checkpoints
    for j in reversed(targets):                 # backward -> restaureaza din checkpoint
        assert _sig(r.seek_candle(j)) == ref[j], f"drift la candle {j}"


def test_last_candle_equals_full_day():
    """Ultima lumanare din replay = valorile incarcarii full-day (developing complet)."""
    d, r = _replay()
    s = r.seek_candle(r.n_candles - 1)
    assert round(s.poc, 4) == round(d.poc, 4)
    assert round(s.total_volume, 4) == round(d.total_volume, 4)
    assert round(s.cum_delta, 4) == round(d.cum_delta, 4)
