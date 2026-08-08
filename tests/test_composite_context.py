"""
P3 — teste pentru COMPOSITE CONTEXT (analyze_composite_context).

Deterministe, sintetice. Controlam prev-session VA (reference_levels) + composite 15D/90D
(composite_levels) si verificam fiecare REGULA de agreement/context, confluenta, gate cauzal,
no-look-ahead, determinism. Plus validare pe date reale 03/08 si 04/08.
"""

import os
import numpy as np
import pytest

from core import (Snapshot, ContextEngine, snapshot_from_daydata, ReferenceLevel,
                  analyze_composite_context, CompositeContextContext, COMPOSITE_CONTEXT_STATES)
from app.desktop.data_service import DayData


def _rl(session, poc, vah, val, avail=0):
    return [ReferenceLevel(session, "poc", poc, avail), ReferenceLevel(session, "vah", vah, avail),
            ReferenceLevel(session, "val", val, avail)]


def _snap(price, prev=None, comps=None, extra_comps=None, n=8, tick=0.25, base=1_800_000_000):
    refs = _rl("prev", *prev) if prev else []
    clv = []
    for (span, poc, vah, val) in (comps or []):
        clv += _rl(span, poc, vah, val)
    clv += list(extra_comps or [])
    t = np.arange(n, dtype=float) * 60 + base
    c = np.full(n, float(price))
    return Snapshot(now_epoch=int(t[-1]), bar_seconds=60, t=t, open=c.copy(), high=c + 1,
                    low=c - 1, close=c, volume=np.zeros(n) + 10.0, cvd=np.cumsum(np.full(n, 10.0)),
                    poc=0.0, vah=0.0, val=0.0, footprint={}, row_size=1.0,
                    reference_levels=refs, composite_levels=clv, symbol="T", tick_size=tick)


# ---------------------------------------------------------------- reguli agreement -> context
def test_confluent_above_is_supportive():
    d = analyze_composite_context(_snap(105.0, prev=(95, 100, 90),
                                        comps=[("15D", 96, 101, 91), ("90D", 97, 102, 92)]))
    assert d.agreement == "CONFLUENT_ABOVE" and d.context == "SUPPORTIVE"


def test_confluent_below_is_supportive():
    d = analyze_composite_context(_snap(80.0, prev=(95, 100, 90),
                                        comps=[("15D", 96, 101, 91)]))
    assert d.agreement == "CONFLUENT_BELOW" and d.context == "SUPPORTIVE"


def test_confluent_inside_is_neutral():
    d = analyze_composite_context(_snap(105.0, prev=(105, 108, 102),
                                        comps=[("15D", 104, 110, 100)]))
    assert d.agreement == "CONFLUENT_INSIDE" and d.context == "NEUTRAL"


def test_mixed_is_contradicting():
    d = analyze_composite_context(_snap(105.0, prev=(108, 110, 106),      # price BELOW prev value
                                        comps=[("15D", 102, 104, 100)]))  # price ABOVE 15D value
    assert d.agreement == "MIXED" and d.context == "CONTRADICTING"


def test_partial_is_neutral():
    d = analyze_composite_context(_snap(105.0, prev=(108, 110, 106),      # BELOW prev
                                        comps=[("15D", 105, 108, 102)]))  # INSIDE 15D
    assert d.agreement == "PARTIAL" and d.context == "NEUTRAL"


def test_insufficient_when_one_timeframe():
    d = analyze_composite_context(_snap(105.0, prev=None, comps=[("15D", 96, 101, 91)]))
    assert d.agreement == "INSUFFICIENT" and d.context == "NEUTRAL"


def test_reasons_are_transparent():
    d = analyze_composite_context(_snap(105.0, prev=(95, 100, 90), comps=[("15D", 96, 101, 91)]))
    assert any("prev: ABOVE_VALUE" in r for r in d.reasons)
    assert any("15D: ABOVE_VALUE" in r for r in d.reasons)
    assert any("agreement=" in r for r in d.reasons)


# ---------------------------------------------------------------- profile + relatie pret
def test_composite_profiles_and_location():
    d = analyze_composite_context(_snap(105.0, comps=[("15D", 96, 101, 91), ("90D", 97, 102, 92)]))
    spans = {cp.span: cp for cp in d.composites}
    assert set(spans) == {"15D", "90D"}
    assert spans["15D"].location == "ABOVE_VALUE"
    assert spans["15D"].poc_distance_ticks == (105.0 - 96.0) / 0.25


def test_hvn_lvn_collected():
    clv = [ReferenceLevel("15D", "hvn", 103.0, 0), ReferenceLevel("15D", "lvn", 101.0, 0)] \
        + [ReferenceLevel("15D", "poc", 100.0, 0), ReferenceLevel("15D", "vah", 104.0, 0),
           ReferenceLevel("15D", "val", 96.0, 0)]
    d = analyze_composite_context(_snap(110.0, extra_comps=clv))
    cp = d.composites[0]
    assert cp.hvn == [103.0] and cp.lvn == [101.0]


