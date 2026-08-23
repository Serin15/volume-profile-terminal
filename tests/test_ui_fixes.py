"""Teste pentru fix-urile de UI (bug-uri raportate pe screenshot):
  1. etichetele prior (yPOC/yVAH/yVAL/PDH/PDL) arata VALORILE, nu '0.00';
  2. layout-ul NU mai forteaza latimea ferestrei peste ecran (LayerBar in scroll,
     graficul poate ceda latime) -> panoul Context / dock-ul Historical Profiles incap.

Date reale (skip daca lipsesc). Offscreen.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob

import pytest

from data.loader import PARQUET_DIR

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

DAY = "20260615"   # are ziua precedenta (14.06) disponibila -> prior real


@pytest.fixture(scope="module")
def win():
    from pyqtgraph.Qt import QtWidgets
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from app.desktop.main import MainWindow
    return MainWindow()


def _select_day(win, ymd):
    for i in range(win.cbo_day.count()):
        if ymd in str(win.cbo_day.itemData(i)):
            win.cbo_day.setCurrentIndex(i)
            return True
    return False


def test_prior_labels_show_values_not_zero(win):
    """Bug: liniile prior erau pozitionate corect dar eticheta ramanea 'yPOC 0.00'
    (InfLineLabel.valueChanged face early-return cat linia e ascunsa la setPos)."""
    if not _select_day(win, DAY):
        pytest.skip("ziua de test lipseste")
    win.chk_prior.setChecked(True)
    assert win._prior is not None, "prior ar trebui sa existe (14.06 e disponibil)"
    for key in ("poc", "vah", "val", "high", "low"):
        ln = win.prior_lines[key]
        text = ln.label.textItem.toPlainText()
        assert ln.value() > 1.0                          # pozitie reala
        assert f"{ln.value():.2f}" in text, f"{key}: eticheta '{text}' nu contine valoarea"
        assert "0.00" not in text or ln.value() == 0.0   # fara '0.00' stale


def test_layout_does_not_force_window_over_screen(win):
    """LayerBar e intr-un scroll (nu mai forteaza latimea minima) + graficul poate ceda
    latime -> panoul Context si dock-ul nu mai ies off-screen pe 1920."""
    from pyqtgraph.Qt import QtWidgets
    # graficul poate ceda latime
    assert win.glw.minimumWidth() <= 600
    # randul LayerBar e un QScrollArea cu minim mic (decuplat de latimea ferestrei)
    central = win.centralWidget()
    lay = central.layout()
    row3 = lay.itemAt(3).widget()
    assert isinstance(row3, QtWidgets.QScrollArea)
    assert row3.minimumWidth() <= 200


def test_dock_and_context_open_without_error(win):
    """Sanity: deschiderea dock-ului + panoului Context nu crapa si raman functionale."""
    win.chk_ctx.setChecked(True)
    win.btn_profile_only.setChecked(True)
    assert not win.hist_dock.isHidden()
    assert not win.ctx_container.isHidden()          # isVisible() e fals daca fereastra nu e show()
    win.btn_profile_only.setChecked(False)
    win.chk_ctx.setChecked(False)
    assert win.ctx_container.isHidden()
