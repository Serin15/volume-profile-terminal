"""
P4.3 — teste pentru ABSORPTION / EXHAUSTION enrichment (stari contextuale cauzale).

Deterministe, sintetice. Construim bare cu footprint (cells buy/sell per nivel) pentru
absorption si serii OHLC/volum/cvd pentru exhaustion, apoi verificam starile + tranzitia
FORMING -> CONFIRMED/FADED dupa confirmation window (reactie masurata DOAR din bare <= T).
"""

import numpy as np

from core import (Snapshot, ContextEngine, snapshot_from_daydata,
                  analyze_absorption, AbsorptionContext, ABSORPTION_STATES,
                  analyze_exhaustion, ExhaustionContext, EXHAUSTION_STATES)
from app.desktop.data_service import DayData

EXH = {"window": 3}          # fereastra mica pt teste (implicit e 14 = prea multe bare)


def _bar_delta(b):
    if "delta" in b:
        return float(b["delta"])
    if "cells" in b:
        return float(sum(c[0] - c[1] for c in b["cells"].values()))
    return 0.0


def _arrays(bars, base=1_800_000_000, bs=60):
    n = len(bars)
    t = np.arange(n, dtype=float) * bs + base
    o = np.array([b["o"] for b in bars], float); h = np.array([b["h"] for b in bars], float)
    l = np.array([b["l"] for b in bars], float); c = np.array([b["c"] for b in bars], float)
    v = np.array([b["vol"] for b in bars], float)
    cvd = np.cumsum([_bar_delta(b) for b in bars]) if n else np.zeros(0)
    fp = {int(round(t[i])): {float(p): [float(x) for x in cell]
                             for p, cell in bars[i]["cells"].items()}
          for i in range(n) if bars[i].get("cells")}
    return t, o, h, l, c, v, cvd, fp


def _snap(bars, tick=0.25, row=1.0):
    t, o, h, l, c, v, cvd, fp = _arrays(bars)
    return Snapshot(now_epoch=int(t[-1]) if len(t) else 0, bar_seconds=60, t=t,
                    open=o, high=h, low=l, close=c, volume=v, cvd=cvd,
                    poc=0.0, vah=0.0, val=0.0, footprint=fp, row_size=row,
                    symbol="T", tick_size=tick)


def _make_day(bars, tick=0.25, row=1.0):
    t, o, h, l, c, v, cvd, fp = _arrays(bars)
    n = len(bars)
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=o, high=h, low=l, close=c, volume=v,
                   vwap=c.copy(), cvd=cvd, last_price=float(c[-1]) if n else 0.0,
                   bar_seconds=60, bin_price=np.array([100.0]), bin_buy=np.array([1.0]),
                   bin_sell=np.array([1.0]), row_size=row, poc=999.0, vah=1005.0, val=995.0,
                   footprint=fp, dev_poc=dev, dev_vah=dev + 5, dev_val=dev - 5)


def _bg(hi=107.0, lo=103.0, cl=105.0, vol=100.0):
    return dict(o=105.0, h=hi, l=lo, c=cl, vol=vol)


# ------------------------------------------------------------------ scenarii absorption
def _bull_absorption(reaction="up"):
    bars = [_bg() for _ in range(6)]
    bars.append(dict(o=105, h=110, l=100, c=109, vol=300,      # bar 6: sell absorbit la minim + inchidere sus
                     cells={100: [5, 120], 101: [5, 80], 108: [10, 5],
                            109: [10, 5], 110: [10, 5]}))
    if reaction == "up":                                       # pretul reactioneaza in sus, fara minim nou
        bars += [dict(o=109, h=112, l=106, c=111, vol=100),
                 dict(o=111, h=114, l=110, c=113, vol=100),
                 dict(o=113, h=116, l=112, c=115, vol=100)]
    else:                                                      # rupe minimul -> absorbtie esuata
        bars += [dict(o=109, h=105, l=98, c=99, vol=100),
                 dict(o=99, h=101, l=97, c=98, vol=100),
                 dict(o=98, h=100, l=96, c=97, vol=100)]
    return bars


def _bear_absorption():
    bars = [_bg() for _ in range(6)]
    bars.append(dict(o=105, h=110, l=100, c=101, vol=300,      # buy absorbit la maxim + inchidere jos
                     cells={100: [10, 5], 101: [10, 5], 108: [10, 5],
                            109: [80, 5], 110: [120, 5]}))
    bars += [dict(o=101, h=104, l=96, c=97, vol=100),          # reactie in jos, fara maxim nou
             dict(o=97, h=99, l=93, c=94, vol=100),
             dict(o=94, h=96, l=91, c=95, vol=100)]
    return bars


def test_bull_absorption_confirmed():
    assert analyze_absorption(_snap(_bull_absorption("up"))).state == "BULL_ABSORPTION_CONFIRMED"


def test_bear_absorption_confirmed():
    assert analyze_absorption(_snap(_bear_absorption())).state == "BEAR_ABSORPTION_CONFIRMED"


def test_absorption_faded_when_extreme_broken():
    assert analyze_absorption(_snap(_bull_absorption("break"))).state == "BULL_ABSORPTION_FADED"


def test_absorption_pending_before_confirmation_window():
    bars = _bull_absorption("up")
    ab = analyze_absorption(_snap(bars[:8]))                   # candidat la bar6, doar 1 bara dupa
    assert ab.status == "FORMING"
    assert ab.state == "BULL_ABSORPTION_FORMING"
    assert ab.subsequent_reaction_ticks is None                # inca nu masuram reactia


