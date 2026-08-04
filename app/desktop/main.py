"""
Fereastra principala a terminalului de Volume Profile (PySide6 + pyqtgraph).

Layout:
  - bara de sus: titlu + controale (zi, interval, VA%, rezolutie)
  - rand de statistici: POC / VAH-VAL / Volum / Cumulative Delta
  - grafic: lumanari (stanga) + Volume Profile split buy/sell (dreapta), axa Y comuna
  - POC / Value Area intinse peste tot, crosshair cu pret + ora
"""

import os
import re
import glob
import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from data.loader import PARQUET_DIR, RAW_DIR
from app.desktop import theme
from app.desktop.data_service import (load_day, INTERVAL_SECONDS, resolve_ticks,
                                      prior_session_levels, profile_from_footprint,
                                      session_profiles, SESSION_DEFS, TICK_SIZE,
                                      BIG_TRADE_MIN, ABS_MIN_VOL, ABS_DOM, ABS_REJECT,
                                      EXH_WINDOW, EXH_VOL_MULT, EXH_DELTA_FRAC)
from app.desktop.charts import (CandlestickItem, ProfileOverlayItem, FootprintItem,
                                GridStatsItem, StatsAxis)
from app.desktop.replay import Replay
from app.desktop.drawings import DrawingManager

class _DragScaleAxis:
    """
    Mixin: LEFT-drag pe axa SCALEAZA (comprima/extinde), ca la TradingView/DeepCharts.
    Pe axa verticala (preț) scaleaza Y; pe cea orizontala (timp) scaleaza X.
    (Implicit pyqtgraph face doar pan pe left-drag; scalare doar pe right-drag.)
    """

    def mouseDragEvent(self, ev):
        lv = self.linkedView()
        if lv is None:
            return ev.ignore()
        # daca drag-ul a pornit in interiorul graficului, nu noi ne ocupam (pan normal)
        if lv.sceneBoundingRect().contains(ev.buttonDownScenePos()):
            return ev.ignore()
        ev.accept()
        if self.orientation in ("left", "right"):
            d = ev.pos().y() - ev.lastPos().y()
            s = (1.0, max(0.5, min(1.5, 1.0 + d * 0.01)))     # scaleaza doar Y
        else:
            d = ev.pos().x() - ev.lastPos().x()
            s = (max(0.5, min(1.5, 1.0 - d * 0.01)), 1.0)      # scaleaza doar X
        try:
            center = lv.mapSceneToView(ev.buttonDownScenePos())
        except Exception:
            center = None
        lv.scaleBy(s, center)


class PriceAxis(_DragScaleAxis, pg.AxisItem):
    """Axa de preț (dreapta): trage de ea ca sa comprimi/extinzi scala prețului."""


class UTCDateAxis(_DragScaleAxis, pg.DateAxisItem):
    """Axa de timp care afiseaza UTC (nu ora locala, cum face pyqtgraph implicit)."""

    def tickStrings(self, values, scale, spacing):
        off = getattr(self, "tz_offset", 0)
        out = []
        for v in values:
            try:
                dt = datetime.datetime.fromtimestamp(v + off, datetime.timezone.utc)
            except (ValueError, OSError, OverflowError):
                out.append("")
                continue
            if spacing >= 86400:
                out.append(dt.strftime("%d %b"))
            elif dt.hour == 0 and dt.minute == 0:
                out.append(dt.strftime("%d %b"))
            else:
                out.append(dt.strftime("%H:%M"))
        return out


# Fusuri orare (IANA prin zoneinfo -> ora de vara/iarna corecta AUTOMAT, per data).
# Offset-ul se calculeaza pentru DATA sesiunii incarcate, nu pentru ziua de azi.
TZ_OPTIONS = [
    ("Romania", "Europe/Bucharest", "RO"),      # implicit: 16:30 RO = deschidere NY
    ("New York", "America/New_York", "ET"),     # ora bursei (RTH open 09:30)
    ("Chicago", "America/Chicago", "CT"),       # ora CME Globex
    ("UTC", None, "UTC"),
]
TZ_ZONE = {name: zone for (name, zone, _) in TZ_OPTIONS}
TZ_LABEL = {name: lab for (name, _, lab) in TZ_OPTIONS}


REGIME = {
    "20260504": "bullish", "20260505": "bullish", "20260506": "bullish",
    "20260507": "bullish", "20260508": "bullish",
    "20260706": "range-bound", "20260707": "range-bound", "20260708": "range-bound",
    "20260709": "range-bound", "20260710": "range-bound",
    "20260720": "bearish", "20260721": "bearish", "20260722": "bearish",
    "20260723": "bearish", "20260724": "bearish",
}


def _bt_tier(vol):
    """Marime DISCRETA a bulei Big Trade (trepte) -> vezi instant clasa de marime."""
    if vol >= 200:
        return 26
    if vol >= 100:
        return 19
    if vol >= 50:
        return 13
    return 8


def discover_files():
    files = glob.glob(os.path.join(PARQUET_DIR, "*.parquet"))
    if not files:
        files = glob.glob(os.path.join(RAW_DIR, "*.csv"))
    return sorted(os.path.basename(f) for f in files)


def date_of(name):
    for part in name.replace(".", "-").split("-"):
        if len(part) == 8 and part.isdigit():
            return part
    return name


def nice_label(name):
    d = date_of(name)
    if len(d) == 8:
        reg = REGIME.get(d, "")
        return f"{d[6:8]}.{d[4:6]}.{d[0:4]}" + (f"  ·  {reg}" if reg else "")
    return name


class StatCard(QtWidgets.QFrame):
    def __init__(self, label):
        super().__init__()
        self.setObjectName("StatCard")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 5, 12, 5)
        lay.setSpacing(1)
        self._l = QtWidgets.QLabel(label); self._l.setObjectName("StatLabel")
        self._v = QtWidgets.QLabel("—"); self._v.setObjectName("StatValue")
        lay.addWidget(self._l); lay.addWidget(self._v)

    def set_value(self, txt, color=None):
        self._v.setText(txt)
        self._v.setStyleSheet(f"color:{color};" if color else "")


