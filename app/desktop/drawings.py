"""
Unelte de desen pentru backtesting (stil TradingView), pe durata sesiunii curente.

Unelte:
  - Nivel orizontal (hline)  : 1 click  -> linie orizontala mobila la pretul dat
  - Trendline (trend)        : 2 clickuri -> segment mobil (cu manere)
  - Dreptunghi / zona (rect) : 2 clickuri (colturi) -> cutie translucida (supply/demand)
  - Fibonacci (fib)          : 2 clickuri (swing) -> nivelurile fib intre cele doua puncte
  - Masura (measure)         : 2 clickuri -> puncte / ticks / % / minute intre puncte

Cat timp o unealta e armata, pan-ul graficului e dezactivat (ca sa prindem clickurile
curat). Dupa ce desenezi, revine la cursor. Right-click / Esc anuleaza unealta.
Undo scoate ultimul desen, Clear le sterge pe toate. Nimic nu se salveaza pe disc.
"""

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from app.desktop import theme
from app.desktop.data_service import TICK_SIZE

FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
POS_RED = "#e5484d"        # rosu pentru zona/linia de STOP (risc)
NQ_POINT_USD = 20.0        # E-mini NQ: $20 per punct (pentru valoarea $ a trade-ului)


class DrawingManager(QtCore.QObject):
    def __init__(self, plot):
        super().__init__()
        self.plot = plot
        self.vb = plot.getViewBox()
        self.tool = None
        self.pending = []          # puncte click in asteptare
        self.items = []            # desene create (fiecare = item sau lista de items) -> undo/clear
        self._preview = []         # items temporare de preview intre clickuri
        self.on_tool_done = None   # callback catre UI (reseteaza butoanele)
        self.snap_provider = None  # magnet: functie (x,y)->(x,y) lipita de OHLC (cu Ctrl)
        self.on_avwap = None       # callback (x_epoch) -> MainWindow ancoreaza un VWAP

        self._pen = pg.mkPen(theme.ACCENT, width=1.5)
        self._pen_fib = pg.mkPen(theme.VWAP, width=1, style=QtCore.Qt.DashLine)
        self._pen_prev = pg.mkPen(theme.TEXT_DIM, width=1, style=QtCore.Qt.DashLine)

        plot.scene().sigMouseClicked.connect(self._on_click)
        plot.scene().sigMouseMoved.connect(self._on_move)

    # cate clickuri are nevoie fiecare unealta
    NEEDED = {"hline": 1, "trend": 2, "rect": 2, "fib": 2, "measure": 2,
              "long": 3, "short": 3, "avwap": 1}

    # ---------- stare unealta ----------
    def set_tool(self, tool):
        self._clear_preview()
        self.pending = []
        self.tool = tool
        armed = tool is not None
        self.vb.setMouseEnabled(not armed, not armed)   # dezactiveaza pan cat desenam

    def cancel(self):
        self.set_tool(None)
        if self.on_tool_done:
            self.on_tool_done()

    # ---------- magnet (Ctrl) ----------
    def _maybe_snap(self, x, y):
        """Cu Ctrl apasat, lipeste punctul de OHLC-ul celei mai apropiate lumanari (ca pe TV)."""
        if self.snap_provider and (
                QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ControlModifier):
            try:
                return self.snap_provider(x, y)
            except Exception:
                return x, y
        return x, y

    # ---------- input ----------
    def _on_click(self, ev):
        if self.tool is None:
            return
        try:
            btn = ev.button()
        except Exception:
            btn = QtCore.Qt.LeftButton
        if btn == QtCore.Qt.RightButton:
            self.cancel()
            return
        if not self.plot.sceneBoundingRect().contains(ev.scenePos()):
            return
        pt = self.vb.mapSceneToView(ev.scenePos())
        self.add_point(*self._maybe_snap(float(pt.x()), float(pt.y())))

    def _on_move(self, pos):
        if self.tool is None or not self.pending:
            return
        if not self.plot.sceneBoundingRect().contains(pos):
            return
        pt = self.vb.mapSceneToView(pos)
        cur = self._maybe_snap(float(pt.x()), float(pt.y()))
        self._update_preview(self.pending + [cur])

    def add_point(self, x, y):
        """Adauga un punct de click; creeaza desenul cand are suficiente puncte."""
        t = self.tool
        if t is None:
            return
        self.pending.append((x, y))
        if len(self.pending) >= self.NEEDED.get(t, 2):
            pts = self.pending[:self.NEEDED.get(t, 2)]
            if t == "hline":
                self._add_hline(pts)
            elif t == "trend":
                self._add_trend(pts)
            elif t == "rect":
                self._add_rect(pts)
            elif t == "fib":
                self._add_fib(pts)
            elif t == "measure":
                self._add_measure(pts)
            elif t in ("long", "short"):
                self._add_position(pts, t)
            elif t == "avwap":
                # Anchored VWAP: nu-l desenam aici (are nevoie de datele lumanarilor).
                # Trimitem epoca ancorei la MainWindow, care calculeaza + deseneaza.
                if self.on_avwap:
                    self.on_avwap(pts[0][0])
            self._finish()

    def _finish(self):
        self._clear_preview()
        self.pending = []
        self.set_tool(None)
        if self.on_tool_done:
            self.on_tool_done()

    # ---------- preview intre clickuri ----------
    def _clear_preview(self):
        for it in self._preview:
            self.plot.removeItem(it)
        self._preview = []

    def _update_preview(self, pts):
        self._clear_preview()
        if len(pts) < 2:
            return
        p0, p1 = pts[0], pts[-1]
        if self.tool in ("rect", "fib"):
            x0, x1 = sorted((p0[0], p1[0])); y0, y1 = sorted((p0[1], p1[1]))
            r = QtWidgets.QGraphicsRectItem(x0, y0, x1 - x0, y1 - y0)
            r.setPen(self._pen_prev)
            self.plot.addItem(r); self._preview = [r]
        else:   # trend, measure, long, short
            ln = pg.PlotDataItem([p0[0], p1[0]], [p0[1], p1[1]], pen=self._pen_prev)
            self.plot.addItem(ln); self._preview = [ln]

    # ---------- creare desene ----------
    def _register(self, item_or_list):
        self.items.append(item_or_list)

    def _add_hline(self, pts):
        y = pts[0][1]
        ln = pg.InfiniteLine(pos=y, angle=0, movable=True,
                             pen=self._pen, hoverPen=pg.mkPen(theme.ACCENT, width=2.5),
                             label="{value:.2f}",
                             labelOpts={"position": 0.05, "color": "#0a0a0a",
                                        "fill": pg.mkColor(theme.ACCENT), "movable": True})
        ln.setZValue(20)
        self.plot.addItem(ln)
        self._register(ln)

    def _add_trend(self, pts):
        roi = pg.LineSegmentROI([list(pts[0]), list(pts[1])], pen=self._pen)   # editabil (manere)
        roi.setZValue(20)
        self.plot.addItem(roi)
        self._register(roi)

    def _add_rect(self, pts):
        p0, p1 = pts[0], pts[1]
        x0, x1 = sorted((p0[0], p1[0])); y0, y1 = sorted((p0[1], p1[1]))
        roi = pg.RectROI([x0, y0], [max(x1 - x0, 1.0), max(y1 - y0, 0.25)],
                         pen=pg.mkPen(theme.ACCENT, width=1.5), movable=True,
                         resizable=True, rotatable=False)          # editabil: mut + redimensionez
        roi.addScaleHandle([0, 0], [1, 1])
        roi.setZValue(5)
        self.plot.addItem(roi)
        self._register(roi)

    def _add_fib(self, pts):
        p0, p1 = pts[0], pts[1]
        x0, x1 = sorted((p0[0], p1[0]))
        y_a, y_b = p0[1], p1[1]
        group = []
        for lvl in FIB_LEVELS:
            yl = y_a + (y_b - y_a) * lvl
            seg = pg.PlotDataItem([x0, x1], [yl, yl], pen=self._pen_fib)
            seg.setZValue(19)
            self.plot.addItem(seg)
            txt = pg.TextItem(f"{lvl:.3f}  {yl:.2f}", color=theme.VWAP, anchor=(0, 0.5))
            txt.setPos(x1, yl); txt.setZValue(19)
            self.plot.addItem(txt)
            group += [seg, txt]
        self._register(group)

    def _add_measure(self, pts):
        p0, p1 = pts[0], pts[1]
        dpts = p1[1] - p0[1]
        dticks = dpts / TICK_SIZE if TICK_SIZE else 0.0
        pct = (dpts / p0[1] * 100.0) if p0[1] else 0.0
        dmin = (p1[0] - p0[0]) / 60.0
        col = QtGui.QColor(theme.UP if dpts >= 0 else theme.DOWN)
        line = pg.PlotDataItem([p0[0], p1[0]], [p0[1], p1[1]],
                               pen=pg.mkPen(col, width=1.5, style=QtCore.Qt.DashLine))
        line.setZValue(20)
        self.plot.addItem(line)
        fill = QtGui.QColor(col); fill.setAlpha(28)
        x0, x1 = sorted((p0[0], p1[0])); y0, y1 = sorted((p0[1], p1[1]))
        band = QtWidgets.QGraphicsRectItem(x0, y0, x1 - x0, y1 - y0)
        band.setPen(pg.mkPen(None)); band.setBrush(pg.mkBrush(fill))
        band.setZValue(1)
        self.plot.addItem(band)
        label = pg.TextItem(
            f"{dpts:+.2f} pts  ({dticks:+.0f} ticks)\n{pct:+.2f}%   {dmin:+.0f} min",
            color="#0a0a0a", anchor=(0.5, 0.5), fill=pg.mkBrush(col))
        label.setPos((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        label.setZValue(21)
        self.plot.addItem(label)
        self._register([line, band, label])

    def _add_position(self, pts, kind):
        """Simulare trade (ca 'Long/Short Position' pe TV): 3 clickuri = Entry, Stop, Target.
        Zona verde = profit (spre target), rosie = risc (spre stop); eticheta cu puncte + R:R + $."""
        entry, stop, target = pts[0][1], pts[1][1], pts[2][1]
        xs = [p[0] for p in pts]
        x0, x1 = min(xs), max(xs)
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = reward / risk if risk > 1e-9 else 0.0
        green = QtGui.QColor(theme.UP); green.setAlpha(45)
        red = QtGui.QColor(POS_RED); red.setAlpha(45)
        group = []

        def zone(y_from, y_to, brush):
            yy0, yy1 = sorted((y_from, y_to))
            r = QtWidgets.QGraphicsRectItem(x0, yy0, x1 - x0, yy1 - yy0)
            r.setPen(pg.mkPen(None)); r.setBrush(pg.mkBrush(brush)); r.setZValue(1)
            self.plot.addItem(r); group.append(r)

        zone(entry, target, green)     # profit
        zone(entry, stop, red)         # risc
        for y, col, w in ((entry, theme.TEXT, 1.5), (target, theme.UP, 1),
                          (stop, POS_RED, 1)):
            seg = pg.PlotDataItem([x0, x1], [y, y], pen=pg.mkPen(col, width=w))
            seg.setZValue(20); self.plot.addItem(seg); group.append(seg)

        tag = "LONG" if kind == "long" else "SHORT"
        label = pg.TextItem(
            f"{tag}   R:R 1:{rr:.2f}\n"
            f"target +{reward:.2f} pts  (${reward * NQ_POINT_USD:,.0f})\n"
            f"stop  -{risk:.2f} pts  (${risk * NQ_POINT_USD:,.0f})",
            color="#0a0a0a", anchor=(0, 0.5),
            fill=pg.mkBrush(QtGui.QColor(theme.UP if kind == "long" else theme.DOWN)))
        label.setPos(x1, entry); label.setZValue(22)
        self.plot.addItem(label); group.append(label)
        self._register(group)

    # ---------- undo / clear ----------
    def _remove(self, entry):
        if isinstance(entry, list):
            for it in entry:
                self.plot.removeItem(it)
        else:
            self.plot.removeItem(entry)

    def undo(self):
        if self.items:
            self._remove(self.items.pop())

    def clear(self):
        for entry in self.items:
            self._remove(entry)
        self.items = []
