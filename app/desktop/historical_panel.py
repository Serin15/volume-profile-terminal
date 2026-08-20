"""
HistoricalProfilePanel — dock separat pentru Volume Profile-uri ISTORICE (Faza 1)
---------------------------------------------------------------------------------
Scop: SEPARAM analiza profilelor istorice de Main Chart. Cand utilizatorul cere
"Profile Only", profilele NU se mai deseneaza peste graficul principal; se deschide
acest QDockWidget (mutabil / redimensionabil / detasabil pe alt monitor / inchidibil).

Structura:
  HistoricalProfilePanel (QDockWidget)
    └─ [ + Add Profile ]
    └─ ProfileCard*   (Date ▼ · Session ▼ · [Volume Profile] · POC/VAH/VAL)

Fiecare card isi alege independent data + sesiunea (Full Day / Asia / London /
New York) si citeste profilul prin SessionStore (Faza 0) — FARA sa reincarce ticks
sau sa recalculeze VP. Cardurile sunt independente (nu se contamineaza intre ele).

Faza 2 (sync OPT-IN cu replay-ul): daca bifezi "Sync to replay cursor" si un card
selecteaza ZIUA de replay, profilul se calculeaza CAUZAL — doar pe footprint-ul din
snapshot (deja taiat la cursor), pe fereastra sesiunii. Zilele ISTORICE (deja inchise)
raman profile COMPLETE. Fara sync (implicit) sau pentru alte zile: profil complet, ca
in Faza 1. Cauzalitatea vine din Replay (single source of truth); aici doar afisam.
"""

from pyqtgraph.Qt import QtCore, QtWidgets

from app.desktop import theme
from app.desktop.vp_view import VolumeProfileView
import app.desktop.data_service as ds


def _fmt_k(v):
    """Volum compact: 1234 -> 1.2K, 12345 -> 12K."""
    a = abs(v)
    if a >= 1000:
        return (f"{v/1000:.1f}K" if a < 10000 else f"{v/1000:.0f}K").replace(".0K", "K")
    return f"{v:.0f}"