# Vederi (preset-uri de straturi): un click aprinde un set curat, gandit, in loc de
# 15 bife. Cheile = starea checkbox-urilor + tipul (Profil/Footprint) + Auto.
VIEWS = {
    "Curat": dict(type="Profil", auto=True, vp=True, nodes=False, vwap=True, dev=False,
                  big=False, abs=False, exh=False, grid=False, cvd=False,
                  prior=False, session=False, sess=False),
    "Order Flow": dict(type="Footprint", auto=True, vp=False, nodes=False, vwap=False, dev=False,
                       big=True, abs=True, exh=True, grid=True, cvd=True,
                       prior=False, session=False, sess=False),
    "NY Open": dict(type="Profil", auto=True, vp=True, nodes=True, vwap=False, dev=False,
                    big=True, abs=True, exh=False, grid=False, cvd=True,
                    prior=True, session=True, sess=True),
    "Tot": dict(type="Footprint", auto=True, vp=True, nodes=True, vwap=True, dev=True,
                big=True, abs=True, exh=True, grid=True, cvd=True,
                prior=True, session=True, sess=True),
}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Volume Profile Terminal — NQ")
        self.resize(1500, 900)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())
        root.addWidget(self._build_stats())
        root.addWidget(self._build_charts(), stretch=1)
        root.addWidget(self._build_layerbar())
        root.addWidget(self._build_replaybar())

        self._replay = None
        self._data_full = None
        self._mode, self._span = "session", "day"
        self._follow = True          # auto-follow activ in replay
        self._prog_range = False     # garda: schimbare de range facuta de noi (nu de user)
        self._prog_slider = False    # garda: mutare scrubber facuta de noi (nu de user)
        self._vp_scope = "full"      # 'full' (sesiune) sau 'visible' (profil pe ce vezi)
        self._lvn_full = False       # LVN pe tot profilul (nu doar intre HVN) - din ⚙ VP
        # Profile per-sesiune (Asia/Londra/NY): mod de definire + ore EDITABILE (copie mutabila)
        self._sess_mode = "real"     # 'real' (fus bursa, auto DST) sau 'ro' (ore Romania fixe)
        self._sessions = {m: [[n, tz, [a, b], [c, d]] for (n, tz, (a, b), (c, d)) in defs]
                          for m, defs in SESSION_DEFS.items()}
        self._sess_data = None
        self._sess_dialog = None
        self._vp_dialog = None
        self._big_min = BIG_TRADE_MIN    # prag Big Trades (reglabil din ⚙)
        self._bt_zones = False           # zone S/R din cele mai mari tranzactii (⚙)
        self._abs_params = {}            # praguri Absorption (reglabile din ⚙)
        self._exh_params = {}            # praguri Exhaustion (reglabile din ⚙)
        self._bt_dialog = None
        self._abs_dialog = None
        self._exh_dialog = None
        self._fp_dialog = None
        self._tz_name = "Romania"    # fus implicit (ora ta: 16:30 = deschidere NY)
        self._tz_offset = 3 * 3600   # provizoriu; recalculat corect per data in _apply_tz
        self._tz_label = "RO"
        self.replay_timer = QtCore.QTimer(self)
        self.replay_timer.timeout.connect(self._replay_tick)
        self.price.getViewBox().sigRangeChanged.connect(self._on_range_changed)
        self.price.getViewBox().sigRangeChanged.connect(self._apply_lod)        # Smart Layers pe zoom
        self.price.getViewBox().sigRangeChanged.connect(self._apply_vp_scope)   # VP Visible pe zoom

        # Scurtaturi backtesting (stil TradingView): sageti = pas lumanare, spatiu = play/pauza
        for keys, fn in [
            (QtCore.Qt.Key_Right, lambda: self._step_bars(+1)),
            (QtCore.Qt.Key_Left, lambda: self._step_bars(-1)),
            (QtCore.Qt.Key_Space, self._toggle_play_key),
            (QtCore.Qt.Key_Escape, lambda: self.draw_mgr.cancel()),
            (QtCore.Qt.Key_Delete, lambda: self.draw_mgr.undo())]:
            sc = QtGui.QShortcut(QtGui.QKeySequence(keys), self)
            sc.setContext(QtCore.Qt.ApplicationShortcut)
            sc.activated.connect(fn)

        self._reload()

    # ---------- helperi UI ----------
    @staticmethod
    def _sep():
        line = QtWidgets.QFrame(); line.setObjectName("Sep")
        line.setFrameShape(QtWidgets.QFrame.VLine)
        return line

    @staticmethod
    def _field(label, widget):
        """Un control cu eticheta mica deasupra (compact, aliniat)."""
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(1)
        lab = QtWidgets.QLabel(label); lab.setObjectName("FieldLabel")
        v.addWidget(lab); v.addWidget(widget)
        return box

    # ---------- UI de sus (ce DATE afisezi) ----------
    def _build_topbar(self):
        bar = QtWidgets.QWidget(); bar.setObjectName("TopBar")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(16, 5, 16, 5); lay.setSpacing(12)

        title = QtWidgets.QLabel("Volume Profile Terminal"); title.setObjectName("Title")
        lay.addWidget(title)
        lay.addWidget(self._sep())

        self.cbo_day = QtWidgets.QComboBox()
        for f in discover_files():
            self.cbo_day.addItem(nice_label(f), userData=f)
        # Session Browser + Compare: a doua sesiune de suprapus (profil + niveluri)
        self.cbo_compare = QtWidgets.QComboBox()
        self.cbo_compare.addItem("— fara —", userData=None)
        for f in discover_files():
            self.cbo_compare.addItem(nice_label(f), userData=f)
        self.cbo_type = QtWidgets.QComboBox(); self.cbo_type.addItems(["Profil", "Footprint"])
        # Vederi (preset-uri de straturi) - un click = un set curat, gandit
        self.cbo_view = QtWidgets.QComboBox()
        self.cbo_view.addItems(["Vedere ▾", "Curat", "Order Flow", "NY Open", "Tot"])
        self.cbo_view.setToolTip("Aprinde un set gandit de straturi (in loc de 15 bife):\n"
                                 "Curat · Order Flow · NY Open (strategia ta) · Tot")
        self.cbo_interval = QtWidgets.QComboBox()
        self.cbo_interval.addItems(list(INTERVAL_SECONDS.keys()))
        self.cbo_interval.setCurrentText("5min")
        self.cbo_tz = QtWidgets.QComboBox()
        self.cbo_tz.addItems([name for (name, _, _) in TZ_OPTIONS])
        self.cbo_tz.setCurrentText("Romania")   # implicit: ora ta (16:30 = deschidere NY)

        # --- Controale VP: traiesc in panoul ⚙, nu in bara (structura DeepCharts) ---
        self.cbo_period = QtWidgets.QComboBox()
        self.cbo_period.addItems(["Sesiune", "Zi UTC", "Composite (saptamana)",
                                  "Composite 15 zile", "Composite 90 zile (bias)",
                                  "Visible (ce vezi)", "Custom range (trage)"])
        self.cbo_va = QtWidgets.QComboBox()
        self.cbo_va.addItems(["60", "68", "70", "80", "90"]); self.cbo_va.setCurrentText("70")
        self.cbo_res = QtWidgets.QComboBox()
        self.cbo_res.addItems(["0.25", "0.5", "1.0", "2.0", "3.0", "5.0"]); self.cbo_res.setCurrentText("2.0")

        self.chk_auto = QtWidgets.QCheckBox("Auto"); self.chk_auto.setChecked(True)
        self.chk_auto.setToolTip("Smart Layers: afiseaza automat straturile dupa zoom\n"
                                 "(zoom out = curat; zoom in = Big Trades/Absorption/Footprint)")
        self.chk_vp = QtWidgets.QCheckBox("VP"); self.chk_vp.setChecked(True)
        self.chk_vp.setToolTip("Overlay Volume Profile (merge si peste Footprint)")
        def _gear(tip):
            b = QtWidgets.QToolButton(); b.setText("⚙"); b.setObjectName("GearBtn"); b.setToolTip(tip)
            return b
        self.btn_vp_settings = _gear("Setari Volume Profile (perioada, grupare, VA%)")
        self.btn_bt_settings = _gear("Setari Big Trades (prag minim contracte)")
        self.btn_abs_settings = _gear("Setari Absorption (praguri)")
        self.btn_exh_settings = _gear("Setari Exhaustion (fereastra, climax, delta)")
        self.btn_fp_settings = _gear("Setari Footprint (imbalance)")
        self.chk_nodes = QtWidgets.QCheckBox("HVN/LVN"); self.chk_nodes.setChecked(True)
        self.chk_vwap = QtWidgets.QCheckBox("VWAP"); self.chk_vwap.setChecked(True)
        self.chk_vwap.setToolTip("VWAP developing (curba portocalie): pretul mediu al sesiunii ponderat cu volumul")
        self.chk_big = QtWidgets.QCheckBox("Big Trades"); self.chk_big.setChecked(True)
        self.chk_abs = QtWidgets.QCheckBox("Absorption"); self.chk_abs.setChecked(True)
        self.chk_exh = QtWidgets.QCheckBox("Exhaustion"); self.chk_exh.setChecked(True)
        self.chk_exh.setToolTip("Climax de volum + delta la o extrema noua (ultimul impuls, potential reversal)")
        self.chk_prior = QtWidgets.QCheckBox("Ieri"); self.chk_prior.setChecked(True)
        self.chk_prior.setToolTip("Nivelurile sesiunii precedente: yPOC / yVAH / yVAL + PDH / PDL")
        self.chk_session = QtWidgets.QCheckBox("RTH"); self.chk_session.setChecked(True)
        self.chk_session.setToolTip("Umbreste overnight (Globex) -> sesiunea NY (RTH 16:30 RO / 09:30 ET) iese in evidenta")
        self.chk_sess = QtWidgets.QCheckBox("Sesiuni"); self.chk_sess.setChecked(False)
        self.chk_sess.setToolTip("Volume Profile SEPARAT pe Asia / Londra / NY (VAH/VAL + LVN per sesiune)")
        self.btn_sess_settings = _gear("Setari Sesiuni (mod definire: fus real / ore RO + ore editabile)")
        self.chk_dev = QtWidgets.QCheckBox("Dev"); self.chk_dev.setChecked(False)
        self.chk_dev.setToolTip("Developing POC / Value Area: cum a migrat valoarea in timp (trail per lumanare, se dezvolta in replay)")
        self.chk_grid = QtWidgets.QCheckBox("Grid"); self.chk_grid.setChecked(True)
        self.chk_grid.setToolTip("Grid de statistici jos: ΣV (volum) / ΔV (delta) / Δ% per lumanare, colorat heatmap")
        self.chk_cvd = QtWidgets.QCheckBox("CVD"); self.chk_cvd.setChecked(True)
        self.chk_cvd.setToolTip("Panoul Cumulative Delta (jos): presiunea neta agresiva de-a lungul sesiunii")

        # ZIUA + buton "deschide fisier de ORIUNDE" (CSV/Parquet, ex. direct de pe Desktop)
        self.btn_open = QtWidgets.QToolButton(); self.btn_open.setText("📂")
        self.btn_open.setObjectName("GearBtn")
        self.btn_open.setToolTip("Deschide un fișier de date de ORIUNDE (CSV / Parquet) —\n"
                                 "ex. direct de pe Desktop, fără conversie sau git")
        self.btn_open.clicked.connect(self._open_data_file)
        daybox = QtWidgets.QWidget(); dv = QtWidgets.QVBoxLayout(daybox)
        dv.setContentsMargins(0, 0, 0, 0); dv.setSpacing(1)
        dl = QtWidgets.QLabel("ZIUA"); dl.setObjectName("FieldLabel"); dv.addWidget(dl)
        drow = QtWidgets.QHBoxLayout(); drow.setContentsMargins(0, 0, 0, 0); drow.setSpacing(4)
        drow.addWidget(self.cbo_day); drow.addWidget(self.btn_open)
        dv.addLayout(drow); lay.addWidget(daybox)
        lay.addWidget(self._sep())
        # Tip + ⚙ footprint
        tipbox = QtWidgets.QWidget(); tv = QtWidgets.QVBoxLayout(tipbox)
        tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(1)
        tl = QtWidgets.QLabel("Tip"); tl.setObjectName("FieldLabel"); tv.addWidget(tl)
        trow = QtWidgets.QHBoxLayout(); trow.setContentsMargins(0, 0, 0, 0); trow.setSpacing(4)
        trow.addWidget(self.cbo_type); trow.addWidget(self.btn_fp_settings)
        tv.addLayout(trow); lay.addWidget(tipbox)
        lay.addWidget(self._field("Interval", self.cbo_interval))
        lay.addWidget(self._field("Fus", self.cbo_tz))
        # (Straturile s-au mutat in bara de jos - _build_layerbar)

        lay.addStretch(1)
        self.lbl_warn = QtWidgets.QLabel(""); self.lbl_warn.setObjectName("WarnLabel")
        lay.addWidget(self.lbl_warn)

        self.cbo_day.currentIndexChanged.connect(self._reload)
        self.cbo_period.currentIndexChanged.connect(self._reload)            # schimba contextul de date
        self.cbo_interval.currentIndexChanged.connect(self._reload_keep)     # pastreaza pozitia+zoom
        self.cbo_va.currentIndexChanged.connect(self._reload_keep)
        self.cbo_res.currentIndexChanged.connect(self._reload_keep)
        self.cbo_type.currentIndexChanged.connect(self._rerender_current)    # Profil/Footprint = doar vizual
        self.cbo_view.currentIndexChanged.connect(self._on_view_changed)     # preset-uri de straturi
        self.chk_nodes.stateChanged.connect(self._rerender_current)
        self.chk_vp.stateChanged.connect(self._rerender_current)
        self.chk_auto.stateChanged.connect(self._apply_lod)
        self.chk_big.stateChanged.connect(self._apply_lod)
        self.chk_abs.stateChanged.connect(self._apply_lod)
        self.chk_exh.stateChanged.connect(self._apply_lod)
        self.chk_prior.stateChanged.connect(self._update_prior_visibility)
        self.chk_session.stateChanged.connect(self._update_session_shading)
        self.chk_sess.stateChanged.connect(self._on_sess_toggled)
        self.btn_sess_settings.clicked.connect(self._open_sess_settings)
        self.chk_dev.stateChanged.connect(self._rerender_current)
        self.chk_grid.stateChanged.connect(self._on_grid_toggled)
        self.chk_cvd.stateChanged.connect(self._on_cvd_toggled)
        self.chk_vwap.stateChanged.connect(lambda: self.vwap_curve.setVisible(self.chk_vwap.isChecked()))
        self.cbo_compare.currentIndexChanged.connect(self._on_compare_changed)
        self.cbo_tz.currentIndexChanged.connect(self._on_tz_changed)
        self.btn_vp_settings.clicked.connect(self._open_vp_settings)
        self.btn_bt_settings.clicked.connect(self._open_bt_settings)
        self.btn_abs_settings.clicked.connect(self._open_abs_settings)
        self.btn_exh_settings.clicked.connect(self._open_exh_settings)
        self.btn_fp_settings.clicked.connect(self._open_fp_settings)
        return bar

    def _open_vp_settings(self):
        """Panou ⚙ pentru Volume Profile: perioada, grupare, VA% (non-modal)."""
        if getattr(self, "_vp_dialog", None) is None:
            dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Volume Profile — setari")
            dlg.setObjectName("VPDialog")
            form = QtWidgets.QFormLayout(dlg)
            form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
            form.addRow("Perioada", self.cbo_period)
            form.addRow("Grupare (rezolutie)", self.cbo_res)
            form.addRow("Value Area %", self.cbo_va)
            self.cbo_vp_color = QtWidgets.QComboBox()
            self.cbo_vp_color.addItems(["Simplu (VA evidentiata)", "Buy / Sell"])
            self.cbo_vp_color.setCurrentIndex(0 if self.profile_item.mode == "single" else 1)
            self.cbo_vp_color.currentIndexChanged.connect(self._on_vp_color_changed)
            form.addRow("Culoare profil", self.cbo_vp_color)
            self.chk_lvn_full = QtWidgets.QCheckBox("LVN pe tot profilul")
            self.chk_lvn_full.setChecked(self._lvn_full)
            self.chk_lvn_full.setToolTip(
                "Detecteaza LVN pe TOT profilul (inclusiv spre margini = discount/premium),\n"
                "nu doar vaile dintre HVN-uri. Zone unde pretul NU a stat.")
            self.chk_lvn_full.stateChanged.connect(self._on_lvn_full_changed)
            form.addRow(self.chk_lvn_full)
            hint = QtWidgets.QLabel("Visible = profilul se recalculeaza doar pe ce vezi pe ecran.")
            hint.setObjectName("FieldLabel"); hint.setWordWrap(True)
            form.addRow(hint)
            self._vp_dialog = dlg
        self._vp_dialog.show(); self._vp_dialog.raise_()

    def _on_vp_color_changed(self, idx):
        """Comuta profilul VP intre 'simplu' (o culoare + VA evidentiata) si 'buy/sell'."""
        self.profile_item.set_mode("single" if idx == 0 else "split")

    def _on_lvn_full_changed(self, *a):
        """Toggle LVN pe tot profilul (nu doar intre HVN-uri) -> reload cu pozitia pastrata."""
        self._lvn_full = self.chk_lvn_full.isChecked()
        self._reload_keep()

    def _open_bt_settings(self):
        """Panou ⚙ Big Trades: pragul minim de contracte."""
        if self._bt_dialog is None:
            dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Big Trades — setari")
            dlg.setObjectName("VPDialog")
            form = QtWidgets.QFormLayout(dlg); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
            sp = QtWidgets.QSpinBox(); sp.setRange(1, 5000); sp.setSingleStep(5); sp.setValue(self._big_min)
            self._bt_min_spin = sp
            form.addRow("Prag minim (contracte)", sp)
            self._bt_zone_chk = QtWidgets.QCheckBox("Zone S/R (cele mai mari tranzactii)")
            self._bt_zone_chk.setChecked(self._bt_zones)
            form.addRow(self._bt_zone_chk)
            hint = QtWidgets.QLabel("Pe NQ tranzactiile single sunt mici; 25–100 e uzual.")
            hint.setObjectName("FieldLabel"); hint.setWordWrap(True); form.addRow(hint)
            sp.valueChanged.connect(self._on_bt_min_changed)
            self._bt_zone_chk.stateChanged.connect(self._on_bt_zones_changed)
            self._bt_dialog = dlg
        self._bt_dialog.show(); self._bt_dialog.raise_()

    def _on_bt_min_changed(self, v):
        self._big_min = int(v)
        self._reload_keep()

    def _on_bt_zones_changed(self, *a):
        self._bt_zones = self._bt_zone_chk.isChecked()
        self._rerender_current()

    def _set_bt_zones(self, big_trades):
        """Zone S/R orizontale la cele mai mari tranzactii (verde=buy / mov=sell)."""
        for ln in self.bt_zone_lines:
            self.price.removeItem(ln)
        self.bt_zone_lines = []
        if not (self._bt_zones and self.chk_big.isChecked()) or not big_trades:
            return
        top = sorted(big_trades, key=lambda b: b[2], reverse=True)[:8]   # cele mai mari 8
        for ep, price, size, side in top:
            col = QtGui.QColor(theme.UP if side == "B" else theme.DOWN); col.setAlpha(120)
            ln = pg.InfiniteLine(pos=price, angle=0, movable=False,
                                 pen=pg.mkPen(col, width=1, style=QtCore.Qt.DashLine))
            ln.setZValue(-2); self.price.addItem(ln); self.bt_zone_lines.append(ln)

    def _open_abs_settings(self):
        """Panou ⚙ Absorption: praguri (volum minim, dominanta, respingere)."""
        if self._abs_dialog is None:
            dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Absorption — setari")
            dlg.setObjectName("VPDialog")
            form = QtWidgets.QFormLayout(dlg); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
            self._abs_v = QtWidgets.QSpinBox(); self._abs_v.setRange(1, 5000); self._abs_v.setSingleStep(10)
            self._abs_v.setValue(int(self._abs_params.get("min_vol", ABS_MIN_VOL)))
            self._abs_dom = QtWidgets.QDoubleSpinBox(); self._abs_dom.setRange(1.0, 5.0)
            self._abs_dom.setSingleStep(0.1); self._abs_dom.setValue(self._abs_params.get("dom", ABS_DOM))
            self._abs_rej = QtWidgets.QSpinBox(); self._abs_rej.setRange(0, 100); self._abs_rej.setSuffix(" %")
            self._abs_rej.setValue(int(self._abs_params.get("reject", ABS_REJECT) * 100))
            form.addRow("Volum minim (zona)", self._abs_v)
            form.addRow("Dominanta agresor (x)", self._abs_dom)
            form.addRow("Respingere (inchidere)", self._abs_rej)
            for w in (self._abs_v, self._abs_dom, self._abs_rej):
                w.valueChanged.connect(self._on_abs_changed)
            self._abs_dialog = dlg
        self._abs_dialog.show(); self._abs_dialog.raise_()

    def _on_abs_changed(self, *a):
        self._abs_params = {"min_vol": int(self._abs_v.value()),
                            "dom": float(self._abs_dom.value()),
                            "reject": self._abs_rej.value() / 100.0}
        self._reload_keep()

    def _open_exh_settings(self):
        """Panou ⚙ Exhaustion: fereastra, multiplu de climax, fractie delta."""
        if self._exh_dialog is None:
            dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Exhaustion — setari")
            dlg.setObjectName("VPDialog")
            form = QtWidgets.QFormLayout(dlg); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
            self._exh_win = QtWidgets.QSpinBox(); self._exh_win.setRange(3, 60)
            self._exh_win.setValue(int(self._exh_params.get("window", EXH_WINDOW)))
            self._exh_mult = QtWidgets.QDoubleSpinBox(); self._exh_mult.setRange(1.0, 6.0)
            self._exh_mult.setSingleStep(0.25); self._exh_mult.setValue(self._exh_params.get("vol_mult", EXH_VOL_MULT))
            self._exh_df = QtWidgets.QSpinBox(); self._exh_df.setRange(0, 100); self._exh_df.setSuffix(" %")
            self._exh_df.setValue(int(self._exh_params.get("delta_frac", EXH_DELTA_FRAC) * 100))
            form.addRow("Fereastra (lumanari)", self._exh_win)
            form.addRow("Climax volum (x mediana)", self._exh_mult)
            form.addRow("Delta minima (% din volum)", self._exh_df)
            hint = QtWidgets.QLabel("Climax de volum + delta la o EXTREMA NOUA = ultimul impuls "
                                    "(cumparatori/vanzatori epuizati, posibil reversal).")
            hint.setObjectName("FieldLabel"); hint.setWordWrap(True); form.addRow(hint)
            for w in (self._exh_win, self._exh_mult, self._exh_df):
                w.valueChanged.connect(self._on_exh_changed)
            self._exh_dialog = dlg
        self._exh_dialog.show(); self._exh_dialog.raise_()

    def _on_exh_changed(self, *a):
        self._exh_params = {"window": int(self._exh_win.value()),
                            "vol_mult": float(self._exh_mult.value()),
                            "delta_frac": self._exh_df.value() / 100.0}
        self._reload_keep()

    def _build_layerbar(self):
        """Bara de straturi jos (stil DeepCharts): toggle-uri curate pe grupuri +
        ⚙ per tool, in loc de checkbox-uri imprastiate in topbar."""
        bar = QtWidgets.QWidget(); bar.setObjectName("LayerBar")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(10, 4, 10, 4); lay.setSpacing(8)
        vlbl = QtWidgets.QLabel("VEDERE"); vlbl.setObjectName("FieldLabel")
        lay.addWidget(vlbl); lay.addWidget(self.cbo_view)
        lay.addWidget(self._sep())
        lbl = QtWidgets.QLabel("STRATURI"); lbl.setObjectName("FieldLabel")
        lay.addWidget(lbl)
        lay.addWidget(self.chk_auto)                                   # Smart Layers
        lay.addWidget(self._sep())
        lay.addWidget(self.chk_vp); lay.addWidget(self.btn_vp_settings)   # Volume Profile
        lay.addWidget(self.chk_nodes)
        lay.addWidget(self.chk_vwap)
        lay.addWidget(self.chk_dev)
        lay.addWidget(self._sep())
        lay.addWidget(self.chk_big); lay.addWidget(self.btn_bt_settings)  # Order flow
        lay.addWidget(self.chk_abs); lay.addWidget(self.btn_abs_settings)
        lay.addWidget(self.chk_exh); lay.addWidget(self.btn_exh_settings)
        lay.addWidget(self.chk_grid)
        lay.addWidget(self.chk_cvd)
        lay.addWidget(self._sep())
        lay.addWidget(self.chk_prior)                                  # Context / sesiune
        lay.addWidget(self.chk_session)
        lay.addWidget(self.chk_sess); lay.addWidget(self.btn_sess_settings)
        lay.addStretch(1)
        # Session Browser + Compare (dreapta)
        cl = QtWidgets.QLabel("Compară:"); cl.setObjectName("FieldLabel")
        lay.addWidget(cl); lay.addWidget(self.cbo_compare)
        return bar

    def _open_fp_settings(self):
        """Panou ⚙ Footprint: pragul de imbalance (nu cere reload - doar re-paint)."""
        if self._fp_dialog is None:
            dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Footprint — setari")
            dlg.setObjectName("VPDialog")
            form = QtWidgets.QFormLayout(dlg); form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
            self._fp_ratio = QtWidgets.QDoubleSpinBox(); self._fp_ratio.setRange(1.0, 10.0)
            self._fp_ratio.setSingleStep(0.5); self._fp_ratio.setValue(self.footprint_item._imb_ratio)
            self._fp_minvol = QtWidgets.QSpinBox(); self._fp_minvol.setRange(0, 1000)
            self._fp_minvol.setValue(self.footprint_item._imb_minvol)
            self._fp_mode = QtWidgets.QComboBox()
            self._fp_mode.addItems(["Bid x Ask (bare)", "Volume", "Delta"])
            self._fp_mode.setCurrentIndex({"bidask": 0, "volume": 1, "delta": 2}
                                          .get(self.footprint_item._mode, 0))
            self._fp_shape = QtWidgets.QComboBox()
            self._fp_shape.addItems(["Căsuțe", "Bule (stil DeepChart)"])
            self._fp_shape.setCurrentIndex(1 if self.footprint_item._shape == "bubbles" else 0)
            form.addRow("Stil", self._fp_shape)
            form.addRow("Mod", self._fp_mode)
            form.addRow("Imbalance ratio (x)", self._fp_ratio)
            form.addRow("Volum minim celula", self._fp_minvol)
            hint = QtWidgets.QLabel("Stil: Căsuțe (sell×buy) sau Bule (o pastilă/nivel, volumul total, "
                                    "verde buy / mov sell). Bid×Ask/Volume/Delta = cum se coloreaza.")
            hint.setObjectName("FieldLabel"); hint.setWordWrap(True); form.addRow(hint)
            for w in (self._fp_ratio, self._fp_minvol):
                w.valueChanged.connect(self._on_fp_changed)
            self._fp_mode.currentIndexChanged.connect(self._on_fp_mode_changed)
            self._fp_shape.currentIndexChanged.connect(self._on_fp_shape_changed)
            self._fp_dialog = dlg
        self._fp_dialog.show(); self._fp_dialog.raise_()

    def _on_fp_changed(self, *a):
        self.footprint_item._imb_ratio = float(self._fp_ratio.value())
        self.footprint_item._imb_minvol = int(self._fp_minvol.value())
        self.footprint_item.update()   # re-paint (imbalance re-evaluat), fara reload

    def _on_fp_mode_changed(self, idx):
        self.footprint_item.set_mode(["bidask", "volume", "delta"][idx])

    def _on_fp_shape_changed(self, idx):
        self.footprint_item.set_shape("bubbles" if idx == 1 else "cells")

    def _on_view_changed(self, idx):
        """Preset de straturi: idx 0 = placeholder (nu face nimic)."""
        if idx <= 0:
            return
        self._apply_view(self.cbo_view.currentText())

    def _apply_view(self, name):
        """Aprinde setul de straturi al unei Vederi (Curat / Order Flow / NY Open / Tot)."""
        v = VIEWS.get(name)
        if not v:
            return
        self.cbo_type.setCurrentText(v["type"])
        for chk, key in ((self.chk_auto, "auto"), (self.chk_vp, "vp"), (self.chk_nodes, "nodes"),
                         (self.chk_vwap, "vwap"), (self.chk_dev, "dev"), (self.chk_big, "big"),
                         (self.chk_abs, "abs"), (self.chk_exh, "exh"), (self.chk_grid, "grid"),
                         (self.chk_cvd, "cvd"), (self.chk_prior, "prior"),
                         (self.chk_session, "session"), (self.chk_sess, "sess")):
            chk.setChecked(v[key])

    def _open_data_file(self):
        """Deschide un fisier de date de ORIUNDE (CSV / Parquet) - ex. direct de pe Desktop -
        fara conversie sau git. Il adauga in lista ZIUA si il selecteaza -> se incarca pe loc.
        (CSV se citeste direct; e putin mai lent decat parquet, dar merge instant.)"""
        start = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Deschide fișier de date (CSV / Parquet)", start,
            "Date Databento (*.parquet *.csv);;Toate fișierele (*.*)")
        if not path:
            return
        path = os.path.normpath(path)
        for i in range(self.cbo_day.count()):
            if self.cbo_day.itemData(i) == path:
                self.cbo_day.setCurrentIndex(i)          # deja deschis -> doar selecteaza
                return
        self.cbo_day.addItem("📂 " + nice_label(os.path.basename(path)), userData=path)
        self.cbo_day.setCurrentIndex(self.cbo_day.count() - 1)   # -> declanseaza _reload

    def _build_stats(self):
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(wrap)
        lay.setContentsMargins(16, 4, 16, 4); lay.setSpacing(10)
        self.card_symbol = StatCard("Simbol")
        self.card_poc = StatCard("POC")
        self.card_va = StatCard("VAH / VAL")
        self.card_vol = StatCard("Volum total")
        self.card_delta = StatCard("CVD")
        for c in (self.card_symbol, self.card_poc, self.card_va, self.card_vol, self.card_delta):
            lay.addWidget(c)
        lay.addStretch(1)
        return wrap

    # ---------- Bara de jos: playback + backtesting (replay) ----------
    def _build_replaybar(self):
        bar = QtWidgets.QWidget(); bar.setObjectName("ReplayBar")
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(16, 6, 16, 6); lay.setSpacing(8)

        # Comutatorul Replay - mereu activ (de aici intri/iesi din replay)
        self.btn_replay = QtWidgets.QPushButton("● Replay")
        self.btn_replay.setCheckable(True); self.btn_replay.setObjectName("ReplayToggle")
        lay.addWidget(self.btn_replay)
        lay.addWidget(self._sep())

        # Restul controalelor - active DOAR in replay
        ctrl = QtWidgets.QWidget()
        cl = QtWidgets.QHBoxLayout(ctrl); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(8)
        self.btn_play = QtWidgets.QPushButton("▶"); self.btn_play.setCheckable(True); self.btn_play.setMaximumWidth(40)
        self.cbo_speed = QtWidgets.QComboBox()
        self.cbo_speed.addItems(["lent", "1x", "2x", "5x", "10x"]); self.cbo_speed.setCurrentText("1x")
        self.btn_follow = QtWidgets.QPushButton("Follow"); self.btn_follow.setCheckable(True)
        self.btn_follow.setChecked(True); self.btn_follow.setMaximumWidth(64)
        self.btn_first = QtWidgets.QPushButton("⏮"); self.btn_first.setMaximumWidth(32)
        self.btn_step_back = QtWidgets.QPushButton("◀ Bar"); self.btn_step_back.setMaximumWidth(64)
        self.btn_step_fwd = QtWidgets.QPushButton("Bar ▶"); self.btn_step_fwd.setMaximumWidth(64)
        self.btn_last = QtWidgets.QPushButton("⏭"); self.btn_last.setMaximumWidth(32)
        self.scrubber = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.scrubber.setRange(0, 0)
        self.lbl_pos = QtWidgets.QLabel("—"); self.lbl_pos.setObjectName("ReplayPos"); self.lbl_pos.setMinimumWidth(180)
        self.jump_edit = QtWidgets.QLineEdit(); self.jump_edit.setPlaceholderText("HH:MM"); self.jump_edit.setMaximumWidth(62)
        self.btn_jump = QtWidgets.QPushButton("Sari"); self.btn_jump.setMaximumWidth(48)

        cl.addWidget(self.btn_play); cl.addWidget(self.cbo_speed); cl.addWidget(self.btn_follow)
        cl.addWidget(self._sep())
        cl.addWidget(self.btn_first); cl.addWidget(self.btn_step_back)
        cl.addWidget(self.btn_step_fwd); cl.addWidget(self.btn_last)
        cl.addWidget(self.scrubber, stretch=1)
        cl.addWidget(self.lbl_pos)
        cl.addWidget(QtWidgets.QLabel("Sari la")); cl.addWidget(self.jump_edit); cl.addWidget(self.btn_jump)
        self._replay_controls = ctrl
        ctrl.setEnabled(False)
        lay.addWidget(ctrl, stretch=1)

        self.replay_bar = bar

        self.btn_replay.toggled.connect(self._on_replay_toggled)
        self.btn_play.toggled.connect(self._on_play_toggled)
        self.cbo_speed.currentIndexChanged.connect(self._on_speed_changed)
        self.btn_follow.toggled.connect(self._on_follow_toggled)
        self.btn_first.clicked.connect(lambda: self._seek_to(0))
        self.btn_last.clicked.connect(lambda: self._seek_to(10**9))
        self.btn_step_back.clicked.connect(lambda: self._step_bars(-1))
        self.btn_step_fwd.clicked.connect(lambda: self._step_bars(+1))
        self.scrubber.valueChanged.connect(self._on_scrub)
        self.btn_jump.clicked.connect(self._on_jump)
        self.jump_edit.returnPressed.connect(self._on_jump)
        return bar

    # ---------- Grafice ----------
    def _build_charts(self):
        pg.setConfigOptions(antialias=True)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(theme.BG)

        # Pret pe row 0 (profilul e OVERLAY peste el); panou CVD pe row 1 sub el.
        # Axa de pret e PriceAxis: trage de ea (left-drag) ca sa comprimi/extinzi scala.
        self.price = self.glw.addPlot(row=0, col=0,
                                      axisItems={"right": PriceAxis(orientation="right")})
        self.price.showGrid(x=True, y=True, alpha=0.05)
        self.price.showAxis("right"); self.price.hideAxis("left"); self.price.hideAxis("bottom")
        pa = self.price.getAxis("right")
        pa.setTextPen(theme.TEXT_DIM); pa.setPen(pg.mkPen(theme.BORDER, width=1)); pa.setStyle(tickLength=-4)
        # Butonul "A" (auto-range) al pyqtgraph fita TOATE item-ele (inclusiv overlay-uri cu
        # margini degenerate spre 0) -> vederea sarea la epoca 0. Butonul e pe PlotItem
        # (self.price.autoBtn); il reconectam sa fiteze DOAR pe lumanari (datele reale).
        try:
            self.price.autoBtn.clicked.disconnect()
        except Exception:
            pass
        try:
            self.price.autoBtn.clicked.connect(self._fit_candles)
        except Exception:
            pass

        # Panou CVD (Cumulative Delta) sub pret (row 1). Axa de timp comuna e MUTATA
        # pe grid-ul de statistici (row 2, cel mai de jos).
        self.time_axis = UTCDateAxis(orientation="bottom")
        self.time_axis.tz_offset = 0
        self.cvd_plot = self.glw.addPlot(row=1, col=0)
        self.cvd_plot.setXLink(self.price)
        self.cvd_plot.showGrid(x=True, y=True, alpha=0.05)
        self.cvd_plot.showAxis("right"); self.cvd_plot.hideAxis("left"); self.cvd_plot.hideAxis("bottom")
        self.cvd_plot.setMouseEnabled(y=False)
        self.cvd_plot.getViewBox().setMenuEnabled(False)
        self.cvd_plot.setAutoVisible(y=True)
        self.cvd_plot.enableAutoRange(axis="y", enable=True)
        a = self.cvd_plot.getAxis("right")
        a.setTextPen(theme.TEXT_DIM); a.setPen(pg.mkPen(theme.BORDER, width=1)); a.setStyle(tickLength=-4)

        # Grid de statistici per lumanare (row 2): ΣV / ΔV / Δ% heatmap. Poarta axa de timp.
        self.grid_plot = self.glw.addPlot(row=2, col=0,
                                          axisItems={"bottom": self.time_axis,
                                                     "left": StatsAxis(orientation="left")})
        self.grid_plot.setXLink(self.price)
        self.grid_plot.hideAxis("right")
        self.grid_plot.setMouseEnabled(x=False, y=False)
        self.grid_plot.getViewBox().setMenuEnabled(False)
        self.grid_plot.setYRange(0, 4, padding=0)
        gl = self.grid_plot.getAxis("left")
        gl.setTextPen(theme.TEXT_DIM); gl.setPen(pg.mkPen(theme.BORDER, width=1)); gl.setWidth(34)
        gb = self.grid_plot.getAxis("bottom")
        gb.setTextPen(theme.TEXT_DIM); gb.setPen(pg.mkPen(theme.BORDER, width=1)); gb.setStyle(tickLength=-4)
        self.grid_stats = GridStatsItem()
        self.grid_plot.addItem(self.grid_stats)
        self.grid_stats.attach(self.grid_plot.getViewBox())

        self.glw.ci.layout.setRowStretchFactor(0, 5)
        self.glw.ci.layout.setRowStretchFactor(1, 1)
        self.glw.ci.layout.setRowStretchFactor(2, 1)
        self.cvd_zero = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(theme.BORDER, width=1))
        self.cvd_plot.addItem(self.cvd_zero)
        # CVD: umplere CONTINUA colorata pe semn (verde peste 0 / mov sub 0) + o singura
        # linie continua deasupra -> fara "gauri" la trecerea prin zero (arata curat).
        self.cvd_pos = pg.PlotDataItem(pen=pg.mkPen(None), fillLevel=0, brush=pg.mkBrush(46, 224, 138, 55))
        self.cvd_neg = pg.PlotDataItem(pen=pg.mkPen(None), fillLevel=0, brush=pg.mkBrush(176, 107, 247, 55))
        self.cvd_line = pg.PlotDataItem(pen=pg.mkPen(theme.TEXT_DIM, width=1.5))
        self.cvd_plot.addItem(self.cvd_pos)
        self.cvd_plot.addItem(self.cvd_neg)
        self.cvd_plot.addItem(self.cvd_line)
        self.cvd_plot.setLabel("right", "CVD", color=theme.TEXT_DIM)

        # Cutie Value Area (in spate)
        self.va_band = pg.LinearRegionItem(orientation="horizontal", movable=False,
                                           brush=pg.mkBrush(*theme.VA_BAND))
        self.va_band.setZValue(-10)
        self.price.addItem(self.va_band)
        # Value Area de IERI ca ZONA (box amber discret) - reper de suport/rezistenta la NY open.
        # Vizibila cu toggle-ul "Ieri", intre yVAL si yVAH.
        self.prior_va_band = pg.LinearRegionItem(orientation="horizontal", movable=False,
                                                 brush=pg.mkBrush(*theme.PRIOR_VA_BAND))
        self.prior_va_band.setZValue(-11)
        self.prior_va_band.setVisible(False)
        self.price.addItem(self.prior_va_band)
        # Session shading: 2 benzi verticale peste OVERNIGHT (inainte/dupa RTH) -> RTH-ul (NY) iese in evidenta
        self._session_bands = []
        for _ in range(2):
            b = pg.LinearRegionItem(orientation="vertical", movable=False,
                                    brush=pg.mkBrush(*theme.SESSION_SHADE), pen=pg.mkPen(None))
            b.setZValue(-12); b.setVisible(False)
            self.price.addItem(b)
            self._session_bands.append(b)

        # Zona CUSTOM (VP pe interval tras): regiune verticala trasabila de margini
        self.custom_region = pg.LinearRegionItem(orientation="vertical", movable=True,
                                                 brush=pg.mkBrush(255, 157, 46, 24))
        self.custom_region.setZValue(-9)
        self.custom_region.setVisible(False)
        self.price.addItem(self.custom_region)
        self.custom_region.sigRegionChanged.connect(self._on_custom_region)

        # Profil OVERLAY - suprapus peste pret, ancorat stanga, translucid
        self.profile_item = ProfileOverlayItem(width_frac=0.22)
        self.profile_item.setZValue(-5)
        self.price.addItem(self.profile_item)
        self.profile_item.attach(self.price.getViewBox())

        # COMPARE: profilul unei alte sesiuni, ancorat pe DREAPTA, culoare albastra distincta
        self.cmp_profile = ProfileOverlayItem(width_frac=0.16, mode="single",
                                              anchor="right", tint=theme.CMP_RGB)
        self.cmp_profile.setZValue(-6)
        self.cmp_profile.setVisible(False)
        self.price.addItem(self.cmp_profile)
        self.cmp_profile.attach(self.price.getViewBox())
        # Nivelurile sesiunii de comparat (cPOC/cVAH/cVAL), etichete pe dreapta, albastru
        self.cmp_lines = {}
        for key, lbl, wdt in (("poc", "cPOC", 2), ("vah", "cVAH", 1), ("val", "cVAL", 1)):
            ln = pg.InfiniteLine(angle=0, movable=False,
                                 pen=pg.mkPen(theme.CMP, width=wdt, style=QtCore.Qt.DashLine),
                                 label=lbl + " {value:.2f}",
                                 labelOpts={"position": 0.90, "color": "#04121e",
                                            "fill": pg.mkColor(theme.CMP), "movable": False})
            ln.setZValue(-2); ln.setVisible(False)
            self.price.addItem(ln); self.cmp_lines[key] = ln
        self._cmp_data = None

        # Lumanari (deasupra profilului)
        self.candles = CandlestickItem()
        self.price.addItem(self.candles)

        # Footprint - alternativa la lumanari (celule bid/ask colorate pe imbalance)
        self.footprint_item = FootprintItem()
        self.footprint_item.setZValue(-4)
        self.price.addItem(self.footprint_item)
        self.footprint_item.attach(self.price.getViewBox())

        # VWAP developing
        _vwap_c = QtGui.QColor(theme.VWAP); _vwap_c.setAlpha(200)   # context: putin mai stins ca semnalele sa iasa in fata
        self.vwap_curve = pg.PlotDataItem(pen=pg.mkPen(_vwap_c, width=1.5))
        self.price.addItem(self.vwap_curve)

        # Developing POC / Value Area: cum a MIGRAT valoarea in timp (trail per lumanare).
        # POC = magenta subtire; VAH/VAL = portocaliu dim punctat. Se dezvolta si in replay.
        dev_poc_c = QtGui.QColor(theme.POC); dev_poc_c.setAlpha(160)
        dev_va_c = QtGui.QColor(theme.VA_LINE); dev_va_c.setAlpha(110)
        self.dev_poc_curve = pg.PlotDataItem(pen=pg.mkPen(dev_poc_c, width=1.4))
        self.dev_vah_curve = pg.PlotDataItem(pen=pg.mkPen(dev_va_c, width=1, style=QtCore.Qt.DotLine))
        self.dev_val_curve = pg.PlotDataItem(pen=pg.mkPen(dev_va_c, width=1, style=QtCore.Qt.DotLine))
        for c in (self.dev_poc_curve, self.dev_vah_curve, self.dev_val_curve):
            c.setZValue(3); c.setVisible(False); self.price.addItem(c)

        # tooltip brut pyqtgraph (x/y/data) suprimat -> aratam doar cardul nostru (hover_card)
        _no_tip = lambda x, y, data: ""
        # Big Trades - bule la tranzactiile individuale mari (hover -> tooltip)
        self.big_scatter = pg.ScatterPlotItem(pen=pg.mkPen(None), hoverable=True,
                                              hoverSize=-1, hoverPen=pg.mkPen("#ffffff", width=2),
                                              tip=_no_tip)
        self.big_scatter.setZValue(6)
        self.big_scatter.sigHovered.connect(self._on_marker_hover)
        self.price.addItem(self.big_scatter)

        # Absorption - triunghi la extrema respinsa (bull la minim / bear la maxim); hover -> tooltip
        self.abs_scatter = pg.ScatterPlotItem(hoverable=True,
                                              hoverPen=pg.mkPen("#ffffff", width=2), tip=_no_tip)
        self.abs_scatter.setZValue(7)
        self.abs_scatter.sigHovered.connect(self._on_marker_hover)
        self.price.addItem(self.abs_scatter)

        # Exhaustion - romb la climaxul de la o extrema noua (top/bot); hover -> tooltip
        self.exh_scatter = pg.ScatterPlotItem(hoverable=True,
                                              hoverPen=pg.mkPen("#ffffff", width=2), tip=_no_tip)
        self.exh_scatter.setZValue(7)
        self.exh_scatter.sigHovered.connect(self._on_marker_hover)
        self.price.addItem(self.exh_scatter)

        # FIX: pyqtgraph 0.14 nu mai activeaza acceptHoverEvents din hoverable=True ->
        # sigHovered nu se declansa (tooltip-ul nu aparea). Il setam explicit (persista peste setData).
        for _sc in (self.big_scatter, self.abs_scatter, self.exh_scatter):
            _sc.setAcceptHoverEvents(True)

        # Card de tooltip la hover peste bule/markere (ascuns implicit)
        self.hover_card = pg.TextItem(color=theme.TEXT, anchor=(0, 1),
                                      fill=pg.mkBrush(20, 22, 30, 235),
                                      border=pg.mkPen(theme.BORDER))
        self.hover_card.setZValue(50)
        self.hover_card.setVisible(False)
        self.price.addItem(self.hover_card, ignoreBounds=True)

        # Linii POC / VA / ultim pret - pilule pe axa din dreapta
        def mk(color, width, dash, label=None, position=0.99):
            kw = dict(angle=0, movable=False,
                      pen=pg.mkPen(color, width=width, style=dash))
            if label:
                kw["label"] = label
                kw["labelOpts"] = {"position": position, "color": "#0a0a0a",
                                   "fill": pg.mkColor(color), "movable": False}
            ln = pg.InfiniteLine(**kw)
            self.price.addItem(ln)
            return ln

        # POC + ultimul pret = pastile pe marginea din dreapta (0.99); VAH/VAL putin
        # INSET (0.95) ca sa nu se stivuiasca peste POC/last cand preturile sunt apropiate.
        self.price_lines = {
            "poc": mk(theme.POC, 3, QtCore.Qt.SolidLine, "POC {value:.2f}"),   # cel mai gros = cel mai important
            "vah": mk(theme.VA_LINE, 1, QtCore.Qt.DashLine, "VAH {value:.2f}", position=0.95),
            "val": mk(theme.VA_LINE, 1, QtCore.Qt.DashLine, "VAL {value:.2f}", position=0.95),
        }
        self.last_line = mk(theme.TEXT_DIM, 1, QtCore.Qt.DashLine, "{value:.2f}")

        # Nivelurile SESIUNII PRECEDENTE (backtesting) - etichete pe STANGA (nu se bat cu cele curente)
        def mk_prior(color, width, dash, label):
            ln = pg.InfiniteLine(
                angle=0, movable=False, pen=pg.mkPen(color, width=width, style=dash),
                label=label, labelOpts={"position": 0.04, "color": "#0a0a0a",
                                        "fill": pg.mkColor(color), "movable": False})
            ln.setZValue(-2); ln.setVisible(False)
            self.price.addItem(ln)
            return ln

        self.prior_lines = {
            "poc": mk_prior(theme.PRIOR_POC, 2, QtCore.Qt.DashLine, "yPOC {value:.2f}"),
            "vah": mk_prior(theme.PRIOR_VA, 1, QtCore.Qt.DotLine, "yVAH {value:.2f}"),
            "val": mk_prior(theme.PRIOR_VA, 1, QtCore.Qt.DotLine, "yVAL {value:.2f}"),
            "high": mk_prior(theme.PRIOR_HL, 1, QtCore.Qt.DashLine, "PDH {value:.2f}"),
            "low": mk_prior(theme.PRIOR_HL, 1, QtCore.Qt.DashLine, "PDL {value:.2f}"),
        }
        self._prior = None

        self.node_lines = []  # HVN/LVN - recreate la fiecare reload
        self._sess_lines = []  # niveluri profile per-sesiune (Asia/Londra/NY) - recreate la reload
        self._hvn_prices = []  # preturile HVN/LVN curente (pt identificare la hover)
        self._lvn_prices = []
        self.bt_zone_lines = []  # zone S/R din Big Trades (optional)
        self._data = None     # ultima zi incarcata (pentru readout crosshair footprint)

        self._build_crosshair()

        # Unelte de desen (backtesting) + bara verticala de unelte in stanga graficului
        self.draw_mgr = DrawingManager(self.price)
        self.draw_mgr.on_tool_done = self._reset_draw_tool
        self.draw_mgr.snap_provider = self._snap_point   # magnet (Ctrl) -> lipit de OHLC
        self.draw_mgr.on_avwap = self._add_avwap_anchor  # aVWAP: click -> ancora
        self._avwap_anchors = []   # epoci ancore Anchored VWAP
        self._avwap_items = []     # itemele grafice curente (re-desenate la _render)
        wrap = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        h.addWidget(self._build_draw_toolbar())
        h.addWidget(self.glw, stretch=1)
        return wrap

    def _build_draw_toolbar(self):
        bar = QtWidgets.QWidget(); bar.setObjectName("DrawBar")
        lay = QtWidgets.QVBoxLayout(bar)
        lay.setContentsMargins(4, 8, 4, 8); lay.setSpacing(4)

        self.draw_group = QtWidgets.QButtonGroup(self)
        self.draw_group.setExclusive(True)
        tools = [("⤢", None, "<b>Cursor</b><br>Fără unealtă · pan · click pe lumânare = Bar Info"),
                 ("─", "hline", "<b>Nivel orizontal</b><br>1 click → linie mobilă la preț"),
                 ("╱", "trend", "<b>Trendline</b><br>2 clickuri → segment editabil (mânere)"),
                 ("▭", "rect", "<b>Dreptunghi / zonă</b><br>2 clickuri → cutie (supply/demand), mut + redimensionez"),
                 ("Fib", "fib", "<b>Fibonacci retracement</b><br>2 clickuri (swing) → nivelurile fib"),
                 ("↔", "measure", "<b>Măsură</b><br>2 clickuri → puncte / ticks / % / timp"),
                 ("L", "long", "<b>Long Position</b><br>1 click = Entry; Stop + Target apar automat și le TRAGI → R:R + $ live"),
                 ("S", "short", "<b>Short Position</b><br>1 click = Entry; Stop + Target apar automat și le TRAGI → R:R + $ live"),
                 ("aV", "avwap", "<b>Anchored VWAP</b><br>1 click = ancoră (ex. NY open) → VWAP + benzi std-dev de acolo")]
        self._tool_btns = {}
        for label, tool, tip in tools:
            b = QtWidgets.QPushButton(label)
            b.setCheckable(True); b.setToolTip(tip)
            b.setFixedSize(34, 30)
            b.clicked.connect(lambda _=False, t=tool: self.draw_mgr.set_tool(t))
            self.draw_group.addButton(b)
            self._tool_btns[tool] = b
            lay.addWidget(b)
        self._tool_btns[None].setChecked(True)   # cursor implicit

        lay.addSpacing(8)
        self.btn_undo = QtWidgets.QPushButton("↶"); self.btn_undo.setFixedSize(34, 30)
        self.btn_undo.setToolTip("Undo (scoate ultimul desen)")
        self.btn_clear = QtWidgets.QPushButton("🗑"); self.btn_clear.setFixedSize(34, 30)
        self.btn_clear.setToolTip("Sterge toate desenele")
        self.btn_undo.clicked.connect(self.draw_mgr.undo)
        self.btn_clear.clicked.connect(self._clear_all_drawings)
        lay.addWidget(self.btn_undo)
        lay.addWidget(self.btn_clear)
        lay.addStretch(1)
        return bar

    def _fit_candles(self, *args):
        """Buton 'A' (auto-range): fita DOAR pe lumanari, nu pe overlay-uri (fix bug epoca 0)."""
        d = self._data
        if d is None or not len(d.t):
            return
        vb = self.price.getViewBox()
        vb.enableAutoRange(x=False, y=False)   # oprim auto-range-ul care includea overlay-urile
        self._prog_range = True
        bar = d.bar_seconds
        vb.setXRange(float(d.t.min()), float(d.t.max()) + 10 * bar, padding=0.01)
        lo = min(float(d.low.min()), d.val)
        hi = max(float(d.high.max()), d.vah)
        vb.setYRange(lo, hi, padding=0.05)
        self._prog_range = False

    def _reset_draw_tool(self):
        self._tool_btns[None].setChecked(True)   # revine la cursor dupa un desen

    # ---------- Anchored VWAP ----------
    def _add_avwap_anchor(self, x):
        """Ancoreaza un VWAP la punctul dat (lipit de lumanarea cea mai apropiata)."""
        d = self._data
        if d is None or not len(d.t):
            return
        bar = d.bar_seconds
        anchor = float(round(x / bar) * bar)                 # lipit pe grila lumanarilor
        anchor = min(max(anchor, float(d.t.min())), float(d.t.max()))
        if anchor not in self._avwap_anchors:
            self._avwap_anchors.append(anchor)
        self._draw_avwaps()

    @staticmethod
    def _compute_avwap(d, anchor):
        """VWAP + deviatie standard (ponderata cu volumul) de la ancora incoace.
        Consistent cu VWAP-ul sesiunii: pret tipic (H+L+C)/3 ponderat cu volumul lumanarii."""
        idx = int(np.searchsorted(d.t, anchor, side="left"))
        idx = max(0, min(idx, len(d.t) - 1))
        t = d.t[idx:]
        tp = (d.high[idx:] + d.low[idx:] + d.close[idx:]) / 3.0
        v = d.volume[idx:].astype(float)
        # CENTRARE pe primul pret tipic: varianta e invarianta la translatie, dar centrarea
        # evita anularea catastrofala (preturi ~30000 ridicate la patrat) -> std stabil numeric.
        c = float(tp[0]) if len(tp) else 0.0
        tpc = tp - c
        cumv = np.cumsum(v)
        safe = np.where(cumv <= 0, np.nan, cumv)
        m = np.cumsum(tpc * v) / safe                        # media centrata
        avwap = m + c
        var = np.cumsum(v * tpc * tpc) / safe - m * m        # varianta ponderata a pretului tipic
        std = np.sqrt(np.clip(var, 0.0, None))
        return t, avwap, std

    def _draw_avwaps(self):
        """(Re)deseneaza toate Anchored VWAP-urile din snapshot-ul curent (dezvolta si in replay)."""
        for it in self._avwap_items:
            self.price.removeItem(it)
        self._avwap_items = []
        d = self._data
        if d is None or not len(d.t):
            return
        base = QtGui.QColor(theme.AVWAP)
        b1 = QtGui.QColor(theme.AVWAP); b1.setAlpha(150)     # ±1σ
        b2 = QtGui.QColor(theme.AVWAP); b2.setAlpha(90)      # ±2σ
        tmin, tmax = float(d.t.min()), float(d.t.max())
        for anchor in self._avwap_anchors:
            if anchor < tmin - d.bar_seconds or anchor > tmax:
                continue                                     # ancora nu e in sesiunea curenta
            t, avwap, std = self._compute_avwap(d, anchor)
            if not len(t):
                continue
            def add(x, y, pen):
                ln = pg.PlotDataItem(x, y, pen=pen, connect="finite")
                ln.setZValue(4); self.price.addItem(ln); self._avwap_items.append(ln)
            add(t, avwap + 2 * std, pg.mkPen(b2, width=1, style=QtCore.Qt.DotLine))
            add(t, avwap - 2 * std, pg.mkPen(b2, width=1, style=QtCore.Qt.DotLine))
            add(t, avwap + std, pg.mkPen(b1, width=1, style=QtCore.Qt.DashLine))
            add(t, avwap - std, pg.mkPen(b1, width=1, style=QtCore.Qt.DashLine))
            add(t, avwap, pg.mkPen(base, width=2))
            # eticheta "aVWAP" la ancora + ora
            lbl = pg.TextItem("aVWAP", color=theme.AVWAP, anchor=(1, 0.5))
            lbl.setPos(float(t[0]), float(avwap[0])); lbl.setZValue(5)
            self.price.addItem(lbl); self._avwap_items.append(lbl)

    def _clear_avwaps(self):
        self._avwap_anchors = []
        self._draw_avwaps()

    def _clear_all_drawings(self):
        """Butonul 🗑: sterge desenele + Anchored VWAP-urile."""
        self.draw_mgr.clear()
        self._clear_avwaps()

    def _on_marker_hover(self, scatter, points, ev):
        """Tooltip la trecerea peste o bula Big Trade sau un marker Absorption."""
        if points is None or len(points) == 0:
            self.hover_card.setVisible(False)
            return
        info = points[0].data()
        if not info:
            self.hover_card.setVisible(False)
            return
        if info[0] == "big":
            _, side, size, price, ep = info
            tag = "BUY" if side == "B" else ("SELL" if side == "A" else "?")
            t = datetime.datetime.fromtimestamp(
                int(ep) + self._tz_offset, datetime.timezone.utc).strftime("%d.%m %H:%M")
            txt = f"  {tag}   {int(size)} contracte\n  pret {price:.2f}\n  {t} {self._tz_label}  "
        elif info[0] == "exh":
            _, xkind, price, vol, delta = info
            title = "Exhaustion TOP (cumparatori epuizati)" if xkind == "top" else \
                    "Exhaustion BOT (vanzatori epuizati)"
            txt = (f"  {title}\n  Volum {vol:.0f}   Delta {delta:+.0f}\n"
                   f"  pret {price:.2f}  ")
        else:   # "abs"
            _, akind, price, buyv, sellv = info
            title = "Bullish Absorption" if akind == "bull" else "Bearish Absorption"
            txt = (f"  {title}\n  Sell {sellv:.0f}    Buy {buyv:.0f}\n"
                   f"  Delta {buyv - sellv:+.0f}   pret {price:.2f}  ")
        self.hover_card.setText(txt)
        self.hover_card.setPos(points[0].pos().x(), points[0].pos().y())
        self.hover_card.setVisible(True)

    def _snap_point(self, x, y):
        """Magnet (Ctrl): lipeste (x,y) de OHLC-ul celei mai apropiate lumanari, ca pe TradingView."""
        d = self._data
        if d is None or not len(d.t):
            return x, y
        i = int(round((x - float(d.t[0])) / d.bar_seconds))
        i = max(0, min(i, len(d.t) - 1))
        cand = (float(d.open[i]), float(d.high[i]), float(d.low[i]), float(d.close[i]))
        ny = min(cand, key=lambda v: abs(v - y))
        return float(d.t[i]), ny

    def _build_crosshair(self):
        self.vLine = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen(theme.TEXT_DIM, width=1, style=QtCore.Qt.DotLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False,
                                     pen=pg.mkPen(theme.TEXT_DIM, width=1, style=QtCore.Qt.DotLine))
        self.price.addItem(self.vLine, ignoreBounds=True)
        self.price.addItem(self.hLine, ignoreBounds=True)
        self.cross_label = pg.TextItem(color=theme.TEXT, anchor=(0, 1),
                                       fill=pg.mkBrush(30, 34, 45, 220))
        self.price.addItem(self.cross_label, ignoreBounds=True)
        # Card mic de identificare a liniilor de nivel (hover): apare cand cursorul e
        # aproape de o linie (HVN/LVN/POC/VAH/VAL/nivele de ieri) -> nume + pret.
        self.level_tip = pg.TextItem(color=theme.TEXT, anchor=(0, 0.5),
                                     fill=pg.mkBrush(18, 20, 28, 235),
                                     border=pg.mkPen(theme.BORDER))
        self.level_tip.setZValue(60)
        self.level_tip.setVisible(False)
        self.price.addItem(self.level_tip, ignoreBounds=True)
        # Bar Info: panou care apare la CLICK pe o lumanare (OHLC + order flow al barei)
        self.bar_info = pg.TextItem(anchor=(0, 0), fill=pg.mkBrush(16, 18, 26, 238),
                                    border=pg.mkPen(theme.BORDER))
        self.bar_info.setZValue(62)
        self.bar_info.setVisible(False)
        self.price.addItem(self.bar_info, ignoreBounds=True)
        self.price.scene().sigMouseMoved.connect(self._on_mouse)
        self.price.scene().sigMouseClicked.connect(self._on_chart_click)

    def _on_mouse(self, pos):
        vb = self.price.getViewBox()
        if not self.price.sceneBoundingRect().contains(pos):
            return
        pt = vb.mapSceneToView(pos)
        d = self._data
        # Lipim crosshair-ul de lumanarea cea mai apropiata -> ora consistenta
        if d is not None and len(d.t):
            bar = d.bar_seconds
            snapped = round(pt.x() / bar) * bar
        else:
            snapped = pt.x()
        self.vLine.setPos(snapped)
        self.hLine.setPos(pt.y())
        t = datetime.datetime.fromtimestamp(
            int(snapped) + self._tz_offset, datetime.timezone.utc).strftime("%d.%m %H:%M")
        txt = f"  {pt.y():.2f}   {t} {self._tz_label}  "
        if d is not None and self.cbo_type.currentText() == "Footprint" and d.footprint:
            cell = d.footprint.get(int(round(snapped)))
            if cell:
                price = round(round(pt.y() / d.row_size) * d.row_size, 4)
                cc = cell.get(price)
                if cc:
                    buy, sell = cc
                    txt += f"|  buy {buy:.0f}   sell {sell:.0f}   Δ {buy - sell:+.0f}  "
        self.cross_label.setText(txt)
        self.cross_label.setPos(snapped, pt.y())
        self._update_level_tip(vb, pt)
        self._marker_hover_at(vb, pt)   # tooltip markere (livrat MANUAL, vezi metoda)

    def _marker_hover_at(self, vb, pt):
        """Tooltip pe markere (Big Trades / Absorption / Exhaustion) livrat MANUAL din
        sigMouseMoved. Motiv: pyqtgraph 0.14 / PySide6 nu mai livreaza hoverEvent la
        ScatterPlotItem, deci sigHovered nu se declanseaza. Detectam proximitatea in px."""
        try:
            xs, ys = vb.viewPixelSize()
        except Exception:
            xs = ys = 0.0
        if xs <= 0 or ys <= 0:
            self.hover_card.setVisible(False)
            return
        best = None
        best_d = 1e18
        for sc in (self.abs_scatter, self.exh_scatter, self.big_scatter):
            if not sc.isVisible():
                continue
            for p in sc.points():
                pos = p.pos()
                dx = (pt.x() - pos.x()) / xs
                dy = (pt.y() - pos.y()) / ys
                d = (dx * dx + dy * dy) ** 0.5
                if d < best_d:
                    best_d, best = d, (sc, p)
        if best is not None and best_d <= 13.0:      # in ~13 px de un marker -> arata cardul
            self._on_marker_hover(best[0], [best[1]], None)
        else:
            self.hover_card.setVisible(False)

    def _update_level_tip(self, vb, pt):
        """Hover pe linii: daca cursorul e langa o linie de nivel, arata nume + pret."""
        try:
            _, y_per_px = vb.viewPixelSize()
        except Exception:
            self.level_tip.setVisible(False)
            return
        if y_per_px <= 0:
            self.level_tip.setVisible(False)
            return
        # Toate liniile etichetabile: (pret, nume, culoare). POC/VA din liniile curente
        # (valorile afisate), HVN/LVN din preturile retinute, cele de ieri daca-s vizibile.
        levels = []
        for key, name in (("poc", "POC"), ("vah", "VAH"), ("val", "VAL")):
            ln = self.price_lines[key]
            levels.append((ln.value(), name, ln.pen.color()))
        hvn_c = QtGui.QColor(theme.HVN)
        lvn_c = QtGui.QColor(theme.LVN)
        for p in self._hvn_prices:
            levels.append((p, "HVN", hvn_c))
        for p in self._lvn_prices:
            levels.append((p, "LVN", lvn_c))
        if self.chk_prior.isChecked():
            for key, name in (("poc", "yPOC"), ("vah", "yVAH"), ("val", "yVAL"),
                              ("high", "PDH"), ("low", "PDL")):
                ln = self.prior_lines[key]
                if ln.isVisible():
                    levels.append((ln.value(), name, ln.pen.color()))

        best = None
        for price, name, color in levels:
            dist_px = abs(price - pt.y()) / y_per_px
            if dist_px <= 7 and (best is None or dist_px < best[0]):
                best = (dist_px, price, name, color)
        if best is None:
            self.level_tip.setVisible(False)
            return
        _, price, name, color = best
        html = (f'<span style="color:{color.name()}; font-weight:600">{name}</span>'
                f'<span style="color:{theme.TEXT}">  {price:.2f}</span>')
        self.level_tip.setHtml(f'&nbsp;{html}&nbsp;')
        self.level_tip.setPos(pt.x(), price)
        self.level_tip.setVisible(True)

    # ---------- Bar Info (click pe o lumanare) ----------
    def _on_chart_click(self, ev):
        """DUBLU-click pe o lumanare -> panou Bar Info. Click SIMPLU -> il ascunde
        (nu mai ramane permanent pe ecran)."""
        if self.draw_mgr.tool is not None:      # desenam -> lasa DrawingManager sa preia
            return
        d = self._data
        if d is None or not len(d.t):
            return
        if not self.price.sceneBoundingRect().contains(ev.scenePos()):
            return
        is_double = False
        try:
            is_double = bool(ev.double())
        except Exception:
            pass
        if is_double:
            pt = self.price.getViewBox().mapSceneToView(ev.scenePos())
            i = int(np.argmin(np.abs(d.t - float(pt.x()))))   # lumanarea cea mai apropiata
            self._show_bar_info(i)
        else:
            self.bar_info.setVisible(False)                   # click simplu = ascunde

    def _show_bar_info(self, i):
        """Panou cu radiografia lumanarii i: OHLC, range/body/wick, volum, trades,
        Average Trade Size, delta/delta%, Efficiency (volum/tick) + distanta POC/VWAP."""
        d = self._data
        o, h, l, c = float(d.open[i]), float(d.high[i]), float(d.low[i]), float(d.close[i])
        vol = float(d.volume[i]); rng = h - l; body = abs(c - o)
        uw = h - max(o, c); lw = min(o, c) - l
        trades = float(d.tps[i]) * d.bar_seconds if len(getattr(d, "tps", [])) > i else 0.0
        avg = vol / trades if trades > 0 else 0.0
        dv = np.diff(d.cvd, prepend=0.0) if len(d.cvd) else np.zeros(len(d.t))
        delta = float(dv[i]) if i < len(dv) else 0.0
        dpct = (delta / vol * 100.0) if vol else 0.0
        rng_t = rng / TICK_SIZE if TICK_SIZE else 0.0
        eff = vol / rng_t if rng_t > 0 else 0.0
        # Efficiency relativa la ziua asta (efort vs rezultat) -> descriptor onest, data-driven
        rall = (d.high - d.low) / TICK_SIZE
        with np.errstate(divide="ignore", invalid="ignore"):
            eall = np.where(rall > 0, d.volume / rall, 0.0)
        emed = float(np.median(eall[eall > 0])) if np.any(eall > 0) else 0.0
        eff_tag = ""
        if emed > 0 and eff > 0:
            r = eff / emed
            eff_tag = "efort mare" if r >= 1.7 else ("eficient" if r <= 0.6 else "")
        d_poc = c - (d.poc or 0.0)
        vw = float(d.vwap[i]) if (i < len(d.vwap) and not np.isnan(d.vwap[i])) else None
        tstr = datetime.datetime.fromtimestamp(int(d.t[i]) + self._tz_offset,
                                               datetime.timezone.utc).strftime("%d.%m %H:%M")
        up = c >= o
        dc = theme.UP if delta >= 0 else theme.DOWN
        cc = theme.UP if up else theme.DOWN
        dim = theme.TEXT_DIM

        def k(v):
            return f"{v/1000:.1f}K" if abs(v) >= 1000 else f"{v:.0f}"

        html = (
            f'<div style="font-family:Consolas,monospace; font-size:11px; color:{theme.TEXT}; line-height:150%">'
            f'<b>{tstr}</b>&nbsp; <span style="color:{cc}">{"▲" if up else "▼"} {c:.2f}</span><br>'
            f'<span style="color:{dim}">O</span> {o:.2f}&nbsp; <span style="color:{dim}">H</span> {h:.2f}&nbsp; '
            f'<span style="color:{dim}">L</span> {l:.2f}<br>'
            f'<span style="color:{dim}">Range</span> {rng:.2f} ({rng_t:.0f}t)&nbsp; '
            f'<span style="color:{dim}">Body</span> {body:.2f}<br>'
            f'<span style="color:{dim}">Wick</span> ↑{uw:.2f} ↓{lw:.2f}<br>'
            f'<span style="color:{dim}">Vol</span> {k(vol)}&nbsp; '
            f'<span style="color:{dim}">Trades</span> {trades:.0f}&nbsp; '
            f'<span style="color:{dim}">Avg</span> {avg:.1f}<br>'
            f'<span style="color:{dim}">Δ</span> <span style="color:{dc}">{delta:+.0f} ({dpct:+.0f}%)</span><br>'
            f'<span style="color:{dim}">Eff</span> {eff:.0f} c/tick'
            + (f' <span style="color:{theme.ACCENT}">· {eff_tag}</span>' if eff_tag else '') + '<br>'
            f'<span style="color:{dim}">POC</span> {d_poc:+.1f}'
            + (f'&nbsp; <span style="color:{dim}">VWAP</span> {c - vw:+.1f}' if vw is not None else '')
            + '</div>'
        )
        self.bar_info.setHtml(html)
        self.bar_info.setVisible(True)
        self._position_bar_info()

    def _position_bar_info(self):
        """Fixeaza panoul in coltul STANGA-SUS al vederii (se re-aliniaza la zoom/pan)."""
        if not getattr(self, "bar_info", None) or not self.bar_info.isVisible():
            return
        (xmin, xmax), (ymin, ymax) = self.price.getViewBox().viewRange()
        self.bar_info.setPos(xmin + (xmax - xmin) * 0.012, ymax - (ymax - ymin) * 0.02)

    # ---------- Incarcare date ----------
    def _reload(self):
        fname = self.cbo_day.currentData()
        if not fname:
            return
        if getattr(self, "bar_info", None):
            self.bar_info.setVisible(False)   # ascunde Bar Info vechi la schimbarea zilei/perioadei
        per = self.cbo_period.currentText()
        if per.startswith("Zi UTC"):
            self._mode, self._span = "utc", "day"
        elif per.startswith("Composite"):
            self._mode = "session"
            self._span = ("15d" if "15" in per else
                          "90d" if "90" in per else "week")
        else:                                    # Sesiune / Visible / Custom
            self._mode, self._span = "session", "day"
        self._vp_scope = ("visible" if per.startswith("Visible")
                          else "custom" if per.startswith("Custom") else "full")
        self.setCursor(QtCore.Qt.WaitCursor)
        try:
            d = load_day(fname,
                         va_percent=float(self.cbo_va.currentText()) / 100.0,
                         interval=self.cbo_interval.currentText(),
                         row_size=float(self.cbo_res.currentText()),
                         mode=self._mode, span=self._span,
                         big_trade_min=self._big_min, abs_params=self._abs_params,
                         exh_params=self._exh_params, lvn_full_profile=self._lvn_full)
        finally:
            self.unsetCursor()

        self.lbl_warn.setText(
            "⚠ sesiune incompleta (lipseste ziua precedenta)" if d.incomplete else "")
        self._data_full = d
        self._apply_tz()   # recalculeaza fusul pentru DATA acestei zile (ora vara/iarna corecta)
        self._update_prior_levels()   # nivelurile sesiunii precedente (yPOC/yVAH/yVAL/PDH/PDL)
        self._update_session_profiles()  # profile separate Asia/Londra/NY (VAH/VAL + LVN)
        self._setup_custom_region()   # arata/ascunde zona Custom range

        if self.btn_replay.isChecked():
            self._enter_replay()
        else:
            self._render(d, set_range=True)

    def _rerender_current(self):
        """Re-deseneaza snapshot-ul curent FARA reload si FARA sa schimbe view-ul.
        (toggle HVN/LVN, VP, Profil/Footprint -> nu reseta pozitia/zoom-ul)."""
        if self._data is not None:
            self._render(self._data, set_range=False, follow=False)

    def _set_nodes(self, hvn, lvn):
        """(Re)deseneaza liniile HVN/LVN. Reutilizat de _render si de modul Visible."""
        for ln in self.node_lines:
            self.price.removeItem(ln)
        self.node_lines = []
        # Retinem preturile pt identificarea liniilor la hover (nu mai au pastila de text)
        self._hvn_prices = list(hvn) if self.chk_nodes.isChecked() else []
        self._lvn_prices = list(lvn) if self.chk_nodes.isChecked() else []
        if not self.chk_nodes.isChecked():
            return
        hvn_c = QtGui.QColor(theme.HVN); hvn_c.setAlpha(160)
        lvn_c = QtGui.QColor(theme.LVN); lvn_c.setAlpha(140)
        # HVN/LVN = doar liniile colorate (cyan plin / gri punctat), FARA pastile de text:
        # culoarea+stilul le disting deja, iar pastilele repetate aglomerau axa din dreapta.
        for y in hvn:
            ln = pg.InfiniteLine(pos=y, angle=0, movable=False, pen=pg.mkPen(hvn_c, width=0.8))
            ln.setZValue(-3); self.price.addItem(ln); self.node_lines.append(ln)
        for y in lvn:
            ln = pg.InfiniteLine(pos=y, angle=0, movable=False,
                                 pen=pg.mkPen(lvn_c, width=1, style=QtCore.Qt.DotLine))
            ln.setZValue(-3); self.price.addItem(ln); self.node_lines.append(ln)

    def _recompute_vp_range(self, x0, x1):
        """Recalculeaza profilul + POC/VA/HVN/LVN doar pe lumanarile din [x0, x1]."""
        if self._data is None or not len(self._data.t):
            return
        d = self._data
        epochs = [int(t) for t in d.t if x0 <= t <= x1]
        if not epochs:
            return
        res = profile_from_footprint(d.footprint, epochs, d.row_size,
                                     float(self.cbo_va.currentText()) / 100.0,
                                     lvn_full_profile=self._lvn_full)
        if res is None:
            return
        if self.chk_vp.isChecked():
            self.profile_item.set_data(res["bin_price"], res["bin_buy"], res["bin_sell"], d.row_size,
                                       va_low=res["val"], va_high=res["vah"], poc=res["poc"])
        self.price_lines["poc"].setPos(res["poc"])
        self.price_lines["vah"].setPos(res["vah"])
        self.price_lines["val"].setPos(res["val"])
        self.va_band.setRegion((res["val"], res["vah"]))
        self._set_nodes(res["hvn"], res["lvn"])
        self.card_poc.set_value(f"{res['poc']:.2f}", theme.POC)
        self.card_va.set_value(f"{res['vah']:.0f} / {res['val']:.0f}")

    def _apply_vp_scope(self, *args):
        """VISIBLE: profil pe fereastra vizibila (se schimba la zoom/pan)."""
        if self._vp_scope != "visible" or self._data is None or not len(self._data.t):
            return
        (xmin, xmax), _ = self.price.getViewBox().viewRange()
        self._recompute_vp_range(xmin, xmax)

    def _on_custom_region(self, *args):
        """CUSTOM range: profil pe zona trasa (fixa, se ajusteaza tragand de margini)."""
        if self._vp_scope != "custom":
            return
        x0, x1 = self.custom_region.getRegion()
        self._recompute_vp_range(x0, x1)

    def _setup_custom_region(self):
        """Arata zona Custom (initializata pe treimea din mijloc la intrare) sau o ascunde."""
        if self._vp_scope == "custom":
            if not self.custom_region.isVisible() and self._data_full is not None and len(self._data_full.t):
                t = self._data_full.t
                self.custom_region.blockSignals(True)
                self.custom_region.setRegion((float(t[len(t) // 3]), float(t[2 * len(t) // 3])))
                self.custom_region.blockSignals(False)
            self.custom_region.setVisible(True)
        else:
            self.custom_region.setVisible(False)

    def _apply_lod(self, *args):
        """
        Smart Layers: ce straturi se vad, in functie de zoom (cand Auto e on).
        Zoom out = curat (doar lumanari/VP/VWAP/POC/CVD); zoom mediu = +Big Trades/Absorption;
        zoom in (Footprint) = celule footprint (cu delta/Bid×Ask dupa marimea celulei).
        Cand Auto e off, checkbox-urile decid (comportament manual).
        """
        self._position_bar_info()   # panoul Bar Info ramane in coltul stanga-sus la zoom/pan
        is_fp = self.cbo_type.currentText() == "Footprint"
        if not self.chk_auto.isChecked() or self._data is None or not len(self._data.t):
            self.footprint_item.setVisible(is_fp)
            self.candles.setVisible(not is_fp)
            self.big_scatter.setVisible(self.chk_big.isChecked())
            self.abs_scatter.setVisible(self.chk_abs.isChecked())
            self.exh_scatter.setVisible(self.chk_exh.isChecked())
            return
        (xmin, xmax), _ = self.price.getViewBox().viewRange()
        vis = float(xmax - xmin) / self._data.bar_seconds    # cate lumanari sunt vizibile
        fp_show = bool(is_fp and vis <= 220)                  # footprint pana la zoom mediu (heatmap compact); apoi lumanari
        self.footprint_item.setVisible(fp_show)
        self.candles.setVisible(not fp_show)
        # Markerele (Big Trades / Absorption / Exhaustion) sunt rare si importante -> MEREU
        # vizibile cand stratul e pornit (indiferent de zoom), ca sa le vezi + sa le poti hover-ui.
        self.big_scatter.setVisible(self.chk_big.isChecked())
        self.abs_scatter.setVisible(self.chk_abs.isChecked())
        self.exh_scatter.setVisible(self.chk_exh.isChecked())

    def _reload_keep(self):
        """Reload care PASTREAZA pozitia din replay + zoom-ul (interval/VA%/rezolutie)."""
        epoch = None
        if self._replay is not None and self._data is not None and len(self._data.t):
            epoch = int(self._data.t[-1])
        (x0, x1), (y0, y1) = self.price.getViewBox().viewRange()
        self._reload()
        if epoch is not None and self._replay is not None:
            j = int(np.argmin(np.abs(self._replay.full.t - epoch)))
            self._pause_playback()
            self._render(self._replay.seek_candle(j), set_range=False, follow=False)
        self._prog_range = True
        self.price.setXRange(x0, x1, padding=0)
        self.price.setYRange(y0, y1, padding=0)
        self._prog_range = False

    def _render(self, d, set_range=True, follow=False):
        """Actualizeaza toate elementele vizuale dintr-un DayData (complet sau partial-replay)."""
        self._data = d
        is_fp = self.cbo_type.currentText() == "Footprint"
        show_vp = self.chk_vp.isChecked()
        # Date: lumanarile MEREU (pt fallback LOD la zoom-out), footprint doar in mod footprint.
        self.candles.set_data(d.t, d.open, d.high, d.low, d.close, d.bar_seconds)
        if is_fp:
            self.footprint_item.set_data(d.footprint, d.bar_seconds, d.row_size)
        self.profile_item.setVisible(show_vp)
        if show_vp:
            self.profile_item.set_data(d.bin_price, d.bin_buy, d.bin_sell, d.row_size,
                                       va_low=d.val, va_high=d.vah, poc=d.poc)
        # Vizibilitatea lumanari/footprint/big/absorption o decide _apply_lod (Auto sau manual)

        for key in ("poc", "vah", "val"):
            self.price_lines[key].setPos(getattr(d, key))
        self.last_line.setPos(d.last_price)
        self.vwap_curve.setData(d.t, d.vwap)
        # umplere continua: partea de peste 0 (verde) si de sub 0 (mov) + linia continua
        self.cvd_pos.setData(d.t, np.clip(d.cvd, 0.0, None))
        self.cvd_neg.setData(d.t, np.clip(d.cvd, None, 0.0))
        self.cvd_line.setData(d.t, d.cvd)
        self.va_band.setRegion((d.val, d.vah))

        # Grid statistici jos: ΣV / ΔV / Δ% per lumanare (delta = diferenta CVD-ului)
        if len(d.t):
            delta_v = np.diff(d.cvd, prepend=0.0)   # delta per lumanare (cvd = cumulativ)
            self.grid_stats.set_data(d.t, d.volume, delta_v, d.bar_seconds,
                                     tps=getattr(d, "tps", None))

        # Big Trades - bule (marime dupa volum, verde=buy / mov=sell)
        if d.big_trades:
            xs = [bt[0] for bt in d.big_trades]
            ys = [bt[1] for bt in d.big_trades]
            szs = [_bt_tier(bt[2]) for bt in d.big_trades]   # trepte discrete de marime
            buy_c = QtGui.QColor(theme.UP); buy_c.setAlpha(235)
            sell_c = QtGui.QColor(theme.DOWN); sell_c.setAlpha(235)
            buy_b, sell_b = pg.mkBrush(buy_c), pg.mkBrush(sell_c)
            brs = [buy_b if bt[3] == "B" else sell_b for bt in d.big_trades]
            info = [("big", bt[3], bt[2], bt[1], bt[0]) for bt in d.big_trades]  # tip,side,size,pret,epoca
            # Contur luminos -> bula se vede pe orice fundal (footprint), iar culoarea plina = directia
            halo = pg.mkPen(QtGui.QColor(245, 245, 250), width=1.4)
            self.big_scatter.setData(x=xs, y=ys, size=szs, brush=brs, data=info, pen=halo)
        else:
            self.big_scatter.setData(x=[], y=[])
        self._set_bt_zones(d.big_trades)   # zone S/R din cele mai mari tranzactii (optional)

        # Absorption - triunghi la extrema respinsa: bull (verde) sub minim, bear (mov) peste maxim
        if d.absorption:
            yr = float(d.high.max() - d.low.min()) if len(d.high) else 1.0
            off = max(yr * 0.014, d.row_size)
            abs_b = pg.mkBrush(QtGui.QColor(theme.ABSORPTION))       # galben = categoria Absorption
            halo = pg.mkPen(QtGui.QColor(theme.ABSORPTION), width=2.4)  # halo -> sare in ochi
            spots = []
            for ep, price, kind, buyv, sellv in d.absorption:
                # directie prin forma + pozitie: bull = triunghi sus, sub minim; bear = jos, peste maxim
                info = ("abs", kind, price, buyv, sellv)
                if kind == "bull":
                    spots.append({"pos": (ep, price - off), "symbol": "t1", "size": 20,
                                  "brush": abs_b, "pen": halo, "data": info})
                else:
                    spots.append({"pos": (ep, price + off), "symbol": "t", "size": 20,
                                  "brush": abs_b, "pen": halo, "data": info})
            self.abs_scatter.setData(spots)
        else:
            self.abs_scatter.setData([])

        # Exhaustion - romb la climaxul de la o extrema noua: top (sub-forma jos, peste maxim) /
        # bot (sus, sub minim). Culoare coral = avertisment climax/reversal.
        if d.exhaustion:
            yr = float(d.high.max() - d.low.min()) if len(d.high) else 1.0
            off = max(yr * 0.018, d.row_size)
            exh_b = pg.mkBrush(QtGui.QColor(theme.EXHAUSTION))
            exh_halo = pg.mkPen(QtGui.QColor(theme.EXHAUSTION), width=2.2)
            spots = []
            for ep, price, kind, vol, delta in d.exhaustion:
                info = ("exh", kind, price, vol, delta)
                yoff = price + off if kind == "top" else price - off
                spots.append({"pos": (ep, yoff), "symbol": "d", "size": 17,
                              "brush": exh_b, "pen": exh_halo, "data": info})
            self.exh_scatter.setData(spots)
        else:
            self.exh_scatter.setData([])
        self._apply_lod()   # Smart Layers: vizibilitatea straturilor dupa zoom (Auto) sau manual

        self._set_nodes(d.hvn, d.lvn)
        self._update_session_shading()      # benzi overnight (RTH iese in evidenta)
        self._draw_avwaps()                 # Anchored VWAP-uri (se dezvolta si in replay)
        # Developing POC/VA: trail-ul migrarii valorii (optional, se dezvolta in replay)
        show_dev = self.chk_dev.isChecked() and len(getattr(d, "dev_poc", [])) == len(d.t) and len(d.t)
        if show_dev:
            self.dev_poc_curve.setData(d.t, d.dev_poc)
            self.dev_vah_curve.setData(d.t, d.dev_vah)
            self.dev_val_curve.setData(d.t, d.dev_val)
        for c in (self.dev_poc_curve, self.dev_vah_curve, self.dev_val_curve):
            c.setVisible(bool(show_dev))
        if self._vp_scope == "visible":
            self._apply_vp_scope()          # profil pe fereastra vizibila
        elif self._vp_scope == "custom":
            self._on_custom_region()        # profil pe zona trasa

        if follow and self._follow and len(d.t):
            # Replay: fereastra care deruleaza cu lumanarea curenta (urmareste pretul).
            # _prog_range marcheaza ca noi schimbam range-ul (ca sa nu para interactiune user).
            self._prog_range = True
            bar = d.bar_seconds
            x0 = d.t[-1] - 70 * bar
            x1 = d.t[-1] + 8 * bar          # margine in dreapta (nu lipit de axa)
            self.price.setXRange(x0, x1, padding=0)
            vis = d.t >= x0
            los, his = d.low[vis], d.high[vis]
            if len(los):
                lo, hi = float(los.min()), float(his.max())
                pad = max((hi - lo) * 0.15, 3.0)
                self.price.setYRange(lo - pad, hi + pad, padding=0)
            self._prog_range = False
        elif set_range and len(d.t):
            bar = d.bar_seconds
            self.price.setXRange(d.t.min(), d.t.max() + 10 * bar, padding=0.01)  # margine dreapta = zona de proiectie POC ray
            lo = min(float(d.low.min()), d.val)
            hi = max(float(d.high.max()), d.vah)
            self.price.setYRange(lo, hi, padding=0.05)

        self.card_symbol.set_value(d.symbol)
        self.card_poc.set_value(f"{d.poc:.2f}", theme.POC)
        self.card_va.set_value(f"{d.vah:.0f} / {d.val:.0f}")
        self.card_vol.set_value(f"{d.total_volume:,.0f}")
        pos = d.cum_delta >= 0
        self.card_delta.set_value(f"{d.cum_delta:+,.0f}", theme.UP if pos else theme.DOWN)

        # Sincronizeaza scrubber-ul + eticheta de pozitie cu lumanarea curenta din replay
        if self._replay is not None and len(d.t):
            idx = self._replay.current_candle_index()
            self._prog_slider = True
            self.scrubber.setValue(idx)
            self._prog_slider = False
            tstr = datetime.datetime.fromtimestamp(
                int(d.t[-1]) + self._tz_offset, datetime.timezone.utc).strftime("%d.%m %H:%M")
            self.lbl_pos.setText(f"{tstr} {self._tz_label}   ·   bar {idx + 1}/{self._replay.n_candles}")

    # ---------- Replay ----------
    def _enter_replay(self):
        d = self._data_full
        if d is None:
            return
        tk, _ = resolve_ticks(self.cbo_day.currentData(), self._mode, self._span)
        self._replay = Replay(d, tk.df,
                              va_percent=float(self.cbo_va.currentText()) / 100.0,
                              row_size=float(self.cbo_res.currentText()),
                              big_trade_min=self._big_min, abs_params=self._abs_params,
                              exh_params=self._exh_params, lvn_full_profile=self._lvn_full)
        self._follow = True
        self.btn_follow.blockSignals(True)
        self.btn_follow.setChecked(True)
        self.btn_follow.blockSignals(False)
        self.scrubber.blockSignals(True)
        self.scrubber.setRange(0, self._replay.n_candles - 1)
        self.scrubber.blockSignals(False)
        self._replay_controls.setEnabled(True)
        # Aratam sesiunea COMPLETA, pe pauza, pastrand view-ul curent -> "ramane normal",
        # userul deruleaza cu bara (scrubber) la ora unde vrea sa inceapa backtesting-ul.
        full = self._replay.seek_candle(self._replay.n_candles - 1)
        if full is not None:
            self._render(full, set_range=False, follow=False)
        if self.btn_play.isChecked():
            self._start_timer()

    def _exit_replay(self):
        self.replay_timer.stop()
        self._replay = None
        self._replay_controls.setEnabled(False)
        self.scrubber.blockSignals(True)
        self.scrubber.setValue(0)
        self.scrubber.blockSignals(False)
        self.lbl_pos.setText("—")
        if self._data_full is not None:
            self._render(self._data_full, set_range=True)

    def _on_replay_toggled(self):
        if self.btn_replay.isChecked():
            self.btn_play.blockSignals(True)          # intram pe PAUZA (nu pornim din capat)
            self.btn_play.setChecked(False)
            self.btn_play.setText("▶")
            self.btn_play.blockSignals(False)
            self._enter_replay()
        else:
            self.btn_play.setChecked(False)
            self.btn_play.setText("▶")
            self._exit_replay()

    def _on_play_toggled(self):
        if not self.btn_replay.isChecked():
            return
        if self.btn_play.isChecked():
            self.btn_play.setText("⏸")
            self._start_timer()
        else:
            self.btn_play.setText("▶")
            self.replay_timer.stop()

    def _on_speed_changed(self):
        if self.btn_replay.isChecked() and self.btn_play.isChecked():
            self._start_timer()

    def _on_range_changed(self):
        # User a dat zoom/pan manual in timpul replay -> oprim auto-follow (il lasam sa inspecteze)
        if self._replay is not None and not self._prog_range and self._follow:
            self._follow = False
            self.btn_follow.blockSignals(True)
            self.btn_follow.setChecked(False)
            self.btn_follow.blockSignals(False)

    def _on_follow_toggled(self):
        self._follow = self.btn_follow.isChecked()
        if self._follow and self._replay is not None and self._data is not None:
            self._render(self._data, set_range=False, follow=True)  # re-centreaza pe pret

    def _apply_tz(self):
        """
        Calculeaza offset-ul fusului pentru DATA sesiunii incarcate (nu ziua de azi),
        cu zoneinfo -> ora de vara/iarna corecta automat. Actualizeaza axa de timp.
        """
        zone = TZ_ZONE.get(self._tz_name)
        if zone is None:
            self._tz_offset, self._tz_label = 0, "UTC"
        else:
            d = self._data_full
            if d is not None and len(d.t):
                ref = int(d.t[len(d.t) // 2])    # mijlocul sesiunii (in RTH) = reprezentativ
            else:
                ref = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            off = datetime.datetime.fromtimestamp(ref, ZoneInfo(zone)).utcoffset()
            self._tz_offset = int(off.total_seconds()) if off else 0
            self._tz_label = TZ_LABEL[self._tz_name]
        self.time_axis.tz_offset = self._tz_offset
        self.time_axis.picture = None            # forteaza re-etichetarea axei
        self.time_axis.update()

    def _on_tz_changed(self):
        self._tz_name = self.cbo_tz.currentText()
        self._apply_tz()
        if self._data is not None:               # re-randam ca sa updatam etichetele
            self._render(self._data, set_range=False, follow=self._follow)

    # ---------- Nivelurile sesiunii precedente (backtesting) ----------
    def _update_prior_levels(self):
        """Calculeaza + pozitioneaza yPOC/yVAH/yVAL/PDH/PDL (doar mod '1 zi')."""
        self._prior = None
        if self._span == "day":
            try:
                self._prior = prior_session_levels(
                    self.cbo_day.currentData(), mode=self._mode,
                    va_percent=float(self.cbo_va.currentText()) / 100.0,
                    row_size=float(self.cbo_res.currentText()))
            except Exception:
                self._prior = None
        if self._prior:
            for key in ("poc", "vah", "val", "high", "low"):
                self.prior_lines[key].setPos(self._prior[key])
            self.prior_va_band.setRegion((self._prior["val"], self._prior["vah"]))
        self._update_prior_visibility()

    def _update_prior_visibility(self):
        show = self.chk_prior.isChecked() and self._prior is not None
        for ln in self.prior_lines.values():
            ln.setVisible(show)
        self.prior_va_band.setVisible(show)

    # ---------- Profile per-sesiune (Asia / Londra / NY) ----------
    def _active_sessions(self):
        """Definitiile de sesiune pentru modul curent (fus real / ore RO fixe)."""
        return self._sessions[self._sess_mode]

    def _update_session_profiles(self):
        """Calculeaza VP separat pe Asia/Londra/NY (doar mod '1 zi') + (re)deseneaza."""
        self._sess_data = None
        if self._span == "day":
            try:
                self._sess_data = session_profiles(
                    self.cbo_day.currentData(), sessions=self._active_sessions(),
                    mode=self._mode, va_percent=float(self.cbo_va.currentText()) / 100.0,
                    row_size=float(self.cbo_res.currentText()),
                    lvn_full_profile=self._lvn_full)
            except Exception:
                self._sess_data = None
        self._render_session_lines()

    def _render_session_lines(self):
        """(Re)deseneaza nivelurile per-sesiune. Sursa unica pentru curatare + desen."""
        for ln in self._sess_lines:
            self.price.removeItem(ln)
        self._sess_lines = []
        if not (self.chk_sess.isChecked() and self._sess_data):
            return
        abbr = {"Asia": "A", "Londra": "L", "NY": "NY"}
        # Etichete DECALATE pe orizontala per sesiune -> nu se mai suprapun pe marginea dreapta
        sess_xpos = {"Asia": 0.70, "Londra": 0.80, "NY": 0.90}
        for name, info in self._sess_data.items():
            col = QtGui.QColor(theme.SESS_COLORS.get(name, theme.TEXT_DIM))
            tag = abbr.get(name, name[:2])
            xpos = sess_xpos.get(name, 0.86)
            for key, width, dash, lab in (("poc", 1.5, QtCore.Qt.SolidLine, "POC"),
                                          ("vah", 1, QtCore.Qt.DashLine, "VAH"),
                                          ("val", 1, QtCore.Qt.DashLine, "VAL")):
                v = info.get(key)
                if v is None:
                    continue
                ln = pg.InfiniteLine(
                    pos=v, angle=0, movable=False,
                    pen=pg.mkPen(col, width=width, style=dash),
                    label=f"{tag} {lab}", labelOpts={"position": xpos, "color": "#0a0a0a",
                                                     "fill": col, "movable": False})
                ln.setZValue(-4); self.price.addItem(ln); self._sess_lines.append(ln)
            for v in info.get("lvn", []):
                ln = pg.InfiniteLine(pos=v, angle=0, movable=False,
                                     pen=pg.mkPen(col, width=1, style=QtCore.Qt.DotLine))
                ln.setZValue(-4); self.price.addItem(ln); self._sess_lines.append(ln)

    def _on_sess_toggled(self, *a):
        """Toggle 'Sesiuni' din bara de straturi -> doar redesenare (fara recalcul)."""
        self._render_session_lines()

    def _open_sess_settings(self):
        """Panou ⚙ Sesiuni: mod de definire (fus real / ore RO) + orele fiecarei sesiuni.
        Dialogul se reconstruieste la fiecare deschidere -> reflecta mereu starea curenta."""
        if self._sess_dialog is not None:
            self._sess_dialog.close()
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Sesiuni — setari")
        dlg.setObjectName("VPDialog")
        form = QtWidgets.QFormLayout(dlg)
        form.setContentsMargins(16, 14, 16, 14); form.setSpacing(10)
        mode_cbo = QtWidgets.QComboBox()
        mode_cbo.addItems(["Fus real (auto vară/iarnă)", "Ore România fixe"])
        mode_cbo.setCurrentIndex(0 if self._sess_mode == "real" else 1)
        form.addRow("Definire", mode_cbo)

        edits = []
        for i, (name, tz, (sh, sm), (eh, em)) in enumerate(self._active_sessions()):
            te_s = QtWidgets.QTimeEdit(QtCore.QTime(sh, sm)); te_s.setDisplayFormat("HH:mm")
            te_e = QtWidgets.QTimeEdit(QtCore.QTime(eh, em)); te_e.setDisplayFormat("HH:mm")
            row = QtWidgets.QWidget(); rl = QtWidgets.QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)
            rl.addWidget(te_s); rl.addWidget(QtWidgets.QLabel("–")); rl.addWidget(te_e)
            suffix = "" if self._sess_mode == "ro" else f"  ({tz.split('/')[-1]})"
            form.addRow(name + suffix, row)
            edits.append((i, te_s, te_e))

        hint = QtWidgets.QLabel(
            "Fus real = orele in fusul bursei (auto vară/iarnă). "
            "Ore România fixe = exact orele de mai jos, fără ajustare.")
        hint.setObjectName("FieldLabel"); hint.setWordWrap(True); form.addRow(hint)

        def on_mode(idx):
            self._sess_mode = "real" if idx == 0 else "ro"
            self._update_session_profiles()
            self._open_sess_settings()          # reconstruieste cu orele modului nou

        def on_time(*a):
            for i, te_s, te_e in edits:
                s, e = te_s.time(), te_e.time()
                self._sessions[self._sess_mode][i][2] = [s.hour(), s.minute()]
                self._sessions[self._sess_mode][i][3] = [e.hour(), e.minute()]
            self._update_session_profiles()

        mode_cbo.currentIndexChanged.connect(on_mode)
        for _, te_s, te_e in edits:
            te_s.timeChanged.connect(on_time)
            te_e.timeChanged.connect(on_time)
        self._sess_dialog = dlg
        dlg.show(); dlg.raise_()

    def _on_grid_toggled(self, *a):
        """Arata/ascunde grid-ul de statistici. Axa de timp ramane jos (nu ascundem plot-ul).
        Cand e stins, ascundem si etichetele T/s/ΣV/ΔV/Δ% (nu mai stau agatate degeaba)."""
        show = self.chk_grid.isChecked()
        self.grid_stats.setVisible(show)
        self.grid_plot.getAxis("left").setStyle(showValues=show)   # latimea ramane fixa (34) -> aliniere ok
        lay = self.glw.ci.layout
        lay.setRowStretchFactor(2, 1 if show else 0)
        # Cand e stins, colapsam randul la inaltimea axei de timp -> pretul ia spatiul liber
        lay.setRowMaximumHeight(2, 16777215 if show else 30)

    def _on_cvd_toggled(self, *a):
        """Arata/ascunde panoul CVD (row 1). Axa de timp e pe grid (row 2), deci nu o afecteaza."""
        show = self.chk_cvd.isChecked()
        self.cvd_plot.setVisible(show)
        lay = self.glw.ci.layout
        lay.setRowStretchFactor(1, 1 if show else 0)
        lay.setRowMaximumHeight(1, 16777215 if show else 0)   # colapseaza randul CVD cand e stins

    def _on_compare_changed(self, *a):
        """Session Browser + Compare: suprapune profilul + nivelurile unei alte sesiuni
        (ancorat pe dreapta, albastru). '— fara —' curata."""
        fname = self.cbo_compare.currentData()
        if not fname:
            self._cmp_data = None
            self.cmp_profile.setVisible(False)
            for ln in self.cmp_lines.values():
                ln.setVisible(False)
            return
        self.setCursor(QtCore.Qt.WaitCursor)
        try:
            d = load_day(fname,
                         va_percent=float(self.cbo_va.currentText()) / 100.0,
                         interval=self.cbo_interval.currentText(),
                         row_size=float(self.cbo_res.currentText()),
                         mode=self._mode, span="day")
        except Exception:
            self._cmp_data = None
            self.cmp_profile.setVisible(False)
            for ln in self.cmp_lines.values():
                ln.setVisible(False)
            return
        finally:
            self.unsetCursor()
        self._cmp_data = d
        self.cmp_profile.set_data(d.bin_price, d.bin_buy, d.bin_sell, d.row_size,
                                  va_low=d.val, va_high=d.vah, poc=d.poc)
        self.cmp_profile.setVisible(True)
        for key in ("poc", "vah", "val"):
            self.cmp_lines[key].setPos(getattr(d, key))
            self.cmp_lines[key].setVisible(True)

    def _update_session_shading(self, *args):
        """Umbreste OVERNIGHT (Globex) inainte/dupa RTH -> sesiunea NY iese in evidenta.
        RTH = 09:30-16:00 ET (DST-corect via zoneinfo). Doar mod '1 zi'."""
        bands = self._session_bands
        d = self._data_full if self._data_full is not None else self._data
        show = (self.chk_session.isChecked() and d is not None
                and len(getattr(d, "t", [])) and self._span == "day")
        if not show:
            for b in bands:
                b.setVisible(False)
            return
        try:
            et = ZoneInfo("America/New_York")
            mid = int(d.t[len(d.t) // 2])
            et_date = datetime.datetime.fromtimestamp(mid, et).date()
            rth_open = datetime.datetime.combine(et_date, datetime.time(9, 30), et).timestamp()
            rth_close = datetime.datetime.combine(et_date, datetime.time(16, 0), et).timestamp()
        except Exception:
            for b in bands:
                b.setVisible(False)
            return
        bar = d.bar_seconds
        t0, t1 = float(d.t.min()), float(d.t.max()) + 10 * bar
        segs = []
        if rth_open > t0:                       # overnight de dinainte de RTH
            segs.append((t0, min(rth_open, t1)))
        if rth_close < t1:                      # overnight de dupa RTH
            segs.append((max(rth_close, t0), t1))
        for i, b in enumerate(bands):
            if i < len(segs) and segs[i][1] > segs[i][0]:
                b.setRegion(segs[i]); b.setVisible(True)
            else:
                b.setVisible(False)

    def _ticks_per_frame(self):
        return {"lent": 3, "1x": 15, "2x": 40, "5x": 120, "10x": 350}.get(
            self.cbo_speed.currentText(), 15)

    def _start_timer(self):
        self.replay_timer.start(40)   # ~25 cadre/sec; viteza = tick-uri/cadru

    def _replay_tick(self):
        if self._replay is None:
            return
        d = self._replay.step(self._ticks_per_frame())
        if d is None:  # am ajuns la finalul sesiunii
            self.replay_timer.stop()
            self.btn_play.setChecked(False)
            self.btn_play.setText("▶")
            return
        self._render(d, set_range=False, follow=True)

    # ---------- Navigare backtesting (scrub / step / jump) ----------
    def _ensure_replay(self):
        """Intra automat in replay daca nu suntem deja (pentru step/jump din bara)."""
        if not self.btn_replay.isChecked():
            self.btn_replay.setChecked(True)   # declanseaza _on_replay_toggled -> _enter_replay
        return self._replay is not None

    def _pause_playback(self):
        """Opreste redarea automata (nav manuala = pas cu pas)."""
        self.replay_timer.stop()
        if self.btn_play.isChecked():
            self.btn_play.blockSignals(True)
            self.btn_play.setChecked(False)
            self.btn_play.setText("▶")
            self.btn_play.blockSignals(False)

    def _nav_render(self, d):
        """Randare dupa o navigare manuala (bar-step / scrub / jump): PASTREAZA zoom-ul
        utilizatorului (latimea X + Y). Panorameaza doar daca lumanarea curenta iese din
        vedere -> nu se mai reseteaza graficul cand dai un pas cu Bar."""
        if d is None:
            return
        (x0, x1), (y0, y1) = self.price.getViewBox().viewRange()
        self._render(d, set_range=False, follow=False)
        if not len(d.t):
            return
        bar = d.bar_seconds
        cur = float(d.t[-1])
        width = x1 - x0
        self._prog_range = True
        if width > 0 and (cur > x1 - 2 * bar or cur < x0 + 2 * bar):
            nx1 = cur + 8 * bar                                   # aliniaza lumanarea in dreapta,
            self.price.setXRange(nx1 - width, nx1, padding=0)    # pastrand EXACT latimea (zoom-ul)
        self.price.setYRange(y0, y1, padding=0)                  # Y mereu pastrat
        self._prog_range = False

    def _step_bars(self, delta):
        if not self._ensure_replay():
            return
        self._pause_playback()
        j = self._replay.current_candle_index() + delta
        self._nav_render(self._replay.seek_candle(j))

    def _seek_to(self, j):
        if not self._ensure_replay():
            return
        self._pause_playback()
        self._nav_render(self._replay.seek_candle(j))

    def _on_scrub(self, value):
        if self._prog_slider or self._replay is None:
            return
        self._pause_playback()
        self._nav_render(self._replay.seek_candle(value))

    def _on_jump(self):
        if not self._ensure_replay():
            return
        txt = self.jump_edit.text().strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", txt)
        if not m:
            self.lbl_warn.setText("⚠ format ora: HH:MM")
            return
        self.lbl_warn.setText("")
        target_mod = (int(m.group(1)) * 60 + int(m.group(2))) % 1440
        t = self._replay.full.t
        best_i, best_d = 0, 10**9
        for i, ep in enumerate(t):
            dt = datetime.datetime.fromtimestamp(
                int(ep) + self._tz_offset, datetime.timezone.utc)
            mod = dt.hour * 60 + dt.minute
            diff = abs(mod - target_mod); diff = min(diff, 1440 - diff)
            if diff < best_d:
                best_d, best_i = diff, i
        self._pause_playback()
        self._nav_render(self._replay.seek_candle(best_i))

    def _toggle_play_key(self):
        if self.btn_replay.isChecked():
            self.btn_play.toggle()


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS)
    win = MainWindow()
    win.showMaximized()   # porneste pe tot ecranul (graficul se intinde), nu 1500x900
    return app, win


if __name__ == "__main__":
    app, win = main()
    app.exec()