# ---------------------------------------------------------------- confluenta multi-timeframe
def test_confluence_zone_detected():
    # prev POC 105.2 + 15D HVN 104.8, ambele langa pretul 105 -> confluenta
    extra = [ReferenceLevel("15D", "hvn", 104.8, 0)]
    d = analyze_composite_context(_snap(105.0, prev=(105.2, 130.0, 80.0),
                                        comps=[("15D", 96, 101, 91)], extra_comps=extra))
    assert d.has_confluence is True
    assert len(d.confluence_levels) >= 2


# ---------------------------------------------------------------- gate cauzal
def test_future_dated_composite_excluded():
    future = [ReferenceLevel("90D", "poc", 500.0, 10 ** 12)]      # 90D "din viitor"
    d = analyze_composite_context(_snap(105.0, comps=[("15D", 96, 101, 91)], extra_comps=future))
    assert {cp.span for cp in d.composites} == {"15D"}            # 90D exclus


def test_no_composite_is_unavailable():
    d = analyze_composite_context(_snap(105.0, prev=(95, 100, 90), comps=[]))
    assert d.available is False


# ---------------------------------------------------------------- no-look-ahead + determinism
def _make_day(price, prev, comps, n=10):
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    c = np.full(n, float(price))
    dev = np.full(n, float(price))
    refs = _rl("prev", *prev) if prev else []
    clv = []
    for (span, poc, vah, val) in comps:
        clv += _rl(span, poc, vah, val)
    day = DayData(symbol="T", n_ticks=n, t=t, open=c.copy(), high=c + 1, low=c - 1, close=c,
                  volume=np.zeros(n) + 10.0, vwap=c.copy(), cvd=np.cumsum(np.full(n, 10.0)),
                  last_price=float(c[-1]), bar_seconds=60, bin_price=np.array([100.0]),
                  bin_buy=np.array([1.0]), bin_sell=np.array([1.0]), row_size=1.0,
                  poc=float(price), vah=float(price) + 2, val=float(price) - 2, footprint={},
                  dev_poc=dev, dev_vah=dev + 2, dev_val=dev - 2)
    day.reference_levels = refs
    day.composite_levels = clv
    return day


def test_no_look_ahead():
    day = _make_day(105.0, (95, 100, 90), [("15D", 96, 101, 91)])
    ended = _make_day(105.0, (95, 100, 90), [("15D", 96, 101, 91)], n=7)
    a = analyze_composite_context(snapshot_from_daydata(day, upto_index=6))
    b = analyze_composite_context(snapshot_from_daydata(ended, upto_index=6))
    assert a == b and a.context == "SUPPORTIVE"


def test_determinism():
    snap = snapshot_from_daydata(_make_day(105.0, (95, 100, 90), [("15D", 96, 101, 91)]), 9)
    assert analyze_composite_context(snap) == analyze_composite_context(snap)


def test_engine_keeps_all_eleven_components():
    res = ContextEngine().analyze(snapshot_from_daydata(
        _make_day(105.0, (95, 100, 90), [("15D", 96, 101, 91)]), 9))
    for name in ("delta", "price_progress", "absorption", "exhaustion", "cvd_divergence",
                 "poc_migration", "lvn_interaction", "acceptance_rejection", "tape_speed",
                 "session_context", "composite_context"):
        assert name in res.components
    assert isinstance(res.components["composite_context"], CompositeContextContext)


def test_state_in_known_set():
    for args in ((105.0, (95, 100, 90), [("15D", 96, 101, 91)]),
                 (105.0, (108, 110, 106), [("15D", 102, 104, 100)])):
        assert analyze_composite_context(_snap(args[0], prev=args[1], comps=args[2])).context \
            in COMPOSITE_CONTEXT_STATES


# ---------------------------------------------------------------- date reale 03/08 + 04/08
from data.loader import PARQUET_DIR


@pytest.mark.parametrize("day_file", ["glbx-mdp3-20260803.trades.parquet",
                                      "glbx-mdp3-20260804.trades.parquet"])
def test_composite_context_on_real_data(day_file):
    if not os.path.isfile(os.path.join(PARQUET_DIR, day_file)):
        pytest.skip("date reale lipsesc")
    from app.desktop.data_service import (load_day, build_reference_levels,
                                          build_composite_levels, SESSION_DEFS)
    name = day_file.replace(".parquet", "")
    day = load_day(name, mode="session", interval="5min", row_size=2.0)
    refs = build_reference_levels(name, mode="session", row_size=2.0, sessions=SESSION_DEFS["real"])
    comps = build_composite_levels(name, spans=(15, 90), row_size=2.0)
    assert any(r.session == "15D" for r in comps)          # composite calculat
    d = analyze_composite_context(snapshot_from_daydata(
        day, upto_index=len(day.t) - 1, reference_levels=refs, composite_levels=comps))
    assert d.available is True
    assert d.context in COMPOSITE_CONTEXT_STATES
    assert {cp.span for cp in d.composites} & {"15D", "90D"}