class ProfileCard(QtWidgets.QFrame):
    """Un card: selector data + sesiune, un VolumeProfileView si POC/VAH/VAL.
    Reutilizabil si independent — mai multe carduri = mai multe profile comparate."""

    removed = QtCore.Signal(object)   # emis cu self la apasarea pe ×

    def __init__(self, store, day_items, default_file=None,
                 default_session="New York", row_size=2.0, va_percent=0.70, parent=None):
        super().__init__(parent)
        self.store = store
        self._row_size = float(row_size)
        self._va = float(va_percent)
        # Faza 2: starea de replay (setata de panou). Card "live" = sync ON + ziua de replay.
        self._sync_on = False
        self._replay_day = None
        self._replay_snapshot = None
        self.setObjectName("ProfileCard")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8); outer.setSpacing(4)

        # --- rand selector: Date + Session + remove ---
        head = QtWidgets.QHBoxLayout(); head.setSpacing(6)
        self.cbo_date = QtWidgets.QComboBox()
        self.cbo_session = QtWidgets.QComboBox()
        self.cbo_session.addItems(store.available_sessions())
        idx = self.cbo_session.findText(default_session)
        if idx >= 0:
            self.cbo_session.setCurrentIndex(idx)
        self.btn_remove = QtWidgets.QToolButton()
        self.btn_remove.setText("×"); self.btn_remove.setToolTip("Închide acest profil")
        self.btn_remove.setCursor(QtCore.Qt.PointingHandCursor)
        head.addWidget(QtWidgets.QLabel("Date:")); head.addWidget(self.cbo_date, 1)
        head.addWidget(QtWidgets.QLabel("Session:")); head.addWidget(self.cbo_session, 1)
        head.addWidget(self.btn_remove)
        outer.addLayout(head)

        # --- selector mod de citire: TOTAL (clean) / SPLIT (buy-sell) / DELTA ---
        mode_row = QtWidgets.QHBoxLayout(); mode_row.setSpacing(4)
        self.mode_group = QtWidgets.QButtonGroup(self); self.mode_group.setExclusive(True)
        self._mode_btns = {}
        for m in ("TOTAL", "SPLIT", "DELTA"):
            b = QtWidgets.QToolButton(); b.setText(m); b.setCheckable(True)
            b.setObjectName("ModeBtn"); b.setCursor(QtCore.Qt.PointingHandCursor)
            self.mode_group.addButton(b); self._mode_btns[m] = b
            mode_row.addWidget(b)
        mode_row.addStretch(1)
        self._mode_btns["TOTAL"].setChecked(True)
        outer.addLayout(mode_row)

        # --- profilul ---
        self.view = VolumeProfileView()
        self.view.setMinimumHeight(220)
        outer.addWidget(self.view, 1)
        for m, b in self._mode_btns.items():
            b.clicked.connect(lambda _=False, mm=m: self.view.set_mode(mm.lower()))

        # --- eticheta POC/VAH/VAL ---
        self.lbl_levels = QtWidgets.QLabel("")
        self.lbl_levels.setObjectName("CardLevels")
        outer.addWidget(self.lbl_levels)

        self.set_day_items(day_items, select=default_file)

        self.cbo_date.currentIndexChanged.connect(self._refresh)
        self.cbo_session.currentIndexChanged.connect(self._refresh)
        self.btn_remove.clicked.connect(lambda: self.removed.emit(self))

        self.setStyleSheet(
            f"QFrame#ProfileCard{{border:1px solid {theme.BORDER};border-radius:6px;"
            f"background:{theme.BG};}}"
            f"QLabel#CardLevels{{color:{theme.TEXT_DIM};font-family:'Consolas',monospace;}}"
            f"QToolButton#ModeBtn{{color:{theme.TEXT_DIM};background:transparent;"
            f"border:1px solid {theme.BORDER};border-radius:4px;padding:2px 9px;font-size:11px;}}"
            f"QToolButton#ModeBtn:checked{{color:{theme.TEXT};border-color:{theme.TEXT_DIM};"
            f"background:rgba(255,255,255,0.06);}}")

        self._refresh()

    # ---------- date ----------
    def set_day_items(self, day_items, select=None):
        """(Re)populeaza dropdown-ul de date. day_items = list de (label, filename)."""
        keep = select if select is not None else self.cbo_date.currentData()
        self.cbo_date.blockSignals(True)
        self.cbo_date.clear()
        for label, filename in day_items:
            self.cbo_date.addItem(label, userData=filename)
        if keep is not None:
            i = self.cbo_date.findData(keep)
            if i >= 0:
                self.cbo_date.setCurrentIndex(i)
        self.cbo_date.blockSignals(False)

    def set_row_size(self, row_size):
        self._row_size = float(row_size)
        self._refresh()

    def selection(self):
        """(filename, session) curent — util in teste."""
        return self.cbo_date.currentData(), self.cbo_session.currentText()

    # ---------- sync cu replay (Faza 2) ----------
    def set_replay_context(self, replay_day, snapshot, sync_on):
        """Primeste starea de replay de la panou. NU redeseneaza singur — panoul decide
        cine se recalculeaza (doar cardurile zilei de replay, la miscarea cursorului)."""
        self._replay_day = replay_day
        self._replay_snapshot = snapshot
        self._sync_on = bool(sync_on)

    def is_live(self):
        """True daca acest card e taiat la cursor (sync ON + ziua de replay selectata)."""
        return (self._sync_on and self._replay_snapshot is not None
                and self.cbo_date.currentData() == self._replay_day)

    def refresh(self):
        """Redesenare publica (folosita de panou / teste)."""
        self._refresh()

    def _causal_profiles(self, session):
        """Profil CAUZAL al zilei de replay pana la cursor: agregat DOAR pe footprint-ul
        din snapshot (deja taiat la cursor) pe fereastra sesiunii. Reutilizeaza
        data_service.profile_from_footprint — fara motor nou, fara look-ahead."""
        fp = self._replay_snapshot.footprint
        win = ds.session_window(self.cbo_date.currentData(), session)
        if win is None:
            epochs = [int(e) for e in fp.keys()]              # Full Day = toata sesiunea (<= cursor)
        else:
            s, e = win
            epochs = [int(ep) for ep in fp.keys() if s <= ep < e]
        prof = ds.profile_from_footprint(fp, epochs, self._row_size, self._va)
        return [prof] if prof else []

    # ---------- randare ----------
    def _refresh(self, *a):
        filename = self.cbo_date.currentData()
        session = self.cbo_session.currentText()
        profs = []
        if filename:
            try:
                if self.is_live():
                    profs = self._causal_profiles(session)        # taiat la cursor
                else:
                    profs = self.store.get_session_profile(       # complet (istoric / sync off)
                        filename, session=session, row_size=self._row_size, va_percent=self._va)
            except Exception:
                profs = []
        if profs:
            p = profs[0]
            self.view.set_profile(p, row_size=self._row_size)
            bp = p["bin_price"]
            hi, lo = float(bp.max()), float(bp.min())
            delta = float(p["bin_buy"].sum() - p["bin_sell"].sum())
            dsign = "+" if delta >= 0 else "-"
            nh, nl = len(p.get("hvn") or []), len(p.get("lvn") or [])
            self.lbl_levels.setText(
                f"POC {p['poc']:.2f}   VAH {p['vah']:.2f}   VAL {p['val']:.2f}\n"
                f"Vol {_fmt_k(p['total'])}  ·  Δ {dsign}{_fmt_k(abs(delta))}  ·  "
                f"H {hi:.2f}  L {lo:.2f}  ·  HVN {nh} · LVN {nl}")
        else:
            self.view.clear()
            self.lbl_levels.setText("— fără date pentru selecție —")


