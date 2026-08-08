"""
P2 — teste pentru PREVIOUS SESSION CONTEXT (analyze_session_context).

Deterministe, sintetice. Controlam reference_levels si verificam: pozitia pretului fata de
VA sesiunii precedente, selectia nivelului cel mai apropiat, gate-ul CAUZAL (available_from),
interactiunea (motor P1b) + no-look-ahead + determinism. Plus integrare pe date reale.
"""

import os
import numpy as np
import pytest

from core import (Snapshot, ContextEngine, snapshot_from_daydata, ReferenceLevel,
                  analyze_session_context, SessionContextContext, INTERACTION_STATES)
from app.desktop.data_service import DayData

PREV_VA = [ReferenceLevel("prev", "poc", 102.0, 0), ReferenceLevel("prev", "vah", 104.0, 0),
           ReferenceLevel("prev", "val", 100.0, 0)]


def _snap(bars, refs, tick=0.25, base=1_800_000_000):
    n = len(bars)
    h = np.array([b[0] for b in bars], float); l = np.array([b[1] for b in bars], float)
    c = np.array([b[2] for b in bars], float)
    t = np.arange(n, dtype=float) * 60 + base
    return Snapshot(now_epoch=int(t[-1]) if n else 0, bar_seconds=60, t=t, open=c.copy(),
                    high=h, low=l, close=c, volume=np.zeros(n) + 10.0, cvd=np.cumsum(np.full(n, 10.0)),
                    poc=0.0, vah=0.0, val=0.0, footprint={}, row_size=1.0,
                    reference_levels=list(refs), symbol="T", tick_size=tick)


def _flat(price, n=8):
    return [(price + 1, price - 1, price)] * n


# ---------------------------------------------------------------- pozitie vs VA
def test_price_above_prev_value():
    d = analyze_session_context(_snap(_flat(105.0), PREV_VA))
    p = d.profiles[0]
    assert p.session == "prev" and p.location == "ABOVE_VALUE"
    assert p.poc_distance_ticks == (105.0 - 102.0) / 0.25


def test_price_inside_prev_value():
    assert analyze_session_context(_snap(_flat(102.0), PREV_VA)).profiles[0].location == "INSIDE_VALUE"


def test_price_below_prev_value():
    assert analyze_session_context(_snap(_flat(99.0), PREV_VA)).profiles[0].location == "BELOW_VALUE"


def test_nearest_level_selection():
    d = analyze_session_context(_snap(_flat(105.0), PREV_VA))
    assert d.nearest_level.kind == "vah"                 # 104 cel mai aproape de 105
    assert d.nearest_level.distance_ticks == (105.0 - 104.0) / 0.25


def test_hvn_lvn_collected_per_session():
    refs = PREV_VA + [ReferenceLevel("prev", "hvn", 103.0, 0), ReferenceLevel("prev", "lvn", 101.0, 0)]
    p = analyze_session_context(_snap(_flat(105.0), refs)).profiles[0]
    assert p.hvn == [103.0] and p.lvn == [101.0]


# ---------------------------------------------------------------- gate CAUZAL
def test_future_dated_level_is_excluded():
    """Un nivel cu available_from in VIITOR (sesiune neinchisa inca) NU e folosit la T."""
    future = ReferenceLevel("london", "poc", 200.0, 10 ** 12)   # available_from >> now
    d = analyze_session_context(_snap(_flat(105.0), PREV_VA + [future]))
    assert [p.session for p in d.profiles] == ["prev"]           # london exclus
    # rezultat identic fata de cazul fara nivelul viitor
    assert d == analyze_session_context(_snap(_flat(105.0), PREV_VA))


def test_level_becomes_available_after_its_close():
    now = 1_800_000_000 + 7 * 60                                 # t[-1] pt n=8
    past_london = ReferenceLevel("london", "poc", 108.0, now - 60)   # inchisa inainte de T
    d = analyze_session_context(_snap(_flat(105.0), PREV_VA + [past_london]))
    assert set(p.session for p in d.profiles) == {"prev", "london"}


