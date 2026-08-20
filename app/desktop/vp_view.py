"""
VolumeProfileView — Volume Profile PROFESIONAL, reutilizabil (Faza 3)
--------------------------------------------------------------------
Deseneaza UN profil (dict de la SessionStore/period_profiles sau causal din snapshot)
intr-un plot dedicat, cu axa de pret proprie. Trei moduri de citire:

  TOTAL  — volum-la-pret clasic, curat (implicit). VA evidentiata, POC accent.
  SPLIT  — Buy (verde) + Sell (mov) stivuite pe fiecare nivel (compozitia per pret).
  DELTA  — delta = buy - sell per nivel, bare divergente din centru (verde dreapta /
           mov stanga). Accent pe cine a dominat la fiecare pret.

Plus: linii POC/VAH/VAL + banda Value Area, marcaje HVN/LVN, si HOVER pe nivel
(tooltip discret: Price/Total/Buy/Sell/Delta + POC/VA/HVN/LVN + highlight subtil).

Principii: claritate > informatie > efecte. NU calculeaza nimic — primeste profilul
deja calculat (bin_buy/bin_sell/poc/vah/val/hvn/lvn/total). Reutilizeaza engine-urile
prin datele de intrare; nu atinge vp_engine/delta_engine/Replay/SessionStore.
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from app.desktop import theme


class VolumeProfileView(QtWidgets.QWidget):
    MODES = ("total", "split", "delta")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "total"
        self._profile = None
        self._row_size = 2.0
        self._levels = {}          # {pret: (total, buy, sell)} — lookup pt hover

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

        # Doua seturi de bare (BarGraphItem nativ, fara paint custom):
        #   _bars  = TOTAL / BUY (in split) / DELTA
        #   _bars2 = SELL (doar in split, stivuit peste buy)
        self._bars = pg.BarGraphItem(x0=0, y=[0], height=0, width=[0], pen=pg.mkPen(None))
        self._bars2 = pg.BarGraphItem(x0=0, y=[0], height=0, width=[0], pen=pg.mkPen(None))
        self._bars.setZValue(-5); self._bars2.setZValue(-5)
        self.plot.addItem(self._bars); self.plot.addItem(self._bars2)

        # Linia de zero pentru DELTA (verticala la x=0)
        self._delta_zero = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                           pen=pg.mkPen(theme.BORDER, width=1))
        self._delta_zero.setVisible(False); self.plot.addItem(self._delta_zero)

        # Linii POC / VAH / VAL — marcaje vizuale (valorile numerice sunt in eticheta cardului)
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
        self._node_lines = []      # HVN/LVN — numar variabil, recreate la fiecare profil

        # Hover: linie de highlight (subtila) + tooltip discret
        hc = QtGui.QColor(255, 255, 255); hc.setAlpha(46)
        self._hover_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(hc, width=8))
        self._hover_line.setZValue(8); self._hover_line.setVisible(False)
        self.plot.addItem(self._hover_line)
        self._hover_tip = pg.TextItem(color=theme.TEXT, anchor=(0, 1),
                                      fill=pg.mkBrush(18, 20, 26, 235),
                                      border=pg.mkPen(theme.BORDER))
        self._hover_tip.setZValue(30); self._hover_tip.setVisible(False)
        self.plot.addItem(self._hover_tip, ignoreBounds=True)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Stare goala
        self._empty = pg.TextItem("— fără date —", color=theme.TEXT_DIM, anchor=(0.5, 0.5))
        self._empty.setZValue(20); self._empty.setVisible(False)
        self.plot.addItem(self._empty, ignoreBounds=True)
        self._show_empty()

    # ================= API public =================
    def set_mode(self, mode):
        """TOTAL (implicit) / SPLIT / DELTA. Doar RE-DESENARE — nu recalculeaza profilul."""
        if mode in self.MODES and mode != self._mode:
            self._mode = mode
            self._redraw()

    def mode(self):
        return self._mode

    def set_profile(self, profile, row_size=None):
        self._profile = profile
        if row_size is not None:
            self._row_size = float(row_size)
        self._redraw()

    def clear(self):
        self.set_profile(None)

    def current_levels(self):
        p = self._profile
        if not p:
            return None, None, None
        return p.get("poc"), p.get("vah"), p.get("val")

    def level_at(self, price):
        """Datele nivelului cel mai apropiat de `price` (pt hover SI teste). None daca
        nu exista un nivel in raza de o jumatate de rand."""
        if not self._levels:
            return None
        tol = self._row_size / 2.0
        best = min(self._levels.keys(), key=lambda pr: abs(pr - price))
        if abs(best - price) > tol + 1e-9:
            return None
        total, buy, sell = self._levels[best]
        p = self._profile or {}
        poc, vah, val = p.get("poc"), p.get("vah"), p.get("val")

        def near(seq):
            return any(abs(best - x) <= tol for x in (seq or []))
        return {
            "price": best, "total": total, "buy": buy, "sell": sell, "delta": buy - sell,
            "is_poc": poc is not None and abs(best - poc) <= tol,
            "in_va": val is not None and vah is not None and (val - tol) <= best <= (vah + tol),
            "is_hvn": near(p.get("hvn")), "is_lvn": near(p.get("lvn")),
        }

    def node_line_count(self):
        return len(self._node_lines)

    # ================= randare =================
    def _redraw(self):
        p = self._profile
        bp = p.get("bin_price") if p else None
        if p is None or bp is None or not len(bp):
            self._show_empty()
            return
        self._empty.setVisible(False)

        prices = np.asarray(bp, dtype=float)
        buy = np.asarray(p["bin_buy"], dtype=float)
        sell = np.asarray(p["bin_sell"], dtype=float)
        total = buy + sell
        poc, vah, val = p.get("poc"), p.get("vah"), p.get("val")
        self._levels = {round(float(pr), 4): (float(t), float(b), float(s))
                        for pr, b, s, t in zip(prices, buy, sell, total)}

        if self._mode == "split":
            self._draw_split(prices, buy, sell)
        elif self._mode == "delta":
            self._draw_delta(prices, buy, sell)
        else:
            self._draw_total(prices, total, poc, vah, val)

        # Referinte (toate modurile): banda VA + linii POC/VAH/VAL + noduri HVN/LVN
        if val is not None and vah is not None and val <= vah:
            self._va_band.setRegion((val, vah)); self._va_band.setVisible(True)
        else:
            self._va_band.setVisible(False)
        for key, y in (("poc", poc), ("vah", vah), ("val", val)):
            ln = self._lines[key]
            ln.setVisible(y is not None)
            if y is not None:
                ln.setPos(y)
        self._set_nodes(p.get("hvn") or [], p.get("lvn") or [])
        self._hover_line.setVisible(False); self._hover_tip.setVisible(False)
        self._apply_range(prices, total, buy, sell)

    def _draw_total(self, prices, total, poc, vah, val):
        h = self._row_size * 0.9
        self._bars.setOpts(x0=0, y=prices, height=h, width=total,
                           brushes=self._brushes_total(prices, poc, vah, val), pen=pg.mkPen(None))
        self._bars2.setOpts(x0=0, y=[0], height=0, width=[0])
        self._delta_zero.setVisible(False)

    def _draw_split(self, prices, buy, sell):
        h = self._row_size * 0.9
        buy_c = QtGui.QColor(theme.BUY); buy_c.setAlpha(200)
        sell_c = QtGui.QColor(theme.SELL); sell_c.setAlpha(200)
        # brushes=None -> curata o eventuala lista per-bara ramasa din TOTAL/DELTA
        self._bars.setOpts(x0=0, y=prices, height=h, width=buy,
                           brush=pg.mkBrush(buy_c), brushes=None, pen=pg.mkPen(None))
        self._bars2.setOpts(x0=buy, y=prices, height=h, width=sell,
                            brush=pg.mkBrush(sell_c), brushes=None, pen=pg.mkPen(None))
        self._delta_zero.setVisible(False)

    def _draw_delta(self, prices, buy, sell):
        h = self._row_size * 0.9
        delta = buy - sell
        x0 = np.minimum(0.0, delta)
        width = np.abs(delta)
        buy_c = QtGui.QColor(theme.BUY); buy_c.setAlpha(200)
        sell_c = QtGui.QColor(theme.SELL); sell_c.setAlpha(200)
        brushes = [pg.mkBrush(buy_c) if d >= 0 else pg.mkBrush(sell_c) for d in delta]
        self._bars.setOpts(x0=x0, y=prices, height=h, width=width, brushes=brushes, pen=pg.mkPen(None))
        self._bars2.setOpts(x0=0, y=[0], height=0, width=[0])
        self._delta_zero.setVisible(True)

    def _brushes_total(self, prices, poc, vah, val):
        """Culoare per bara (TOTAL): baza discreta; VA mai luminos; POC accent."""
        base = QtGui.QColor(*theme.VP_BASE); base.setAlpha(150)
        va = QtGui.QColor(*theme.VP_VA); va.setAlpha(205)
        poc_c = QtGui.QColor(theme.POC); poc_c.setAlpha(220)
        base_b, va_b, poc_b = pg.mkBrush(base), pg.mkBrush(va), pg.mkBrush(poc_c)
        tol = self._row_size / 2.0
        out = []
        for pr in prices:
            if poc is not None and abs(pr - poc) <= tol:
                out.append(poc_b)
            elif val is not None and vah is not None and (val - tol) <= pr <= (vah + tol):
                out.append(va_b)
            else:
                out.append(base_b)
        return out

    def _apply_range(self, prices, total, buy, sell):
        pmin, pmax = float(prices.min()), float(prices.max())
        pad = max((pmax - pmin) * 0.04, self._row_size)
        self.plot.setYRange(pmin - pad, pmax + pad, padding=0)
        if self._mode == "delta":
            m = float(np.abs(buy - sell).max()) if len(prices) else 1.0
            m = m if m > 0 else 1.0
            self.plot.setXRange(-m * 1.08, m * 1.08, padding=0)
        else:
            maxtot = float(total.max()) if len(total) and total.max() > 0 else 1.0
            self.plot.setXRange(0, maxtot * 1.08, padding=0)

    def _set_nodes(self, hvn, lvn):
        """HVN (cyan plin, subtil) / LVN (gri punctat). Doar nodurile de la engine (<=9).
        Diferentiate clar; discrete ca sa nu concureze cu barele."""
        for ln in self._node_lines:
            self.plot.removeItem(ln)
        self._node_lines = []
        hvn_c = QtGui.QColor(theme.HVN); hvn_c.setAlpha(120)
        lvn_c = QtGui.QColor(theme.LVN); lvn_c.setAlpha(120)
        for y in hvn:
            ln = pg.InfiniteLine(pos=y, angle=0, movable=False, pen=pg.mkPen(hvn_c, width=1))
            ln.setZValue(-3); self.plot.addItem(ln); self._node_lines.append(ln)
        for y in lvn:
            ln = pg.InfiniteLine(pos=y, angle=0, movable=False,
                                 pen=pg.mkPen(lvn_c, width=1, style=QtCore.Qt.DotLine))
            ln.setZValue(-3); self.plot.addItem(ln); self._node_lines.append(ln)

    def _show_empty(self):
        self._bars.setOpts(x0=0, y=[0], height=0, width=[0])
        self._bars2.setOpts(x0=0, y=[0], height=0, width=[0])
        self._va_band.setVisible(False); self._delta_zero.setVisible(False)
        for ln in self._lines.values():
            ln.setVisible(False)
        self._set_nodes([], [])
        self._hover_line.setVisible(False); self._hover_tip.setVisible(False)
        self._levels = {}
        self.plot.setXRange(0, 1, padding=0); self.plot.setYRange(0, 1, padding=0)
        self._empty.setPos(0.5, 0.5); self._empty.setVisible(True)

    # ================= hover =================
    def _on_mouse_moved(self, pos):
        vb = self.plot.getViewBox()
        if not self._levels or not self.plot.sceneBoundingRect().contains(pos):
            self._hover_line.setVisible(False); self._hover_tip.setVisible(False)
            return
        pt = vb.mapSceneToView(pos)
        info = self.level_at(pt.y())
        if info is None:
            self._hover_line.setVisible(False); self._hover_tip.setVisible(False)
            return
        self._hover_line.setPos(info["price"]); self._hover_line.setVisible(True)
        tags = []
        if info["is_poc"]: tags.append("POC")
        if info["in_va"]: tags.append("VA")
        if info["is_hvn"]: tags.append("HVN")
        if info["is_lvn"]: tags.append("LVN")
        d = info["delta"]
        txt = (f"Price: {info['price']:,.2f}\n"
               f"Total: {int(info['total']):,}\n"
               f"Buy:   {int(info['buy']):,}\n"
               f"Sell:  {int(info['sell']):,}\n"
               f"Delta: {int(d):+,}")
        if tags:
            txt += "\n" + " · ".join(tags)
        self._hover_tip.setText(txt)
        # ancoram tooltip-ul ca sa ramana in cadru (stanga/dreapta dupa pozitia cursorului)
        (x0, x1), (y0, y1) = vb.viewRange()
        ax = 0.0 if pt.x() < (x0 + x1) / 2.0 else 1.0
        ay = 0.0 if pt.y() > (y0 + y1) / 2.0 else 1.0
        self._hover_tip.setAnchor((ax, ay))
        self._hover_tip.setPos(pt.x(), info["price"])
        self._hover_tip.setVisible(True)