class HistoricalProfilePanel(QtWidgets.QDockWidget):
    """Dock-ul cu profile istorice. Detasabil, mutabil, redimensionabil, inchidibil."""

    def __init__(self, store, day_items, row_size=2.0, va_percent=0.70, parent=None):
        super().__init__("Historical Profiles", parent)
        self.store = store
        self._day_items = list(day_items)
        self._row_size = float(row_size)
        self._va = float(va_percent)
        # Faza 2: sync OPT-IN cu replay-ul (implicit OFF -> comportament Faza 1).
        self._sync = False
        self._replay_day = None
        self._replay_snapshot = None
        self._last_key = None          # throttle pe (zi, n_ticks): recalcul doar la miscarea cursorului
        self.setObjectName("HistoricalProfileDock")   # necesar pentru saveState/restoreState
        self.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                         | QtWidgets.QDockWidget.DockWidgetFloatable
                         | QtWidgets.QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)

        root = QtWidgets.QWidget(); root.setObjectName("HistRoot")
        rv = QtWidgets.QVBoxLayout(root); rv.setContentsMargins(8, 8, 8, 8); rv.setSpacing(6)

        title = QtWidgets.QLabel("HISTORICAL PROFILES"); title.setObjectName("HistTitle")
        rv.addWidget(title)
        self.chk_sync = QtWidgets.QCheckBox("🔗 Sync to replay cursor")
        self.chk_sync.setToolTip(
            "Optional. Cand e bifat, cardul cu ZIUA de replay se taie CAUZAL la cursor\n"
            "(doar date pana la momentul curent, fara look-ahead). Zilele istorice raman\n"
            "profile complete. Nebifat = toate profilele sunt complete (ca in Faza 1).")
        self.chk_sync.toggled.connect(self._on_sync_toggled)
        rv.addWidget(self.chk_sync)
        self.btn_add = QtWidgets.QPushButton("+ Add Profile")
        self.btn_add.clicked.connect(lambda: self.add_card())
        rv.addWidget(self.btn_add)

        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder = QtWidgets.QWidget()
        self._cards_lay = QtWidgets.QVBoxLayout(holder)
        self._cards_lay.setContentsMargins(0, 0, 0, 0); self._cards_lay.setSpacing(8)
        self._cards_lay.addStretch(1)
        scroll.setWidget(holder)
        rv.addWidget(scroll, 1)

        root.setStyleSheet(
            f"QWidget#HistRoot{{background:{theme.BG};}}"
            f"QLabel#HistTitle{{color:{theme.TEXT};font-weight:600;letter-spacing:1px;}}")
        self.setWidget(root)

        self._cards = []
        default_file = self._day_items[-1][1] if self._day_items else None
        self.add_card(default_file=default_file)

    # ---------- carduri ----------
    def add_card(self, default_file=None, default_session="New York"):
        if default_file is None and self._day_items:
            default_file = self._day_items[-1][1]
        card = ProfileCard(self.store, self._day_items, default_file=default_file,
                           default_session=default_session, row_size=self._row_size,
                           va_percent=self._va)
        card.removed.connect(self._remove_card)
        # inserat inaintea stretch-ului final
        self._cards_lay.insertWidget(self._cards_lay.count() - 1, card)
        self._cards.append(card)
        # primeste contextul de replay curent (devine cauzal daca e ziua de replay + sync ON)
        card.set_replay_context(self._replay_day, self._replay_snapshot, self._sync)
        if card.is_live():
            card.refresh()
        return card

    def _remove_card(self, card):
        if card in self._cards:
            self._cards.remove(card)
            self._cards_lay.removeWidget(card)
            card.setParent(None)
            card.deleteLater()

    def cards(self):
        return list(self._cards)

    # ---------- context din MainWindow ----------
    def set_day_items(self, day_items):
        """Reimprospateaza lista de zile in toate cardurile (ex. dupa deschiderea unui fisier)."""
        self._day_items = list(day_items)
        for card in self._cards:
            card.set_day_items(self._day_items)

    def set_row_size(self, row_size):
        """Aliniaza rezolutia VP a cardurilor cu cea din Main Chart."""
        self._row_size = float(row_size)
        for card in self._cards:
            card.set_row_size(row_size)

    # ---------- sync cu replay (Faza 2) ----------
    def set_replay_state(self, day, snapshot):
        """Primit de la MainWindow la fiecare randare de replay (snapshot = stare CAUZALA
        la cursor). Throttle pe (zi, n_ticks): recalcul DOAR cand cursorul chiar s-a mutat,
        si DOAR pentru cardurile zilei de replay (performanta — nu atingem zilele istorice)."""
        key = (day, getattr(snapshot, "n_ticks", None))
        if key == self._last_key:
            return                                  # cursor neschimbat -> nimic de facut
        self._last_key = key
        self._replay_day = day
        self._replay_snapshot = snapshot
        for c in self._cards:
            c.set_replay_context(day, snapshot, self._sync)
        if not self._sync:
            return                                  # sync OFF -> cardurile raman complete
        for c in self._cards:
            if c.cbo_date.currentData() == day:     # doar ziua de replay -> recalcul cauzal
                c.refresh()

    def clear_replay_state(self):
        """Iesire din replay / vedere statica: cardurile revin la profil COMPLET. Idempotent."""
        if self._replay_snapshot is None and self._last_key is None:
            return
        self._last_key = None
        self._replay_day = None
        self._replay_snapshot = None
        for c in self._cards:
            c.set_replay_context(None, None, self._sync)
            c.refresh()

    def _on_sync_toggled(self, on):
        """Opt-in ON/OFF. La schimbare, reimprospateaza toate cardurile (rar -> ok)."""
        self._sync = bool(on)
        for c in self._cards:
            c.set_replay_context(self._replay_day, self._replay_snapshot, self._sync)
            c.refresh()

    def sync_enabled(self):
        return self._sync