# ---------------------------------------------------------------- interactiune (motor P1b)
def test_nearest_interaction_uses_p1b_engine():
    # pretul coboara la VAH-ul precedent (104) si il respinge in sus
    bars = [(111.0, 109.0, 110.0)] * 5 + [(110.0, 103.5, 108.0)] + [
        (109.0, 107.0, 108.0), (111.0, 109.0, 110.0), (113.0, 111.0, 112.0), (115.0, 113.0, 114.0)]
    d = analyze_session_context(_snap([tuple(map(float, b)) for b in bars], PREV_VA))
    assert d.nearest_interaction_state in INTERACTION_STATES
    assert d.nearest_interaction_status in ("NONE", "FORMING", "CONFIRMED")


def test_no_reference_levels_is_unavailable():
    d = analyze_session_context(_snap(_flat(105.0), []))
    assert d.available is False and d.profiles == []


# ---------------------------------------------------------------- no-look-ahead + determinism
def _make_day(bars, refs):
    n = len(bars)
    h = np.array([b[0] for b in bars], float); l = np.array([b[1] for b in bars], float)
    c = np.array([b[2] for b in bars], float)
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    dev = np.full(n, 102.0)
    day = DayData(symbol="T", n_ticks=n, t=t, open=c.copy(), high=h, low=l, close=c,
                  volume=np.zeros(n) + 10.0, vwap=c.copy(), cvd=np.cumsum(np.full(n, 10.0)),
                  last_price=float(c[-1]), bar_seconds=60, bin_price=np.array([100.0]),
                  bin_buy=np.array([1.0]), bin_sell=np.array([1.0]), row_size=1.0,
                  poc=102.0, vah=104.0, val=100.0, footprint={},
                  dev_poc=dev, dev_vah=dev + 2, dev_val=dev - 2)
    day.reference_levels = list(refs)
    return day


def test_no_look_ahead():
    bars = _flat(105.0, 10)
    full = _make_day(bars, PREV_VA)
    ended = _make_day(bars[:7], PREV_VA)
    a = analyze_session_context(snapshot_from_daydata(full, upto_index=6))
    b = analyze_session_context(snapshot_from_daydata(ended, upto_index=6))
    assert a == b


def test_determinism():
    snap = snapshot_from_daydata(_make_day(_flat(105.0, 10), PREV_VA), upto_index=9)
    assert analyze_session_context(snap) == analyze_session_context(snap)


def test_engine_keeps_all_ten_components():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day(_flat(105.0, 10), PREV_VA), 9))
    for name in ("delta", "price_progress", "absorption", "exhaustion", "cvd_divergence",
                 "poc_migration", "lvn_interaction", "acceptance_rejection", "tape_speed",
                 "session_context"):
        assert name in res.components
    assert isinstance(res.components["session_context"], SessionContextContext)


# ---------------------------------------------------------------- date reale (skippable)
from data.loader import PARQUET_DIR
_REAL = "glbx-mdp3-20260804.trades.parquet"


@pytest.mark.skipif(not os.path.isfile(os.path.join(PARQUET_DIR, _REAL)),
                    reason="date reale lipsesc")
def test_build_reference_levels_and_context_on_real_data():
    from app.desktop.data_service import load_day, build_reference_levels, SESSION_DEFS
    day = load_day(_REAL, mode="session", interval="5min", row_size=2.0)
    refs = build_reference_levels(_REAL, mode="session", row_size=2.0,
                                  sessions=SESSION_DEFS["real"])
    assert any(r.session == "prev" for r in refs)         # sesiunea precedenta exista
    d = analyze_session_context(snapshot_from_daydata(day, upto_index=len(day.t) - 1,
                                                      reference_levels=refs))
    assert d.available is True
    assert any(p.session == "prev" for p in d.profiles)
    assert d.profiles[0].location in ("ABOVE_VALUE", "INSIDE_VALUE", "BELOW_VALUE", "UNKNOWN")
