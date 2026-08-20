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

Faza 1 NU face sincronizare cu replay/cursor (vine in Faza 2): selectezi manual
ziua + sesiunea si vezi profilul complet al acelei sesiuni istorice.
"""

from pyqtgraph.Qt import QtCore, QtWidgets

from app.desktop import theme
from app.desktop.vp_view import VolumeProfileView


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

        # --- profilul ---
        self.view = VolumeProfileView()
        self.view.setMinimumHeight(220)
        outer.addWidget(self.view, 1)

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
            f"QLabel#CardLevels{{color:{theme.TEXT_DIM};font-family:'Consolas',monospace;}}")

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

    # ---------- randare ----------
    def _refresh(self, *a):
        filename = self.cbo_date.currentData()
        session = self.cbo_session.currentText()
        profs = []
        if filename:
            try:
                profs = self.store.get_session_profile(
                    filename, session=session, row_size=self._row_size, va_percent=self._va)
            except Exception:
                profs = []
        if profs:
            p = profs[0]
            self.view.set_profile(p, row_size=self._row_size)
            self.lbl_levels.setText(
                f"POC {p['poc']:.2f}    VAH {p['vah']:.2f}    VAL {p['val']:.2f}")
        else:
            self.view.clear()
            self.lbl_levels.setText("— fără date pentru selecție —")


class HistoricalProfilePanel(QtWidgets.QDockWidget):
    """Dock-ul cu profile istorice. Detasabil, mutabil, redimensionabil, inchidibil."""

    def __init__(self, store, day_items, row_size=2.0, va_percent=0.70, parent=None):
        super().__init__("Historical Profile", parent)
        self.store = store
        self._day_items = list(day_items)
        self._row_size = float(row_size)
        self._va = float(va_percent)
        self.setObjectName("HistoricalProfileDock")   # necesar pentru saveState/restoreState
        self.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable
                         | QtWidgets.QDockWidget.DockWidgetFloatable
                         | QtWidgets.QDockWidget.DockWidgetClosable)
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)

        root = QtWidgets.QWidget(); root.setObjectName("HistRoot")
        rv = QtWidgets.QVBoxLayout(root); rv.setContentsMargins(8, 8, 8, 8); rv.setSpacing(6)

        title = QtWidgets.QLabel("HISTORICAL PROFILES"); title.setObjectName("HistTitle")
        rv.addWidget(title)
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
