"""Teste Faza 1 — HistoricalProfilePanel (dock separat pentru VP istoric).

Criteriul principal: "Profile Only" deschide dock-ul, iar Main Chart NU mai primeste
niciun overlay de profil istoric. Restul: selectie data/sesiune, Full Day/Asia/
London/NY, date lipsa elegant, folosirea SessionStore (nu loadere duplicate),
independenta intre carduri, determinism, dock inchis/redeschis.

Date reale (skip daca lipsesc). Offscreen (QGraphics).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob

import pytest

from data.loader import PARQUET_DIR
from app.desktop.session_store import SessionStore
from app.desktop.historical_panel import HistoricalProfilePanel, ProfileCard

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

ROW = 2.0


@pytest.fixture(scope="module")
def qapp():
    from pyqtgraph.Qt import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(scope="module")
def win(qapp):
    from app.desktop.main import MainWindow
    return MainWindow()


def _day_items():
    from app.desktop.main import discover_files, nice_label
    return [(nice_label(f), f) for f in discover_files()]


def _profile_of(card):
    return card.view._profile


# ================= Integrare prin MainWindow (criteriul principal) =================
def test_main_chart_type_has_no_profile_only(win):
    """Profile Only nu mai e un TIP de chart -> Main Chart e mereu Profil/Footprint."""
    items = [win.cbo_type.itemText(i) for i in range(win.cbo_type.count())]
    assert items == ["Profil", "Footprint"]


def test_profile_only_opens_and_closes_dock(win):
    win.btn_profile_only.setChecked(True)
    assert not win.hist_dock.isHidden()          # deschis
    win.btn_profile_only.setChecked(False)
    assert win.hist_dock.isHidden()              # inchis
    assert not win.btn_profile_only.isChecked()


def test_profile_only_does_not_draw_on_main_chart(win):
    """CRITERIUL PRINCIPAL: cu Profile Only ON, Main Chart NU primeste overlay istoric."""
    win.btn_profile_only.setChecked(True)
    assert win.period_profiles_item.isVisible() is False
    # lumanarile raman (Main Chart e in continuare graficul principal)
    assert win.candles.isVisible() is True
    win.btn_profile_only.setChecked(False)


def test_dock_features_detachable(win):
    from pyqtgraph.Qt import QtWidgets
    f = win.hist_dock.features()
    assert f & QtWidgets.QDockWidget.DockWidgetFloatable     # detasabil (alt monitor)
    assert f & QtWidgets.QDockWidget.DockWidgetMovable       # mutabil
    assert f & QtWidgets.QDockWidget.DockWidgetClosable      # inchidibil
    assert win.hist_dock.objectName() == "HistoricalProfileDock"   # pt saveState


def test_dock_close_reopen_keeps_cards(win):
    win.btn_profile_only.setChecked(True)
    n = len(win.hist_dock.cards())
    win.btn_profile_only.setChecked(False)
    win.btn_profile_only.setChecked(True)
    assert len(win.hist_dock.cards()) == n       # cardurile persista
    win.btn_profile_only.setChecked(False)


def test_uses_shared_sessionstore(win):
    """Dock-ul consuma prin SessionStore-ul comun (nu instantiaza altul)."""
    assert win.hist_dock.store is win._store
    for card in win.hist_dock.cards():
        assert card.store is win._store


# ================= Panou izolat (rapid, store proaspat) =================
def test_session_change_changes_profile(qapp):
    store = SessionStore()
    items = _day_items()
    card = ProfileCard(store, items, default_file=items[-1][1],
                       default_session="New York", row_size=ROW)
    card.cbo_session.setCurrentText("New York"); ny = _profile_of(card)
    card.cbo_session.setCurrentText("Asia"); asia = _profile_of(card)
    assert ny is not None and asia is not None
    assert ny["total"] != asia["total"]          # sesiuni diferite = profile diferite


def test_date_change_changes_profile(qapp):
    store = SessionStore()
    items = _day_items()
    card = ProfileCard(store, items, default_file=items[0][1],
                       default_session="Full Day", row_size=ROW)
    p0 = _profile_of(card)
    card.cbo_date.setCurrentIndex(card.cbo_date.count() - 1)   # alta zi
    p1 = _profile_of(card)
    assert p0 is not None and p1 is not None
    assert p0["poc"] != p1["poc"] or p0["total"] != p1["total"]


def test_all_four_sessions_work(qapp):
    store = SessionStore()
    items = _day_items()
    card = ProfileCard(store, items, default_file=items[-1][1], row_size=ROW)
    for sess in ("Full Day", "Asia", "London", "New York"):
        card.cbo_session.setCurrentText(sess)
        # fie profil valid (VAL<=POC<=VAH), fie stare goala eleganta — fara crash
        p = _profile_of(card)
        if p is not None:
            assert p["val"] <= p["poc"] + 1e-9 <= p["vah"] + 1e-9
        else:
            assert "fără date" in card.lbl_levels.text()


def test_missing_data_graceful(qapp):
    """Fisier inexistent -> stare goala, fara exceptie."""
    store = SessionStore()
    items = _day_items() + [("ZI INEXISTENTA", "glbx-mdp3-20990101.trades.parquet")]
    card = ProfileCard(store, items, default_file="glbx-mdp3-20990101.trades.parquet",
                       row_size=ROW)
    assert _profile_of(card) is None
    assert "fără date" in card.lbl_levels.text()


def test_empty_day_items_graceful(qapp):
    store = SessionStore()
    panel = HistoricalProfilePanel(store, [], row_size=ROW)   # nicio zi disponibila
    assert len(panel.cards()) == 1
    assert _profile_of(panel.cards()[0]) is None               # gol, fara crash


def test_two_cards_no_cross_contamination(qapp):
    store = SessionStore()
    items = _day_items()
    panel = HistoricalProfilePanel(store, items, row_size=ROW)
    c1 = panel.cards()[0]
    c1.cbo_date.setCurrentIndex(0); c1.cbo_session.setCurrentText("New York")
    c2 = panel.add_card()
    c2.cbo_date.setCurrentIndex(c2.cbo_date.count() - 1); c2.cbo_session.setCurrentText("Asia")
    p1_before = dict(_profile_of(c1) or {})
    # schimbam c2 -> c1 NU se schimba
    c2.cbo_session.setCurrentText("London")
    p1_after = _profile_of(c1)
    assert p1_after is not None
    assert p1_before.get("poc") == p1_after["poc"]
    assert p1_before.get("total") == p1_after["total"]
    # c1 si c2 sunt selectii diferite
    assert c1.selection() != c2.selection()


def test_determinism_same_selection_same_vp(qapp):
    items = _day_items()
    f = items[-1][1]
    a = ProfileCard(SessionStore(), items, default_file=f, default_session="New York", row_size=ROW)
    b = ProfileCard(SessionStore(), items, default_file=f, default_session="New York", row_size=ROW)
    pa, pb = _profile_of(a), _profile_of(b)
    assert pa is not None and pb is not None
    assert (pa["poc"], pa["vah"], pa["val"], pa["total"]) == \
           (pb["poc"], pb["vah"], pb["val"], pb["total"])


def test_card_routes_through_store(qapp, monkeypatch):
    """Dovada ca ProfileCard cere datele prin SessionStore (nu loader propriu)."""
    store = SessionStore()
    calls = {"n": 0}
    real = store.get_session_profile

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(store, "get_session_profile", spy)
    items = _day_items()
    ProfileCard(store, items, default_file=items[-1][1], row_size=ROW)
    assert calls["n"] >= 1


# ================= Punctul 5 + 11: valori din engine, HVN/LVN, no-look-ahead =========
def test_profile_values_match_engine(qapp):
    """Valorile afisate == exact ce intoarce engine-ul (via period_profiles): identice
    POC/VAH/VAL/HVN/LVN/total. Panoul NU recalculeaza — reutilizeaza engine-ul."""
    import app.desktop.data_service as ds
    items = _day_items()
    f = items[-1][1]
    card = ProfileCard(SessionStore(), items, default_file=f,
                       default_session="New York", row_size=ROW)
    shown = card.view._profile
    direct = ds.period_profiles(f, unit="NY", span="day", row_size=ROW)[0]
    assert shown is not None
    for k in ("poc", "vah", "val", "total"):
        assert shown[k] == direct[k], f"{k} difera de engine"
    assert list(shown["hvn"]) == list(direct["hvn"])
    assert list(shown["lvn"]) == list(direct["lvn"])


def test_hvn_lvn_displayed(qapp):
    """HVN/LVN chiar apar ca linii in profil (nu doar in text)."""
    items = _day_items()
    card = ProfileCard(SessionStore(), items, default_file=items[-1][1],
                       default_session="New York", row_size=ROW)
    p = card.view._profile
    assert card.view.node_line_count() == len(p["hvn"]) + len(p["lvn"])


def _set_date(card, ymd):
    for i in range(card.cbo_date.count()):
        if ymd in str(card.cbo_date.itemData(i)):
            card.cbo_date.setCurrentIndex(i)
            return True
    return False


def test_three_profiles_coexist(qapp):
    """Exemplul din cerere: 3 zile August -> NY, coexista si sunt distincte."""
    store = SessionStore()
    items = _day_items()
    panel = HistoricalProfilePanel(store, items, row_size=ROW)
    c1 = panel.cards()[0]
    c2 = panel.add_card()
    c3 = panel.add_card()
    assert _set_date(c1, "20260804") and _set_date(c2, "20260803") and _set_date(c3, "20260805")
    for c in (c1, c2, c3):
        c.cbo_session.setCurrentText("New York")
    assert len(panel.cards()) == 3
    assert len({c.selection() for c in (c1, c2, c3)}) == 3       # 3 selectii distincte
    pocs = [c.view._profile["poc"] for c in (c1, c2, c3) if c.view._profile]
    assert len(pocs) == 3                                        # toate 3 au profil


def test_no_lookahead_panel(qapp):
    """No-look-ahead structural: modulele panoului NU importa replay/cursor, iar profilul
    afisat e sesiunea ISTORICA COMPLETA (nu trunchiata) — deci nici viitor lipsa, nici in plus."""
    import ast
    import inspect
    import app.desktop.historical_panel as hp
    import app.desktop.vp_view as vv
    for mod in (hp, vv):
        tree = ast.parse(inspect.getsource(mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {n.name for n in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any("replay" in m.lower() for m in imported), (mod.__name__, imported)
    import app.desktop.data_service as ds
    items = _day_items()
    f = items[-1][1]
    card = ProfileCard(SessionStore(), items, default_file=f,
                       default_session="Full Day", row_size=ROW)
    direct = ds.period_profiles(f, unit="Zi", span="day", row_size=ROW)[0]
    assert card.view._profile["total"] == direct["total"]        # sesiune completa, nimic viitor


def test_close_reopen_preserves_app_state(win):
    """Inchiderea/redeschiderea dock-ului NU strica starea Main Chart-ului."""
    data_before = win._data
    n = len(win._data.t) if win._data is not None else 0
    for state in (True, False, True, False):
        win.btn_profile_only.setChecked(state)
    assert win._data is data_before                 # exact acelasi obiect de date
    assert len(win._data.t) == n
    assert win.candles.isVisible()                  # Main Chart intact
    assert [win.cbo_type.itemText(i) for i in range(win.cbo_type.count())] == ["Profil", "Footprint"]
    assert win.period_profiles_item.isVisible() is False
