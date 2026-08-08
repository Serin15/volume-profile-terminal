"""
P6 (core) — teste pentru rezumatul TRANSPARENT `overall` + `reasons` (_execution_summary).

Testam regulile direct cu componente "fake" (SimpleNamespace) ca sa controlam exact
starile, plus integrarea end-to-end prin ContextEngine (overall in set, no-look-ahead,
determinism, INSUFFICIENT cand lipsesc dovezi).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # pt testul UI (panoul)

from types import SimpleNamespace as NS

import numpy as np
import pytest

from core import (ContextEngine, snapshot_from_daydata, _execution_summary, OVERALL_STATES)
from app.desktop.data_service import DayData


def _components(delta="NEUTRAL", pp="NEUTRAL", ab=None, ex=None, cvd=("NO_DIVERGENCE", "NONE"),
                poc="POC_SIDEWAYS", lvn=("INSUFFICIENT_EVIDENCE", False),
                tape=("NORMAL", "STEADY"), sess=None, comp=None):
    return {
        "delta": NS(sequence_state=delta),
        "price_progress": NS(state=pp),
        "absorption": NS(status=(ab[1] if ab else "NONE"), kind=(ab[0] if ab else None),
                         detected=bool(ab)),
        "exhaustion": NS(status=(ex[1] if ex else "NONE"), kind=(ex[0] if ex else None),
                         detected=bool(ex)),
        "cvd_divergence": NS(state=cvd[0], status=cvd[1]),
        "poc_migration": NS(state=poc, direction=poc.replace("POC_", "")),
        "lvn_interaction": NS(state=lvn[0], detected=lvn[1]),
        "tape_speed": NS(speed_level=tape[0], acceleration=tape[1]),
        "session_context": NS(available=bool(sess), profiles=([NS(location=sess)] if sess else [])),
        "composite_context": NS(available=bool(comp), context=(comp[0] if comp else "NEUTRAL"),
                                agreement=(comp[1] if comp else "INSUFFICIENT")),
    }


# ---------------------------------------------------------------- reguli overall
def test_supportive_when_two_agreeing_signals():
    o, _ = _execution_summary(_components(delta="BUYING_AGGRESSION",
                                          cvd=("BULLISH_DIVERGENCE", "CONFIRMED")))
    assert o == "SUPPORTIVE"


def test_supportive_from_absorption_and_exhaustion():
    o, _ = _execution_summary(_components(ab=("bull", "CONFIRMED"), ex=("bot", "CONFIRMED")))
    assert o == "SUPPORTIVE"


def test_contradicting_when_signals_conflict():
    o, _ = _execution_summary(_components(delta="SELLING_AGGRESSION",
                                          cvd=("BULLISH_DIVERGENCE", "CONFIRMED")))
    assert o == "CONTRADICTING"


def test_neutral_single_signal():
    o, _ = _execution_summary(_components(cvd=("BULLISH_DIVERGENCE", "CONFIRMED")))
    assert o == "NEUTRAL"


def test_neutral_no_signals():
    assert _execution_summary(_components())[0] == "NEUTRAL"


def test_insufficient_when_core_components_missing():
    o, _ = _execution_summary(_components(pp="INSUFFICIENT_EVIDENCE",
                                          cvd=("INSUFFICIENT_EVIDENCE", "NONE")))
    assert o == "INSUFFICIENT_EVIDENCE"


def test_forming_cvd_does_not_count_as_signal():
    """Divergenta doar FORMING nu conteaza ca dovada confirmata."""
    o, _ = _execution_summary(_components(cvd=("BULLISH_DIVERGENCE", "FORMING")))
    assert o == "NEUTRAL"


def test_overall_always_in_known_set():
    for kw in (dict(delta="BUYING_AGGRESSION", cvd=("BULLISH_DIVERGENCE", "CONFIRMED")),
               dict(delta="SELLING_AGGRESSION"), dict(), dict(pp="INSUFFICIENT_EVIDENCE",
               cvd=("INSUFFICIENT_EVIDENCE", "NONE"))):
        assert _execution_summary(_components(**kw))[0] in OVERALL_STATES


# ---------------------------------------------------------------- reasons transparente
def test_reasons_are_explainable():
    _, reasons = _execution_summary(_components(
        delta="SELLING_DECELERATION", pp="AGGRESSION_WITHOUT_PROGRESS",
        cvd=("BULLISH_DIVERGENCE", "CONFIRMED"), lvn=("ACCEPTANCE", True), sess="ABOVE_VALUE"))
    joined = " | ".join(reasons)
    assert "selling pressure is decelerating" in joined
    assert "little price progress" in joined
    assert "CVD diverges bullishly" in joined
    assert "acceptance at an LVN" in joined
    assert reasons[-1].startswith("evidence:")           # ultima linie = regula


def test_summary_deterministic():
    c = _components(delta="BUYING_AGGRESSION", cvd=("BULLISH_DIVERGENCE", "CONFIRMED"))
    assert _execution_summary(c) == _execution_summary(c)


# ---------------------------------------------------------------- integrare prin ContextEngine
def _make_day(n=12):
    t = np.arange(n, dtype=float) * 60 + 1_800_000_000
    c = 100.0 + np.arange(n, dtype=float)
    dev = np.full(n, 100.0)
    return DayData(symbol="T", n_ticks=n, t=t, open=c.copy(), high=c + 1, low=c - 1, close=c,
                   volume=np.zeros(n) + 100.0, vwap=c.copy(), cvd=np.cumsum(np.full(n, 5.0)),
                   last_price=float(c[-1]), bar_seconds=60, bin_price=np.array([100.0]),
                   bin_buy=np.array([1.0]), bin_sell=np.array([1.0]), row_size=2.0,
                   poc=100.0, vah=102.0, val=98.0, footprint={},
                   dev_poc=dev, dev_vah=dev + 2, dev_val=dev - 2,
                   tps=np.zeros(n) + 3.0)


def test_engine_sets_overall_and_reasons():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day(), upto_index=11))
    assert res.overall in OVERALL_STATES
    assert isinstance(res.reasons, list) and len(res.reasons) >= 1
    assert len(res.components) == 11


def test_engine_overall_no_look_ahead():
    full = _make_day(12)
    ended = _make_day(8)
    a = ContextEngine().analyze(snapshot_from_daydata(full, upto_index=7))
    b = ContextEngine().analyze(snapshot_from_daydata(ended, upto_index=7))
    assert a.overall == b.overall and a.reasons == b.reasons


def test_engine_insufficient_on_tiny_snapshot():
    res = ContextEngine().analyze(snapshot_from_daydata(_make_day(4), upto_index=3))
    assert res.overall == "INSUFFICIENT_EVIDENCE"


def test_engine_overall_deterministic():
    snap = snapshot_from_daydata(_make_day(), upto_index=11)
    assert ContextEngine().analyze(snap).overall == ContextEngine().analyze(snap).overall


# ---------------------------------------------------------------- UI: panoul Execution Context
import glob
from data.loader import PARQUET_DIR


@pytest.mark.skipif(not glob.glob(os.path.join(PARQUET_DIR, "*.parquet")),
                    reason="date reale lipsesc")
def test_execution_context_panel_renders():
    from pyqtgraph.Qt import QtWidgets
    from app.desktop.main import MainWindow
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = MainWindow()

    # Clean Chart (P7): markerele pornesc STINSE
    assert not win.chk_big.isChecked() and not win.chk_abs.isChecked() and not win.chk_exh.isChecked()

    win.chk_ctx.setChecked(True)                    # activeaza panoul -> calculeaza + randeaza
    html = win.ctx_panel.toPlainText()
    assert "EXECUTION CONTEXT" in html and "Overall" in html
    assert "FLOW" in html                           # panou pe sectiuni
    assert "price-action setup" in html             # disclaimerul (nu BUY/SELL)
    assert "TECHNICAL DETAILS" not in html          # ascuns implicit

    # Context-at-cursor: randare la o bara anume (cauzal, upto_index)
    win._update_execution_context(3)
    assert "Overall" in win.ctx_panel.toPlainText()

    # Technical Details expandable
    win.chk_ctx_tech.setChecked(True)
    assert "TECHNICAL DETAILS" in win.ctx_panel.toPlainText()

    win.chk_ctx.setChecked(False)                   # se ascunde curat
    assert win.ctx_container.isVisible() is False
