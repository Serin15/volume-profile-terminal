"""Teste pentru HOVER-ul pe markere (Big Trades / Absorption / Exhaustion / Acc-Rej).

Bug raportat de Ali: "nu apare nimic la hover pe niciun marker". In dev hover-ul merge;
aceste teste BLOCHEAZA regresia pe calea REALA de cod, pe date REALE (offscreen):

  1. _on_marker_hover: pentru FIECARE tip de marker prezent pe o zi reala, dispatch-ul
     produce tooltip-ul corect + cardul devine vizibil. (Bug-ul reparat in 7b1c449 era ca
     ramura "react" LIPSEA din _marker_hover_at -> Acc/Rej n-avea tooltip.)
  2. _marker_hover_at: cu cursorul EXACT pe un marker, proximitatea in px il selecteaza si
     arata cardul (calea manuala care inlocuieste sigHovered nativ, mort in PySide6/pg 0.14).

Date reale (skip daca lipsesc). Offscreen.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob

import pytest

from data.loader import PARQUET_DIR

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

DAY = "20260818"   # 1min: are toate tipurile (big/abs/exh/react) - vezi sonda


@pytest.fixture(scope="module")
def win():
    from pyqtgraph.Qt import QtWidgets
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from app.desktop.main import MainWindow
    w = MainWindow()
    w.cbo_interval.setCurrentText("1min")   # -> _reload_keep
    for i in range(w.cbo_day.count()):
        if DAY in str(w.cbo_day.itemData(i)):
            w.cbo_day.setCurrentIndex(i)     # -> _reload (sincron)
            break
    else:
        pytest.skip(f"ziua {DAY} lipseste")
    # Layerele de markere sunt OFF by default; Ali le porneste (portocalii in UI).
    for chk in (w.chk_big, w.chk_abs, w.chk_exh, w.chk_react):
        chk.setChecked(True)     # stateChanged -> _apply_lod -> scatter vizibil
    return w


def _tooltip_text(win):
    return win.hover_card.textItem.toPlainText()


# tip marker -> (atribut scatter, substring asteptat in tooltip)
CASES = [
    ("big",   "big_scatter",   "contracte"),
    ("abs",   "abs_scatter",   "Absorption"),
    ("exh",   "exh_scatter",   "Exhaustion"),
    ("react", "react_scatter", ("Rejection", "Acceptance")),
]


@pytest.mark.parametrize("kind,attr,expect", CASES)
def test_each_marker_type_has_tooltip(win, kind, attr, expect):
    """Dispatch-ul _on_marker_hover produce tooltip corect pentru fiecare tip prezent."""
    scatter = getattr(win, attr)
    pts = [p for p in scatter.points() if p.data() and p.data()[0] == kind]
    if not pts:
        pytest.skip(f"ziua {DAY} nu are markere de tip {kind}")
    win.hover_card.setVisible(False)
    win._on_marker_hover(scatter, [pts[0]], None)   # ev=None -> pozitionare la punct
    assert win.hover_card.isVisible(), f"{kind}: cardul de hover trebuie sa fie vizibil"
    txt = _tooltip_text(win)
    exps = expect if isinstance(expect, tuple) else (expect,)
    assert any(e in txt for e in exps), f"{kind}: tooltip '{txt}' nu contine {exps}"


def test_marker_hover_at_selects_marker_under_cursor(win):
    """Cursorul EXACT pe un marker Absorption -> _marker_hover_at il gaseste (raza px) si
    arata cardul. Testeaza calea de proximitate care inlocuieste sigHovered nativ."""
    import pyqtgraph as pg
    from pyqtgraph.Qt import QtWidgets

    pts = [p for p in win.abs_scatter.points() if p.data() and p.data()[0] == "abs"]
    if not pts:
        pytest.skip(f"ziua {DAY} nu are markere absorption")

    win.resize(1400, 800)
    win.show()
    QtWidgets.QApplication.instance().processEvents()

    vb = win.price.getViewBox()
    p = pts[0]
    pos = p.pos()
    # centram viewport-ul pe marker ca sa fie in cadru + pixel size determinat
    vb.setRange(xRange=(pos.x() - 600, pos.x() + 600),
                yRange=(pos.y() - 30, pos.y() + 30), padding=0)
    QtWidgets.QApplication.instance().processEvents()
    xs, ys = vb.viewPixelSize()
    if xs <= 0 or ys <= 0:
        pytest.skip("viewPixelSize degenerat offscreen (fara geometrie reala)")

    win.hover_card.setVisible(False)
    win._marker_hover_at(vb, pg.Point(pos.x(), pos.y()))    # cursor exact pe marker
    assert win.hover_card.isVisible(), "cardul trebuie sa apara cand cursorul e pe marker"
    assert "Absorption" in _tooltip_text(win)


def test_rth_only_filters_markers(win):
    """'Doar RTH': dupa activare, TOATE markerele ramase sunt in sesiunea RTH (09:30-16:00 ET)
    si numarul total scade (18.08 are markere overnight, ex. exhaustion 100% overnight)."""
    from pyqtgraph.Qt import QtWidgets
    app = QtWidgets.QApplication.instance()
    scatters = ("big_scatter", "abs_scatter", "exh_scatter", "react_scatter")

    win.chk_rth_only.setChecked(False)          # filtru OFF -> tot
    app.processEvents()
    full = sum(len(getattr(win, a).points()) for a in scatters)
    assert full > 0

    win.chk_rth_only.setChecked(True)           # filtru ON -> _rerender_current
    app.processEvents()
    try:
        kept = 0
        for a in scatters:
            for p in getattr(win, a).points():
                assert win._is_rth(p.pos().x()), f"{a}: marker in afara RTH a scapat de filtru"
                kept += 1
        assert kept < full, "filtrul RTH ar trebui sa scoata markerele overnight"
    finally:
        win.chk_rth_only.setChecked(False)      # restaureaza pt testele urmatoare
        app.processEvents()
