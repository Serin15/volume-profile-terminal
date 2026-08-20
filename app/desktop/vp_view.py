"""
VolumeProfileView — renderer Volume Profile REUTILIZABIL (Faza 1 din panouri)
-----------------------------------------------------------------------------
Deseneaza UN singur Volume Profile (un dict de la SessionStore / period_profiles)
intr-un plot dedicat, cu axa de pret proprie si zoom pe pret. E o componenta
de sine statatoare (QWidget) -> se poate pune in orice panou / card.

Faza 1 (acum): mod "total" — bare volum-la-pret + banda Value Area + POC/VAH/VAL.
Pregatit pentru Faza 3 (fara sa implementeze inca): set_mode("split"/"delta"),
HVN/LVN, hover pe nivel, etichete de volum, highlight zona.

NU calculeaza nimic: primeste profilul deja calculat (bin_price/bin_buy/bin_sell/
poc/vah/val/hvn/lvn/total) — reutilizeaza engine-urile existente prin SessionStore.
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from app.desktop import theme


class VolumeProfileView(QtWidgets.QWidget):
    """Randare a unui profil intr-un plot propriu (pret pe Y, volum pe X).

    API (stabil pentru Faza 3):
      set_profile(profile | None)  -> deseneaza / goleste
      set_mode(mode)               -> "total" (Faza 1) | "split"/"delta" (Faza 3)
      clear()                      -> goleste
    """

    MODES = ("total", "split", "delta")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "total"
        self._profile = None
        self._row_size = 2.0

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.BG)
        self.plot.showAxis("right"); self.plot.hideAxis("left"); self.plot.hideAxis("bottom")
        vb = self.plot.getViewBox()
        vb.setMenuEnabled(False)
        vb.setMouseEnabled(x=False, y=True)      # zoom/pan doar pe pret
        vb.setDefaultPadding(0.0)
        ax = self.plot.getAxis("right")
        ax.setTextPen(theme.TEXT_DIM); ax.setPen(pg.mkPen(theme.BORDER, width=1))
        ax.setStyle(tickLength=-4)
        lay.addWidget(self.plot)

        # Banda Value Area (in spate)
        self._va_band = pg.LinearRegionItem(orientation="horizontal", movable=False,
                                            brush=pg.mkBrush(*theme.VA_BAND))
        self._va_band.setZValue(-10); self._va_band.setVisible(False)
        self.plot.addItem(self._va_band)

        # Barele volum-la-pret (BarGraphItem nativ = fara paint custom)
        self._bars = pg.BarGraphItem(x0=0, y=[0], height=0, width=[0], pen=pg.mkPen(None))
        self._bars.setZValue(-5)
        self.plot.addItem(self._bars)

        # Linii POC / VAH / VAL — doar marcaje vizuale pe histograma (magenta POC, slate
        # punctat VA). Valorile numerice apar in eticheta cardului (POC/VAH/VAL), nu ca
        # pastile pe grafic -> fara text redundant / taiat la margine (UX curat).
        def mk(color, width, dash):
            ln = pg.InfiniteLine(angle=0, movable=False,
                                 pen=pg.mkPen(color, width=width, style=dash))
            ln.setVisible(False); self.plot.addItem(ln)
            return ln
        self._lines = {
            "poc": mk(theme.POC, 3, QtCore.Qt.SolidLine),
            "vah": mk(theme.VA_LINE, 1, QtCore.Qt.DashLine),
            "val": mk(theme.VA_LINE, 1, QtCore.Qt.DashLine),
        }

        # Stare goala: text centrat, fara date
        self._empty = pg.TextItem("— fără date —", color=theme.TEXT_DIM, anchor=(0.5, 0.5))
        self._empty.setZValue(20); self._empty.setVisible(False)
        self.plot.addItem(self._empty, ignoreBounds=True)

        self._show_empty()

    # ---------- API public ----------
    def set_mode(self, mode):
        """Faza 1 implementeaza doar 'total'. 'split'/'delta' vor veni in Faza 3 —
        acceptate acum ca sa nu schimbam semnatura, dar randate tot ca 'total'."""
        if mode in self.MODES:
            self._mode = mode
            self._redraw()

    def set_profile(self, profile, row_size=None):
        """profile = dict de la period_profiles/SessionStore (sau None pentru gol)."""
        self._profile = profile
        if row_size is not None:
            self._row_size = float(row_size)
        self._redraw()

    def clear(self):
        self.set_profile(None)

    def current_levels(self):
        """(poc, vah, val) ale profilului curent sau (None, None, None)."""
        p = self._profile
        if not p:
            return None, None, None
        return p.get("poc"), p.get("vah"), p.get("val")

    # ---------- randare interna ----------
    def _redraw(self):
        p = self._profile
        bp = p.get("bin_price") if p else None
        if p is None or bp is None or not len(bp):
            self._show_empty()
            return
        self._empty.setVisible(False)

        prices = np.asarray(bp, dtype=float)
        totals = np.asarray(p["bin_buy"], dtype=float) + np.asarray(p["bin_sell"], dtype=float)
        poc = p.get("poc"); vah = p.get("vah"); val = p.get("val")

        brushes = self._brushes_for(prices, poc, vah, val)
        h = self._row_size * 0.9
        self._bars.setOpts(x0=0, y=prices, height=h, width=totals, brushes=brushes,
                           pen=pg.mkPen(None))

        # Banda Value Area + linii
        if val is not None and vah is not None and val <= vah:
            self._va_band.setRegion((val, vah)); self._va_band.setVisible(True)
        else:
            self._va_band.setVisible(False)
        for key, y in (("poc", poc), ("vah", vah), ("val", val)):
            ln = self._lines[key]
            if y is not None:
                ln.setPos(y); ln.setVisible(True)
            else:
                ln.setVisible(False)

        # Range: pret pe Y (fit cu padding), volum pe X de la 0
        pmin, pmax = float(prices.min()), float(prices.max())
        pad = max((pmax - pmin) * 0.04, self._row_size)
        maxtot = float(totals.max()) if len(totals) and totals.max() > 0 else 1.0
        self.plot.setYRange(pmin - pad, pmax + pad, padding=0)
        self.plot.setXRange(0, maxtot * 1.08, padding=0)

    def _brushes_for(self, prices, poc, vah, val):
        """Culoare per bara: baza discreta; barele din Value Area mai luminoase; POC accent.
        (Faza 3 va comuta aici pe split buy/sell sau delta.)"""
        base = QtGui.QColor(*theme.VP_BASE); base.setAlpha(150)
        va = QtGui.QColor(*theme.VP_VA); va.setAlpha(205)
        poc_c = QtGui.QColor(theme.POC); poc_c.setAlpha(220)
        base_b, va_b, poc_b = pg.mkBrush(base), pg.mkBrush(va), pg.mkBrush(poc_c)
        tol = self._row_size / 2.0
        out = []
        for price in prices:
            if poc is not None and abs(price - poc) <= tol:
                out.append(poc_b)
            elif val is not None and vah is not None and (val - tol) <= price <= (vah + tol):
                out.append(va_b)
            else:
                out.append(base_b)
        return out

    def _show_empty(self):
        self._bars.setOpts(x0=0, y=[0], height=0, width=[0])
        self._va_band.setVisible(False)
        for ln in self._lines.values():
            ln.setVisible(False)
        self.plot.setXRange(0, 1, padding=0)
        self.plot.setYRange(0, 1, padding=0)
        self._empty.setPos(0.5, 0.5)
        self._empty.setVisible(True)
