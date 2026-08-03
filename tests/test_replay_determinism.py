"""
Test de CORECTITUDINE: replay-ul e DETERMINIST, indiferent de viteza (marimea pasului).

A reda o portiune in pasi mici (viteza lenta) sau in pasi mari (viteza mare) trebuie sa
duca la EXACT aceeasi stare la acelasi cursor. Altfel, "ce vezi" ar depinde de viteza.
Verifica si ca stepping-ul pana la finalul unei lumanari == seek_candle direct la ea.

(Rulam pe portiuni marginite ca sa fie rapid; proprietatea de chunk-independenta e
independenta de lungime.)
"""

import os
import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import load_day, resolve_ticks
from app.desktop.replay import Replay

DATA_FILE = "glbx-mdp3-20260721.trades.parquet"
INTERVAL = "5min"

pytestmark = pytest.mark.skipif(
    not os.path.isfile(os.path.join(PARQUET_DIR, DATA_FILE)),
    reason="date reale lipsesc (data/parquet)",
)


def _sig(s):
    fp = sum(b + se for cells in s.footprint.values() for (b, se) in cells.values())
    return (round(s.poc, 4), round(s.total_volume, 4), round(s.cum_delta, 4),
            round(float(s.vwap[-1]), 4), round(fp, 4), len(s.t),
            round(float(s.close[-1]), 4))


def _fresh():
    d = load_day(DATA_FILE, mode="session", interval=INTERVAL, row_size=2.0)
    tk, _ = resolve_ticks(DATA_FILE, "session", "day")
    return d, Replay(d, tk.df, va_percent=0.70, row_size=2.0)


def _step_to_cursor(r, target_cursor, chunk):
    """Avanseaza EXACT pana la target_cursor, in pasi de `chunk` (+ un rest)."""
    last = None
    while r.cursor + chunk <= target_cursor:
        last = r.step(chunk)
    if r.cursor < target_cursor:
        last = r.step(target_cursor - r.cursor)
    return last


def test_replay_deterministic_across_speeds():
    """Aceeasi portiune, pasi mici (3) vs mari (5000) -> aceeasi stare la acelasi cursor."""
    _, r_slow = _fresh()
    _, r_fast = _fresh()
    target = 30000  # cursor comun (multe lumanari inchise + una in formare)
    slow = _sig(_step_to_cursor(r_slow, target, 3))
    fast = _sig(_step_to_cursor(r_fast, target, 5000))
    assert slow == fast, f"replay difera dupa viteza:\n slow={slow}\n fast={fast}"


def test_stepping_equals_seek():
    """Stepping EXACT pana la finalul lumanarii j == seek_candle(j)."""
    d, r1 = _fresh()
    target = min(120, r1.n_candles - 1)
    target_cursor = int(r1.candle_end[target])
    s_step = _step_to_cursor(r1, target_cursor, 50)   # pas cu pas pana la finalul lum. j
    _, r2 = _fresh()
    s_seek = r2.seek_candle(target)                    # seek direct la lumanarea j
    assert _sig(s_step) == _sig(s_seek)
