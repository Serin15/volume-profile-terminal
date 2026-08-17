"""
Elemente grafice pyqtgraph desenate manual (rapide, pentru live):
  - CandlestickItem: lumanari OHLC
  - ProfileItem: histograma orizontala de Volume Profile, split buy/sell

Se deseneaza intr-un QPicture o singura data (rapid), se re-deseneaza doar la
schimbarea datelor - potrivit pentru update live incremental mai tarziu.
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui

from app.desktop import theme


class CandlestickItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self.picture = QtGui.QPicture()
        self._bounds = QtCore.QRectF()

    def set_data(self, t, o, h, l, c, bar_seconds):
        w = bar_seconds * 0.82 / 2.0  # jumatate de latime a corpului (mai plin)
        up = QtGui.QColor(theme.UP)
        down = QtGui.QColor(theme.DOWN)
        up_edge = QtGui.QColor(theme.UP_EDGE)
        down_edge = QtGui.QColor(theme.DOWN_EDGE)

        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)  # crisp, nu blur

        for i in range(len(t)):
            bull = c[i] >= o[i]
            fill = up if bull else down
            edge = up_edge if bull else down_edge
            # fitil (high-low) - subtire, culoarea corpului
            p.setPen(pg.mkPen(fill, width=1))
            p.drawLine(QtCore.QPointF(t[i], l[i]), QtCore.QPointF(t[i], h[i]))
            # corp (open-close) - umplut, cu contur mai luminos pentru definire
            top = max(o[i], c[i])
            bot = min(o[i], c[i])
            if top == bot:  # doji - linie orizontala pe latimea corpului
                p.setPen(pg.mkPen(edge, width=1))
                p.drawLine(QtCore.QPointF(t[i] - w, top), QtCore.QPointF(t[i] + w, top))
            else:
                p.setPen(pg.mkPen(edge, width=1))
                p.setBrush(pg.mkBrush(fill))
                p.drawRect(QtCore.QRectF(t[i] - w, bot, 2 * w, top - bot))
        p.end()

        if len(t):
            self._bounds = QtCore.QRectF(
                t.min() - w, float(np.min(l)),
                (t.max() - t.min()) + 2 * w, float(np.max(h) - np.min(l)))
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self._bounds)


class ProfileOverlayItem(pg.GraphicsObject):
    """
    Volume Profile SUPRAPUS peste graficul de pret (stil DeepCharts 1:1).
    Desenat in coordonatele pretului (x=timp, y=pret), ancorat la marginea STANGA
    a vizualizarii curente, translucid, cu bare care se re-scaleaza la pan/zoom.

    Fiecare bara = volumul total la nivel; culoarea e impartita proportional
    buy (verde) / sell (mov). Lungimea = fractiune (width_frac) din latimea vizibila.
    """

    def __init__(self, width_frac=0.22, mode="single", anchor="left", tint=None):
        super().__init__()
        self.width_frac = width_frac
        self.mode = mode          # "single" (o culoare, VA evidentiata) sau "split" (buy/sell)
        self.anchor = anchor      # "left" (implicit) sau "right" (pt sesiunea de comparat)
        self.tint = tint          # (r,g,b) - culoare distincta (compare); None = paleta VP normala
        self.bin_price = None
        self.bin_buy = None
        self.bin_sell = None
        self.row_size = 1.0
        self.max_total = 1.0
        self.va_low = None        # marginile Value Area (pt evidentierea barelor din VA)
        self.va_high = None
        self.poc = None           # nivelul POC (bara accentuata)
        self.picture = QtGui.QPicture()
        self._vb = None

    def attach(self, viewbox):
        """Leaga item-ul de viewbox ca sa se re-deseneze la schimbarea range-ului X."""
        self._vb = viewbox
        viewbox.sigXRangeChanged.connect(self._regen)

    def set_mode(self, mode):
        self.mode = mode
        self._regen()

    def set_data(self, bin_price, bin_buy, bin_sell, row_size,
                 va_low=None, va_high=None, poc=None):
        self.bin_price = np.asarray(bin_price, dtype=float)
        self.bin_buy = np.asarray(bin_buy, dtype=float)
        self.bin_sell = np.asarray(bin_sell, dtype=float)
        self.row_size = row_size
        self.va_low = va_low
        self.va_high = va_high
        self.poc = poc
        totals = self.bin_buy + self.bin_sell
        self.max_total = float(totals.max()) if len(totals) else 1.0
        self._regen()

    def _regen(self, *args):
        if self.bin_price is None or self._vb is None or not len(self.bin_price):
            return
        (xmin, xmax), _ = self._vb.viewRange()
        span = (xmax - xmin) * self.width_frac
        if span <= 0 or self.max_total <= 0:
            return

        h = self.row_size * 0.9
        edge = xmin if self.anchor == "left" else xmax   # de unde pornesc barele
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setPen(pg.mkPen(None))

        if self.mode == "split":
            self._draw_split(p, xmin, span, h)
        else:
            self._draw_single(p, edge, span, h)

        p.end()
        self.prepareGeometryChange()
        self.update()

    def _draw_single(self, p, edge, span, h):
        """O singura culoare calma; barele din Value Area mai luminoase, POC accentuat.
        Ancora 'left' -> barele cresc spre dreapta; 'right' -> spre stanga (sesiunea de comparat)."""
        if self.tint is not None:                        # culoare distincta (compare)
            base = QtGui.QColor(*self.tint); base.setAlpha(70)
            va = QtGui.QColor(*self.tint); va.setAlpha(130)
            poc_c = QtGui.QColor(*self.tint); poc_c.setAlpha(190)
        else:
            base = QtGui.QColor(*theme.VP_BASE); base.setAlpha(120)
            va = QtGui.QColor(*theme.VP_VA); va.setAlpha(165)
            poc_c = QtGui.QColor(theme.POC); poc_c.setAlpha(175)
        base_brush, va_brush, poc_brush = pg.mkBrush(base), pg.mkBrush(va), pg.mkBrush(poc_c)
        lo = self.va_low if self.va_low is not None else None
        hi = self.va_high if self.va_high is not None else None
        left = self.anchor == "left"
        # toleranta = jumatate de rand ca sa prindem exact bara POC/marginile VA
        tol = self.row_size / 2.0
        for i in range(len(self.bin_price)):
            price = self.bin_price[i]
            total = self.bin_buy[i] + self.bin_sell[i]
            if total <= 0:
                continue
            w = (total / self.max_total) * span
            y = price - h / 2.0
            if self.poc is not None and abs(price - self.poc) <= tol:
                p.setBrush(poc_brush)
            elif lo is not None and (lo - tol) <= price <= (hi + tol):
                p.setBrush(va_brush)
            else:
                p.setBrush(base_brush)
            x = edge if left else edge - w
            p.drawRect(QtCore.QRectF(x, y, w, h))

    def _draw_split(self, p, xmin, span, h):
        """Mod clasic: bara verde (buy) + mov (sell) stivuite proportional per nivel."""
        buy_c = QtGui.QColor(theme.BUY); buy_c.setAlpha(90)
        sell_c = QtGui.QColor(theme.SELL); sell_c.setAlpha(90)
        buy_brush, sell_brush = pg.mkBrush(buy_c), pg.mkBrush(sell_c)
        for i in range(len(self.bin_price)):
            buy = self.bin_buy[i]
            sell = self.bin_sell[i]
            total = buy + sell
            if total <= 0:
                continue
            w = (total / self.max_total) * span
            wb = (buy / total) * w
            y = self.bin_price[i] - h / 2.0
            if wb > 0:
                p.setBrush(buy_brush)
                p.drawRect(QtCore.QRectF(xmin, y, wb, h))
            if w - wb > 0:
                p.setBrush(sell_brush)
                p.drawRect(QtCore.QRectF(xmin + wb, y, w - wb, h))

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self.picture.boundingRect())


class FootprintItem(pg.GraphicsObject):
    """
    Footprint (stil DeepCharts "Deep Print"): pentru fiecare lumanare si nivel de
    pret, o celula colorata dupa imbalance (verde = cumparare agresiva domina, mov
    = vanzare domina), intensitatea = volumul. Cand dai ZOOM suficient, in fiecare
    celula apar NUMERELE "sell x buy" (text fix-size, ascuns automat cand e prea mic).
    """

    def __init__(self):
        super().__init__()
        self._bounds = QtCore.QRectF()
        self._fp = {}             # {epoca_lumanare: {pret: [buy, sell]}}
        self._deltas = {}         # {epoca_lumanare: delta total (impuls)}
        self._max_total = 1.0
        self._row_size = 0.25
        self._w = 1.0             # latime celula (secunde)
        self._h = 1.0             # inaltime celula (puncte pret)
        self._vb = None
        self._imb_ratio = 3.0     # prag imbalance (dominanta) - reglabil din UI
        self._imb_minvol = 12     # volum minim celula pt imbalance - reglabil din UI
        self._mode = "bidask"     # "bidask" (bare bid/ask) | "volume" | "delta"
        self._shape = "cells"     # "cells" (casute patrate) | "bubbles" (pastile rotunjite, stil DeepChart)
        self._max_side = 1.0      # max volum pe o singura latura (normalizare bare/delta)
        # Pen-uri + brush-uri PRE-CALCULATE (nu alocam nimic per celula in paint)
        self._no_pen = pg.mkPen(None)
        self._no_brush = QtGui.QBrush(QtCore.Qt.NoBrush)
        # Bare interne bid/ask (pline) + fundal faint celula (mod "bidask" la zoom)
        cbar = QtGui.QColor(theme.BUY); cbar.setAlpha(230); self._bar_buy = pg.mkBrush(cbar)
        sbar = QtGui.QColor(theme.SELL); sbar.setAlpha(230); self._bar_sell = pg.mkBrush(sbar)
        self._cell_bg = pg.mkBrush(QtGui.QColor(255, 255, 255, 10))
        self._buy_imb_pen = QtGui.QPen(QtGui.QColor(theme.UP_EDGE)); self._buy_imb_pen.setWidthF(1.7); self._buy_imb_pen.setCosmetic(True)
        self._sell_imb_pen = QtGui.QPen(QtGui.QColor(theme.DOWN_EDGE)); self._sell_imb_pen.setWidthF(1.7); self._sell_imb_pen.setCosmetic(True)
        # POC per lumanare (nivelul cu volumul cel mai mare din bara) - contur magenta (ca linia POC)
        self._poc_pen = QtGui.QPen(QtGui.QColor(theme.POC)); self._poc_pen.setWidthF(1.8); self._poc_pen.setCosmetic(True)
        self._poc_of = {}         # {epoca_lumanare: pret POC (nivelul cu volum maxim din bara)}
        # Numere colorate dupa cine domina in celula: buy verde / sell mov / egal neutru
        self._num_buy_pen = pg.mkPen(theme.UP_EDGE)
        self._num_sell_pen = pg.mkPen(theme.DOWN_EDGE)
        self._num_neutral_pen = pg.mkPen(theme.TEXT_DIM)
        # Pool de brush-uri pe niveluri de alpha (intensitate volum) -> reutilizate
        self._BUCKETS = 24
        self._buy_brushes = []
        self._sell_brushes = []
        self._vol_brushes = []    # mod "volume": o culoare neutra, intensitate dupa volum
        for i in range(self._BUCKETS):
            a = int(45 + 195 * (i / (self._BUCKETS - 1)))
            cb = QtGui.QColor(theme.BUY); cb.setAlpha(a); self._buy_brushes.append(pg.mkBrush(cb))
            cs = QtGui.QColor(theme.SELL); cs.setAlpha(a); self._sell_brushes.append(pg.mkBrush(cs))
            cv = QtGui.QColor(150, 168, 198); cv.setAlpha(a); self._vol_brushes.append(pg.mkBrush(cv))

    def set_mode(self, mode):
        self._mode = mode
        self.update()

    def set_shape(self, shape):
        """'cells' = casute patrate (clasic) | 'bubbles' = pastile rotunjite (stil DeepChart)."""
        self._shape = shape
        self.update()

    def attach(self, viewbox):
        """Re-deseneaza la zoom/pan (viewport culling: doar celulele vizibile)."""
        self._vb = viewbox
        viewbox.sigRangeChanged.connect(lambda *a: self.update())

    def set_data(self, footprint, bar_seconds, row_size):
        # NU desenam aici (fara QPicture cu 58k celule) - doar stocam + o singura
        # trecere pentru max_total, bounds si delta/lumanare. Desenul e in paint(),
        # cull-uit la fereastra vizibila -> nu mai redesenam mii de celule off-screen.
        self._fp = footprint
        self._w = bar_seconds * 0.9
        self._h = row_size * 0.92
        self._row_size = row_size

        mt = 1.0
        ms = 1.0
        tmin = tmax = pmin = pmax = None
        deltas = {}
        poc_of = {}
        for t, cells in footprint.items():
            if tmin is None or t < tmin: tmin = t
            if tmax is None or t > tmax: tmax = t
            dsum = 0.0
            best_p, best_v = None, -1.0
            for price, (buy, sell) in cells.items():
                s = buy + sell
                if s > mt: mt = s
                if buy > ms: ms = buy
                if sell > ms: ms = sell
                dsum += buy - sell
                if s > best_v: best_v, best_p = s, price      # POC per lumanare
                if pmin is None or price < pmin: pmin = price
                if pmax is None or price > pmax: pmax = price
            deltas[int(t)] = dsum
            poc_of[int(t)] = best_p
        self._max_total = mt
        self._max_side = ms
        self._deltas = deltas
        self._poc_of = poc_of

        if tmin is not None:
            w, h = self._w, self._h
            self._bounds = QtCore.QRectF(tmin - w, pmin - h,
                                         (tmax - tmin) + 2 * w, (pmax - pmin) + 2 * h)
        else:
            self._bounds = QtCore.QRectF()

        self.prepareGeometryChange()
        self.update()

    def paint(self, p, *args):
        if self._vb is None or not self._fp:
            return
        (xmin, xmax), (ymin, ymax) = self._vb.viewRange()
        w, h, rs = self._w, self._h, self._row_size
        inv = 1.0 / self._max_total
        xlo, xhi = xmin - w, xmax + w
        ylo, yhi = ymin - h, ymax + h
        RATIO, MIN_VOL = self._imb_ratio, self._imb_minvol
        mode = self._mode
        is_bubbles = self._shape == "bubbles"
        # Marimea celulei pe ecran (px), o singura data -> decide bare / imbalance / numere
        try:
            xscale, yscale = self._vb.viewPixelSize()
        except Exception:
            xscale = yscale = 0.0
        cell_px_w = self._w / xscale if xscale > 0 else 0.0
        cell_px_h = self._h / yscale if yscale > 0 else 0.0
        draw_imb = (mode == "bidask") and cell_px_w >= 3 and cell_px_h >= 3
        show_bars = (mode == "bidask") and cell_px_w >= 16 and cell_px_h >= 3   # bare bid/ask la zoom
        no_pen, no_brush = self._no_pen, self._no_brush
        buy_brushes, sell_brushes, vol_brushes = self._buy_brushes, self._sell_brushes, self._vol_brushes
        nb = self._BUCKETS - 1
        inv_side = 1.0 / self._max_side
        half, bar_h = w / 2.0, h * 0.82

        # Celulele VIZIBILE: doar lumanarile din fereastra, doar nivelurile din fereastra.
        # Brush-uri din pool (fara alocare), pen pus o data (schimbat doar pe imbalance).
        p.setPen(no_pen)
        pen_is_no = True
        for t, cells in self._fp.items():
            if t < xlo or t > xhi:
                continue
            for price, (buy, sell) in cells.items():
                if price < ylo or price > yhi:
                    continue
                total = buy + sell
                if total <= 0:
                    continue
                if not pen_is_no:
                    p.setPen(no_pen); pen_is_no = True
                rect = QtCore.QRectF(t - w / 2, price - h / 2, w, h)
                if is_bubbles:
                    # Stil "bule" (DeepChart): pastila rotunjita, culoarea dominantei
                    # (buy verde / sell mov), intensitate dupa volumul total la nivel.
                    xr, yr = w * 0.42, h * 0.45
                    bucket = int(min(1.0, total * inv) * nb)
                    p.setBrush((buy_brushes if buy >= sell else sell_brushes)[bucket])
                    p.drawRoundedRect(rect, xr, yr)
                    if draw_imb:
                        sell_below = cells.get(round(price - rs, 4), (0.0, 0.0))[1]
                        buy_above = cells.get(round(price + rs, 4), (0.0, 0.0))[0]
                        if buy >= MIN_VOL and buy >= RATIO * sell_below:
                            p.setPen(self._buy_imb_pen); p.setBrush(no_brush)
                            p.drawRoundedRect(rect, xr, yr); pen_is_no = False
                        elif sell >= MIN_VOL and sell >= RATIO * buy_above:
                            p.setPen(self._sell_imb_pen); p.setBrush(no_brush)
                            p.drawRoundedRect(rect, xr, yr); pen_is_no = False
                    if self._poc_of.get(t) == price:   # POC per lumanare (contur magenta)
                        p.setPen(self._poc_pen); p.setBrush(no_brush)
                        p.drawRoundedRect(rect, xr, yr); pen_is_no = False
                    continue
                if show_bars:
                    # Bare interne bid/ask (stil Quantower): fundal faint + bara sell (stanga)
                    # / buy (dreapta) din centru, lungime proportionala cu volumul laturii.
                    p.setBrush(self._cell_bg); p.drawRect(rect)
                    y0 = price - bar_h / 2.0
                    sw = sell * inv_side * half; sw = half if sw > half else sw
                    bw = buy * inv_side * half; bw = half if bw > half else bw
                    if sw > 0:
                        p.setBrush(self._bar_sell); p.drawRect(QtCore.QRectF(t - sw, y0, sw, bar_h))
                    if bw > 0:
                        p.setBrush(self._bar_buy); p.drawRect(QtCore.QRectF(t, y0, bw, bar_h))
                elif mode == "volume":
                    bucket = int(min(1.0, total * inv) * nb)
                    p.setBrush(vol_brushes[bucket]); p.drawRect(rect)
                elif mode == "delta":
                    d = buy - sell
                    bucket = int(min(1.0, abs(d) * inv_side) * nb)   # intensitate dupa |delta|
                    p.setBrush((buy_brushes if d >= 0 else sell_brushes)[bucket]); p.drawRect(rect)
                else:   # "bidask" la zoom-out: celula plina, culoarea dominantei
                    bucket = int(min(1.0, total * inv) * nb)
                    p.setBrush((buy_brushes if buy >= sell else sell_brushes)[bucket]); p.drawRect(rect)
                if not draw_imb:
                    continue
                sell_below = cells.get(round(price - rs, 4), (0.0, 0.0))[1]
                buy_above = cells.get(round(price + rs, 4), (0.0, 0.0))[0]
                if buy >= MIN_VOL and buy >= RATIO * sell_below:
                    p.setPen(self._buy_imb_pen); p.setBrush(no_brush); p.drawRect(rect); pen_is_no = False
                elif sell >= MIN_VOL and sell >= RATIO * buy_above:
                    p.setPen(self._sell_imb_pen); p.setBrush(no_brush); p.drawRect(rect); pen_is_no = False
                if self._poc_of.get(t) == price:   # POC per lumanare: contur magenta (nivelul cu volum max)
                    p.setPen(self._poc_pen); p.setBrush(no_brush); p.drawRect(rect); pen_is_no = False

        # Numerele + delta/lumanare - doar cand celula e destul de mare pe ecran (zoom)
        if xscale <= 0 or yscale <= 0:
            return
        show_numbers = cell_px_w >= (20 if is_bubbles else 30) and cell_px_h >= 7
        if not show_numbers:
            return

        tr = p.transform()
        p.save()
        p.resetTransform()

        # Numerele "sell x buy", colorate dupa cine domina (buy verde / sell mov / egal neutru).
        # Delta pe lumanare NU se mai deseneaza aici - e in randul ΔV din grid (evitam dublura).
        font = QtGui.QFont()
        font.setPixelSize(int(max(7, min(13, cell_px_h * 0.75))))
        p.setFont(font)
        for t, cells in self._fp.items():
            if t < xlo or t > xhi:
                continue
            for price, (buy, sell) in cells.items():
                if price < ylo or price > yhi:
                    continue
                if buy > sell:
                    p.setPen(self._num_buy_pen)
                elif sell > buy:
                    p.setPen(self._num_sell_pen)
                else:
                    p.setPen(self._num_neutral_pen)
                dev = tr.map(QtCore.QPointF(t, price))
                rect = QtCore.QRectF(dev.x() - cell_px_w / 2, dev.y() - cell_px_h / 2,
                                     cell_px_w, cell_px_h)
                txt = f"{int(buy + sell)}" if is_bubbles else f"{int(sell)}x{int(buy)}"
                p.drawText(rect, QtCore.Qt.AlignCenter, txt)

        p.restore()

    def boundingRect(self):
        return QtCore.QRectF(self._bounds)


class ProfileItem(pg.GraphicsObject):
    """Histograma orizontala: pentru fiecare nivel, bara verde (buy) + rosie (sell) stivuite."""

    def __init__(self):
        super().__init__()
        self.picture = QtGui.QPicture()
        self._bounds = QtCore.QRectF()

    def set_data(self, bin_price, bin_buy, bin_sell, row_size):
        h = row_size * 0.88
        buy_brush = pg.mkBrush(QtGui.QColor(theme.BUY))
        sell_brush = pg.mkBrush(QtGui.QColor(theme.SELL))
        no_pen = pg.mkPen(None)

        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setPen(no_pen)

        max_total = 0.0
        for i in range(len(bin_price)):
            y = bin_price[i] - h / 2.0
            buy = float(bin_buy[i])
            sell = float(bin_sell[i])
            if buy > 0:
                p.setBrush(buy_brush)
                p.drawRect(QtCore.QRectF(0, y, buy, h))
            if sell > 0:
                p.setBrush(sell_brush)
                p.drawRect(QtCore.QRectF(buy, y, sell, h))
            max_total = max(max_total, buy + sell)
        p.end()

        if len(bin_price):
            self._bounds = QtCore.QRectF(
                0, float(bin_price.min() - row_size),
                max_total, float(bin_price.max() - bin_price.min() + 2 * row_size))
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self._bounds)


def _fmt_k(v):
    """Formateaza un volum compact: 1234 -> 1.2K, 12345 -> 12K."""
    a = abs(v)
    if a >= 1000:
        return (f"{v/1000:.1f}K" if a < 10000 else f"{v/1000:.0f}K").replace(".0K", "K")
    return f"{v:.0f}"


class StatsAxis(pg.AxisItem):
    """Axa stanga a grid-ului de statistici: etichete fixe T/s / ΣV / ΔV / Δ% pe cele 4 randuri."""
    _LABELS = {3.5: "T/s", 2.5: "ΣV", 1.5: "ΔV", 0.5: "Δ%"}

    def tickValues(self, minVal, maxVal, size):
        return [(1.0, [3.5, 2.5, 1.5, 0.5])]

    def tickStrings(self, values, scale, spacing):
        return [self._LABELS.get(round(v, 1), "") for v in values]


class GridStatsItem(pg.GraphicsObject):
    """
    Grid de statistici per lumanare (jos, stil DeepCharts/Sierra): ΣV (volum total),
    ΔV (delta buy-sell), Δ% (delta / volum) ca heatmap + T/s (viteza tape-ului) ca
    HISTOGRAMA - inaltimea barei = print-uri/secunda, culoarea = semnul delta (verde buy /
    mov sell), stil DeepChart. Numerele apar la zoom. Randuri: T/s sus (y 3..4),
    ΣV (2..3), ΔV (1..2), Δ% jos (0..1).
    """

    def __init__(self):
        super().__init__()
        self._t = self._vol = self._dv = self._dpct = self._tps = None
        self._w = 1.0
        self._vb = None
        self._maxvol = 1.0
        self._maxdv = 1.0
        self._maxtps = 1.0
        self._bounds = QtCore.QRectF(0, 0, 1, 4)
        self._BUCKETS = 20
        self._vol_br, self._pos_br, self._neg_br = [], [], []
        for i in range(self._BUCKETS):
            # heatmap mai discret (max ~144, nu 220) -> panoul de jos nu mai concureaza cu lumanarile
            a = int(26 + 118 * (i / (self._BUCKETS - 1)))
            cv = QtGui.QColor(120, 135, 162); cv.setAlpha(a); self._vol_br.append(pg.mkBrush(cv))
            cp = QtGui.QColor(theme.BUY); cp.setAlpha(a); self._pos_br.append(pg.mkBrush(cp))
            cn = QtGui.QColor(theme.SELL); cn.setAlpha(a); self._neg_br.append(pg.mkBrush(cn))

    def attach(self, viewbox):
        self._vb = viewbox
        viewbox.sigXRangeChanged.connect(lambda *a: self.update())

    def set_data(self, t, volume, delta_v, bar_seconds, tps=None):
        self._t = np.asarray(t, dtype=float)
        self._vol = np.asarray(volume, dtype=float)
        self._dv = np.asarray(delta_v, dtype=float)
        self._tps = (np.asarray(tps, dtype=float) if tps is not None
                     else np.zeros(len(self._t)))
        self._w = bar_seconds * 0.9
        with np.errstate(divide="ignore", invalid="ignore"):
            self._dpct = np.where(self._vol > 0, self._dv / self._vol * 100.0, 0.0)
        self._maxvol = float(self._vol.max()) if len(self._vol) else 1.0
        self._maxdv = float(np.abs(self._dv).max()) if len(self._dv) else 1.0
        self._maxtps = float(self._tps.max()) if len(self._tps) else 1.0
        if len(self._t):
            self._bounds = QtCore.QRectF(self._t.min() - self._w, 0,
                                         (self._t.max() - self._t.min()) + 2 * self._w, 4)
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, *args):
        if self._t is None or not len(self._t) or self._vb is None:
            return
        (xmin, xmax), _ = self._vb.viewRange()
        w = self._w
        xlo, xhi = xmin - w, xmax + w
        nb = self._BUCKETS - 1
        iv = 1.0 / self._maxvol if self._maxvol > 0 else 0.0
        idv = 1.0 / self._maxdv if self._maxdv > 0 else 0.0
        itps = 1.0 / self._maxtps if self._maxtps > 0 else 0.0
        has_tps = self._tps is not None and len(self._tps) == len(self._t)
        p.setPen(pg.mkPen(None))
        for i in range(len(self._t)):
            t = self._t[i]
            if t < xlo or t > xhi:
                continue
            x = t - w / 2.0
            vol = self._vol[i]; dv = self._dv[i]; dp = self._dpct[i]
            if has_tps:
                frac = min(1.0, self._tps[i] * itps)                   # inaltime bara = viteza tape
                if frac > 0:                                            # culoare = semnul delta (cine conduce)
                    p.setBrush((self._pos_br if self._dv[i] >= 0 else self._neg_br)[int(frac * nb)])
                    p.drawRect(QtCore.QRectF(x, 3, w, frac))            # histograma: creste de la baza randului
            p.setBrush(self._vol_br[int(min(1.0, vol * iv) * nb)])
            p.drawRect(QtCore.QRectF(x, 2, w, 1))                       # ΣV
            p.setBrush((self._pos_br if dv >= 0 else self._neg_br)[int(min(1.0, abs(dv) * idv) * nb)])
            p.drawRect(QtCore.QRectF(x, 1, w, 1))                       # ΔV
            p.setBrush((self._pos_br if dp >= 0 else self._neg_br)[int(min(1.0, abs(dp) / 60.0) * nb)])
            p.drawRect(QtCore.QRectF(x, 0, w, 1))                       # Δ% (60% = intens max)

        # Numerele - doar cand celula e destul de larga pe ecran
        try:
            xscale, _ = self._vb.viewPixelSize()
        except Exception:
            return
        if xscale <= 0:
            return
        cw = w / xscale
        if cw < 34:
            return
        tr = p.transform(); p.save(); p.resetTransform()
        font = QtGui.QFont(); font.setPixelSize(9); p.setFont(font)
        for i in range(len(self._t)):
            t = self._t[i]
            if t < xlo or t > xhi:
                continue
            tps_s = f"{self._tps[i]:.0f}/s" if (self._tps is not None
                                                and len(self._tps) == len(self._t)) else ""
            vals = ((3.5, tps_s, theme.BUY if self._dv[i] >= 0 else theme.SELL),
                    (2.5, _fmt_k(self._vol[i]), theme.TEXT),
                    (1.5, f"{int(round(self._dv[i])):+d}", theme.BUY if self._dv[i] >= 0 else theme.SELL),
                    (0.5, f"{self._dpct[i]:+.0f}%", theme.BUY if self._dpct[i] >= 0 else theme.SELL))
            for row, s, col in vals:
                dev = tr.map(QtCore.QPointF(float(t), row))
                p.setPen(pg.mkPen(col))
                p.drawText(QtCore.QRectF(dev.x() - cw / 2, dev.y() - 7, cw, 14),
                           QtCore.Qt.AlignCenter, s)
        p.restore()

    def boundingRect(self):
        return QtCore.QRectF(self._bounds)


class PeriodProfilesItem(pg.GraphicsObject):
    """
    Mod "Profile Only" (stil DeepCharts): mai multe Volume Profile-uri, fiecare pozitionat
    pe axa TIMPULUI la perioada lui ([x0, x1] epoci UTC), histograma orizontala split
    buy (verde) / sell (mov), POC accentuat. Fara lumanari. Culling la viewport ca
    FootprintItem (deseneaza doar profilele + nivelurile vizibile).

    Datele vin din data_service.period_profiles(): list de dict cu
    {label, x0, x1, bin_price, bin_buy, bin_sell, poc, ...}.
    """

    def __init__(self):
        super().__init__()
        self._profiles = []
        self._row_size = 2.0
        self._vb = None
        self._bounds = QtCore.QRectF()
        buy = QtGui.QColor(theme.BUY); buy.setAlpha(175)
        sell = QtGui.QColor(theme.SELL); sell.setAlpha(175)
        self._buy_brush = pg.mkBrush(buy)
        self._sell_brush = pg.mkBrush(sell)
        self._no_pen = pg.mkPen(None)
        self._no_brush = QtGui.QBrush(QtCore.Qt.NoBrush)
        self._poc_pen = QtGui.QPen(QtGui.QColor(theme.POC))
        self._poc_pen.setWidthF(1.6); self._poc_pen.setCosmetic(True)
        self._div_pen = QtGui.QPen(QtGui.QColor(theme.BORDER)); self._div_pen.setCosmetic(True)
        self._lbl_pen = pg.mkPen(theme.TEXT_DIM)

    def attach(self, viewbox):
        self._vb = viewbox
        viewbox.sigRangeChanged.connect(lambda *a: self.update())

    def set_data(self, profiles, row_size):
        self._profiles = profiles or []
        self._row_size = row_size
        xmin = xmax = pmin = pmax = None
        for pr in self._profiles:
            bp = pr.get("bin_price")
            if bp is None or not len(bp):
                pr["_max"] = 1.0; continue
            tot = pr["bin_buy"] + pr["bin_sell"]
            pr["_max"] = float(tot.max()) if len(tot) and tot.max() > 0 else 1.0
            x0, x1 = pr["x0"], pr["x1"]
            lo, hi = float(bp.min()), float(bp.max())
            xmin = x0 if xmin is None else min(xmin, x0)
            xmax = x1 if xmax is None else max(xmax, x1)
            pmin = lo if pmin is None else min(pmin, lo)
            pmax = hi if pmax is None else max(pmax, hi)
        if xmin is not None:
            h = row_size
            self._bounds = QtCore.QRectF(xmin, pmin - h, (xmax - xmin), (pmax - pmin) + 2 * h)
        else:
            self._bounds = QtCore.QRectF()
        self.prepareGeometryChange()
        self.update()

    def data_bounds(self):
        """(xmin, xmax, pmin, pmax) al tuturor profilelor (pt auto-range) sau None."""
        if self._bounds.isNull():
            return None
        b = self._bounds
        return b.left(), b.right(), b.top(), b.bottom()

    def paint(self, p, *args):
        if self._vb is None or not self._profiles:
            return
        (xmin, xmax), (ymin, ymax) = self._vb.viewRange()
        h = self._row_size * 0.92
        for pr in self._profiles:
            x0, x1 = pr["x0"], pr["x1"]
            if x1 < xmin or x0 > xmax:
                continue
            bp = pr.get("bin_price")
            if bp is None or not len(bp):
                continue
            bb, bs = pr["bin_buy"], pr["bin_sell"]
            slot = (x1 - x0) * 0.9
            inv = 1.0 / pr.get("_max", 1.0)
            poc = pr.get("poc")
            # divider faint la inceputul perioadei (separa profilele, ca in poza)
            p.setPen(self._div_pen)
            p.drawLine(QtCore.QPointF(x0, ymin), QtCore.QPointF(x0, ymax))
            p.setPen(self._no_pen)
            for i in range(len(bp)):
                price = float(bp[i])
                if price < ymin - h or price > ymax + h:
                    continue
                buy = float(bb[i]); sell = float(bs[i]); total = buy + sell
                if total <= 0:
                    continue
                w = total * inv * slot
                wb = (buy / total) * w
                y = price - h / 2.0
                if wb > 0:
                    p.setBrush(self._buy_brush); p.drawRect(QtCore.QRectF(x0, y, wb, h))
                if w - wb > 0:
                    p.setBrush(self._sell_brush); p.drawRect(QtCore.QRectF(x0 + wb, y, w - wb, h))
                if poc is not None and abs(price - poc) <= self._row_size / 2.0:
                    p.setPen(self._poc_pen); p.setBrush(self._no_brush)
                    p.drawRect(QtCore.QRectF(x0, y, max(w, slot * 0.06), h))
                    p.setPen(self._no_pen)
        # Etichete (data / sesiune) sus, doar cand perioada e destul de lata pe ecran
        try:
            xscale, _ = self._vb.viewPixelSize()
        except Exception:
            return
        if xscale <= 0:
            return
        tr = p.transform(); p.save(); p.resetTransform()
        font = QtGui.QFont(); font.setPixelSize(9); p.setFont(font); p.setPen(self._lbl_pen)
        for pr in self._profiles:
            x0, x1 = pr["x0"], pr["x1"]
            if x1 < xmin or x0 > xmax:
                continue
            if (x1 - x0) / xscale < 34:
                continue
            dev = tr.map(QtCore.QPointF((x0 + x1) / 2.0, ymax))
            p.drawText(QtCore.QRectF(dev.x() - 60, dev.y() + 2, 120, 12),
                       QtCore.Qt.AlignCenter, str(pr.get("label", "")))
        p.restore()

    def boundingRect(self):
        return QtCore.QRectF(self._bounds)