def test_absorption_reaction_measured_after_window():
    ab = analyze_absorption(_snap(_bull_absorption("up")))
    assert ab.status == "CONFIRMED"
    assert ab.subsequent_reaction_ticks is not None and ab.subsequent_reaction_ticks > 0
    assert ab.bars_since >= ab.confirmation_window


def test_aggression_without_progress_is_NOT_absorption():
    """Sell agresiv masiv la minim DAR inchidere langa minim (fara respingere) -> NU e absorptie."""
    bars = [_bg() for _ in range(6)]
    bars.append(dict(o=105, h=110, l=100, c=101, vol=300,      # close langa minim: (101-100)/10=0.1 < reject
                     cells={100: [5, 120], 101: [5, 80], 108: [10, 5],
                            109: [10, 5], 110: [10, 5]}))
    bars += [_bg() for _ in range(3)]
    ab = analyze_absorption(_snap(bars))
    assert ab.detected is False
    assert ab.state == "NONE"


# ------------------------------------------------------------------ scenarii exhaustion
def _top_exhaustion(reaction="down"):
    bars = [_bg(hi=106, lo=102, cl=104) for _ in range(4)]
    bars.append(dict(o=105, h=120, l=104, c=119, vol=300, delta=100))   # bar4: maxim nou + climax + delta+
    if reaction == "down":                                     # reversal jos, fara maxim nou
        bars += [dict(o=119, h=118, l=112, c=113, vol=100, delta=-30),
                 dict(o=113, h=115, l=109, c=110, vol=100, delta=-30),
                 dict(o=110, h=112, l=106, c=108, vol=100, delta=-30)]
    else:                                                      # maxim nou -> exhaustion esuat
        bars += [dict(o=119, h=125, l=118, c=124, vol=100, delta=20),
                 dict(o=124, h=130, l=123, c=129, vol=100, delta=20),
                 dict(o=129, h=134, l=128, c=133, vol=100, delta=20)]
    return bars


def _bot_exhaustion():
    bars = [_bg(hi=106, lo=102, cl=104) for _ in range(4)]
    bars.append(dict(o=105, h=106, l=90, c=91, vol=300, delta=-100))    # minim nou + climax + delta-
    bars += [dict(o=91, h=98, l=90, c=97, vol=100, delta=30),
             dict(o=97, h=103, l=96, c=102, vol=100, delta=30),
             dict(o=102, h=108, l=101, c=107, vol=100, delta=30)]
    return bars


def test_top_exhaustion_confirmed():
    assert analyze_exhaustion(_snap(_top_exhaustion("down")), EXH).state == "TOP_EXHAUSTION_CONFIRMED"


def test_bot_exhaustion_confirmed():
    assert analyze_exhaustion(_snap(_bot_exhaustion()), EXH).state == "BOT_EXHAUSTION_CONFIRMED"


def test_exhaustion_faded_when_new_extreme():
    assert analyze_exhaustion(_snap(_top_exhaustion("up")), EXH).state == "TOP_EXHAUSTION_FADED"


def test_exhaustion_pending_before_window():
    exc = analyze_exhaustion(_snap(_top_exhaustion("down")[:6]), EXH)
    assert exc.status == "FORMING"
    assert exc.subsequent_reaction_ticks is None


def test_exhaustion_and_absorption_are_separate_components():
    """Un scenariu de exhaustion NU e raportat ca absorptie (concepte separate)."""
    snap = _snap(_top_exhaustion("down"))
    assert analyze_exhaustion(snap, EXH).detected is True
    assert analyze_absorption(snap).detected is False


def test_states_in_known_sets():
    assert analyze_absorption(_snap(_bull_absorption("up"))).state in ABSORPTION_STATES
    assert analyze_exhaustion(_snap(_top_exhaustion("down")), EXH).state in EXHAUSTION_STATES


# ------------------------------------------------------------------ no-look-ahead + determinism
def test_absorption_no_look_ahead_and_confirmation_progression():
    bars = _bull_absorption("up")            # absorptie la bar6, confirmata la bar9
    full = _make_day(bars)
    ended = _make_day(bars[:8])              # ziua s-ar fi terminat la bar7
    a = analyze_absorption(snapshot_from_daydata(full, upto_index=7))
    b = analyze_absorption(snapshot_from_daydata(ended, upto_index=7))
    assert a == b                             # barele viitoare (8,9) nu schimba starea la T=7
    assert a.status == "FORMING"
    # abia dupa ce trece fereastra devine CONFIRMED
    assert analyze_absorption(snapshot_from_daydata(full, upto_index=9)).status == "CONFIRMED"


def test_exhaustion_no_look_ahead():
    bars = _top_exhaustion("down")
    full = _make_day(bars)
    ended = _make_day(bars[:6])
    a = analyze_exhaustion(snapshot_from_daydata(full, upto_index=5), EXH)
    b = analyze_exhaustion(snapshot_from_daydata(ended, upto_index=5), EXH)
    assert a == b
    assert a.status == "FORMING"
    assert analyze_exhaustion(snapshot_from_daydata(full, upto_index=7), EXH).status == "CONFIRMED"


def test_determinism():
    snap = snapshot_from_daydata(_make_day(_bull_absorption("up")), upto_index=9)
    assert analyze_absorption(snap) == analyze_absorption(snap)
    esnap = _snap(_top_exhaustion("down"))
    assert analyze_exhaustion(esnap, EXH) == analyze_exhaustion(esnap, EXH)


def test_engine_keeps_all_components():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day(_bull_absorption("up")),
                                                        upto_index=9))
    for name in ("delta", "price_progress", "absorption", "exhaustion"):
        assert name in res.components
    assert isinstance(res.components["absorption"], AbsorptionContext)
    assert isinstance(res.components["exhaustion"], ExhaustionContext)
