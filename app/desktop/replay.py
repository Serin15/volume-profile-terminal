"""
Replay TICK-BY-TICK - redă o sesiune ca și cum ar fi live: lumânarea curentă se
FORMEAZĂ tick cu tick (open fix, high/low se întind, close se mișcă), iar profilul,
delta, footprint și VWAP se dezvoltă în timp real. Lumânările trecute rămân fixe.

Avansează cu un număr de tick-uri pe cadru (controlat de viteză), deci vezi
lumânarea crescând, exact ca pe o platformă reală.
"""

import copy

import numpy as np

from core import VolumeProfileEngine, DeltaEngine
from app.desktop.data_service import (DayData, _top_nodes, detect_absorption,
                                      detect_exhaustion, detect_level_reactions,
                                      BIG_TRADE_MIN, _detector_defaults)

CHECKPOINT_EVERY = 40   # salvam starea la fiecare N lumanari -> seek inapoi rapid


class Replay:
    def __init__(self, full: DayData, df, va_percent, row_size,
                 big_trade_min=BIG_TRADE_MIN, abs_params=None, exh_params=None,
                 lvn_full_profile=False):
        self.full = full
        self.va = va_percent
        self.row_size = row_size
        self.bar = full.bar_seconds
        self._abs_params = abs_params or {}
        self._exh_params = exh_params or {}
        # praguri absorption/exhaustion adaptate la interval (base) + override-uri din ⚙
        self._abs_base, self._exh_base = _detector_defaults(self.bar)
        self._lvn_full = lvn_full_profile

        d = df.sort_values("ts", kind="stable")
        self.prices = d["price"].to_numpy()
        self.sizes = d["size"].to_numpy()
        self.sides = d["side"].astype(str).to_numpy()
        tsec = (d["ts"].astype("int64") // 10**9).to_numpy()
        self.cepoch = (tsec // self.bar) * self.bar   # epoca lumânării pentru fiecare tick
        self.n = len(self.prices)
        self.cidx_of = {int(round(e)): i for i, e in enumerate(full.t)}
        self._big_idx = np.where(self.sizes >= big_trade_min)[0]  # indici tranzactii mari
        # Speed of tape: nr. de print-uri (trade-uri) per lumanare, aliniat la full.t
        # (folosit pentru randul T/s din grid, developing tick-cu-tick in replay).
        if len(self.cepoch):
            uniq, cnt = np.unique(self.cepoch, return_counts=True)
            cmap = {int(u): int(c) for u, c in zip(uniq, cnt)}
            self._full_counts = np.array([cmap.get(int(round(e)), 0) for e in full.t], dtype=float)
        else:
            self._full_counts = np.zeros(len(full.t))
        # Pentru fiecare lumânare, cursorul (nr. de tick-uri) la finalul ei -> seek rapid
        self.candle_end = np.searchsorted(self.cepoch, full.t.astype("int64"), side="right")
        self.n_candles = len(full.t)
        self._ckpts = None      # checkpoints {cursor: state}, construite lazy la primul seek inapoi
        self.reset()

    def reset(self):
        self.cursor = 0
        self.vp = VolumeProfileEngine(tick_size=self.row_size)
        self.de = DeltaEngine(tick_size=self.row_size)
        self.cur_epoch = None
        self.cur_o = self.cur_h = self.cur_l = self.cur_c = 0.0
        self.cur_vol = 0.0
        self.cur_fp = {}

    def at_end(self):
        return self.cursor >= self.n

    def _feed_tick(self, k):
        """Proceseaza un singur tick k in engine-uri + lumanarea in formare."""
        rs = self.row_size
        price = float(self.prices[k]); size = float(self.sizes[k])
        side = self.sides[k]; ep = int(self.cepoch[k])
        self.vp.add_tick(price, size)
        self.de.add_tick(price, size, side)
        if ep != self.cur_epoch:                    # a început o lumânare nouă
            self.cur_epoch = ep
            self.cur_o = self.cur_h = self.cur_l = self.cur_c = price
            self.cur_vol = 0.0
            self.cur_fp = {}
        else:
            self.cur_h = max(self.cur_h, price)
            self.cur_l = min(self.cur_l, price)
            self.cur_c = price
        self.cur_vol += size
        cell = self.cur_fp.setdefault(round(round(price / rs) * rs, 4), [0.0, 0.0])
        sn = side.strip().upper()[:1] if side else ""
        if sn == "B":
            cell[0] += size
        elif sn == "A":
            cell[1] += size

    def step(self, n_ticks):
        """Hrănește următoarele n_ticks tick-uri; lumânarea curentă se formează live."""
        if self.at_end():
            return None
        end = min(self.cursor + int(n_ticks), self.n)
        for k in range(self.cursor, end):
            self._feed_tick(k)
        self.cursor = end
        return self._snapshot()

    # ---- Checkpoints pentru seek INAPOI rapid ----
    def _capture(self):
        return (self.cursor, copy.deepcopy(self.vp), copy.deepcopy(self.de),
                self.cur_epoch, self.cur_o, self.cur_h, self.cur_l, self.cur_c,
                self.cur_vol, copy.deepcopy(self.cur_fp))

    def _restore(self, st):
        (self.cursor, vp, de, self.cur_epoch, self.cur_o, self.cur_h,
         self.cur_l, self.cur_c, self.cur_vol, fp) = st
        self.vp = copy.deepcopy(vp)
        self.de = copy.deepcopy(de)
        self.cur_fp = copy.deepcopy(fp)

    def _build_checkpoints(self):
        """O singura trecere pe sesiune, salvand starea la fiecare CHECKPOINT_EVERY lumanari."""
        self.reset()
        self._ckpts = {}
        save_at = {int(self.candle_end[j])
                   for j in range(0, self.n_candles, CHECKPOINT_EVERY)}
        last = max(save_at) if save_at else 0
        for k in range(self.n):
            self._feed_tick(k)
            c = k + 1
            if c in save_at:
                self.cursor = c
                self._ckpts[c] = self._capture()
            if c >= last:
                break
        self.reset()

    def current_candle_index(self):
        """Indexul (in sesiune) al lumanarii curente (in formare)."""
        return self.cidx_of.get(self.cur_epoch, 0)

    def seek_candle(self, j):
        """
        Sare la lumanarea j: o formeaza complet (toate tick-urile ei), gata de a fi
        vazuta. Merge INAINTE (incremental de la cursorul curent) sau INAPOI
        (reconstruieste de la zero pana acolo). Returneaza snapshot-ul.
        """
        j = max(0, min(int(j), self.n_candles - 1))
        target = int(self.candle_end[j])
        if target == self.cursor:
            return self._snapshot()                    # deja acolo
        # +1/+2 lumanari inainte: step direct (ieftin), fara sa construim checkpoints
        small_fwd = 0 < (target - self.cursor) and (j - self.current_candle_index()) <= 2
        if not small_fwd and self._ckpts is None:
            self._build_checkpoints()
        # Cel mai bun punct de pornire <= target: cursorul curent (daca e <= target)
        # sau cel mai apropiat checkpoint. Merge si inainte (jump mare) si inapoi.
        best = self.cursor if self.cursor <= target else -1
        best_state = None
        if self._ckpts:
            for c, st in self._ckpts.items():
                if best < c <= target:
                    best, best_state = c, st
        if best_state is not None:
            self._restore(best_state)
        elif best == -1:
            self.reset()
        if target > self.cursor:
            return self.step(target - self.cursor)
        return self._snapshot()

    def _snapshot(self) -> DayData:
        f = self.full
        cc = self.cidx_of.get(self.cur_epoch, 0)   # indexul lumânării în formare
        nc = cc                                     # lumânări deja închise: 0..cc-1

        t = np.append(f.t[:nc], float(self.cur_epoch))
        o = np.append(f.open[:nc], self.cur_o)
        h = np.append(f.high[:nc], self.cur_h)
        l = np.append(f.low[:nc], self.cur_l)
        c = np.append(f.close[:nc], self.cur_c)
        vol = np.append(f.volume[:nc], self.cur_vol)

        typ = (h + l + c) / 3.0
        cv = np.cumsum(vol)
        vwap = np.cumsum(typ * vol) / np.where(cv == 0, np.nan, cv)

        vpr = self.vp.result(va_percent=self.va)
        der = self.de.result()
        prices = sorted(vpr.profile.keys())
        bin_price = np.array(prices, dtype=float)
        bin_buy = np.empty(len(prices)); bin_sell = np.empty(len(prices))
        for k, p in enumerate(prices):
            total = vpr.profile[p]
            b = der.buy_volume_per_level.get(p, 0.0)
            s = der.sell_volume_per_level.get(p, 0.0)
            bs = b + s
            if bs > 0:
                bin_buy[k] = total * b / bs
                bin_sell[k] = total * s / bs
            else:
                bin_buy[k] = bin_sell[k] = total / 2.0

        node_hvn, node_lvn = self.vp.compute_hvn_lvn_peaks(
            min_prominence_ratio=0.4, lvn_within_hvn=not self._lvn_full)
        hvn, lvn = _top_nodes(node_hvn, node_lvn, vpr.profile,
                              max_lvn=6 if self._lvn_full else 3)

        # Footprint: lumânările închise din full + lumânarea în formare (live)
        fp = {int(round(e)): f.footprint.get(int(round(e)), {}) for e in f.t[:nc]}
        fp[self.cur_epoch] = {p: v for p, v in self.cur_fp.items()}

        pcd = {tt: sum(b - s for (b, s) in cells.values()) for tt, cells in fp.items()}
        cvd = np.cumsum([pcd.get(int(round(tt)), 0.0) for tt in t])

        big = [(int(self.cepoch[k]), float(self.prices[k]), float(self.sizes[k]), self.sides[k])
               for k in self._big_idx if k < self.cursor]

        # Absorption: doar pe lumanarile INCHISE (excludem cea in formare)
        abs0 = detect_absorption(fp, t, h, l, c, self.row_size, exclude_last=True,
                                 **{**self._abs_base, **self._abs_params})
        # Exhaustion: climax pe lumanarile inchise (excludem cea in formare)
        exh0 = detect_exhaustion(fp, t, h, l, c, vol, exclude_last=True,
                                 **{**self._exh_base, **self._exh_params})

        # Developing POC/VA: trail-ul lumanarilor inchise (precalculat, identic) + valoarea
        # curenta a lumanarii in formare -> se dezvolta in replay fara cost per-cadru.
        cur_poc = vpr.poc if vpr.poc is not None else 0.0
        cur_vah = vpr.vah if vpr.vah is not None else 0.0
        cur_val = vpr.val if vpr.val is not None else 0.0
        dev_poc = np.append(f.dev_poc[:nc], cur_poc) if len(f.dev_poc) else np.array([cur_poc])
        dev_vah = np.append(f.dev_vah[:nc], cur_vah) if len(f.dev_vah) else np.array([cur_vah])
        dev_val = np.append(f.dev_val[:nc], cur_val) if len(f.dev_val) else np.array([cur_val])

        # Acceptance/Rejection la marginile VA developing (doar lumanari inchise)
        react0 = detect_level_reactions(t, o, h, l, c, dev_poc, dev_vah, dev_val,
                                        self.row_size, exclude_last=True)

        # Speed of tape (T/s): lumanari inchise = nr. print-uri precalculat; cea in formare =
        # print-urile hranite pana acum (developing, determinist dupa cursor).
        start_cur = int(self.candle_end[cc - 1]) if cc > 0 else 0
        cur_ntrades = float(self.cursor - start_cur)
        tps_closed = self._full_counts[:nc] if len(self._full_counts) else np.zeros(0)
        tps = np.append(tps_closed, cur_ntrades) / self.bar

        return DayData(
            symbol=f.symbol, n_ticks=self.cursor,
            t=t, open=o, high=h, low=l, close=c, volume=vol,
            vwap=vwap, cvd=cvd, last_price=self.cur_c, bar_seconds=self.bar,
            bin_price=bin_price, bin_buy=bin_buy, bin_sell=bin_sell, row_size=self.row_size,
            poc=vpr.poc if vpr.poc is not None else 0.0,
            vah=vpr.vah if vpr.vah is not None else 0.0,
            val=vpr.val if vpr.val is not None else 0.0,
            hvn=hvn, lvn=lvn, total_volume=vpr.total_volume,
            cum_delta=der.cumulative_delta, buy_total=der.total_buy_volume,
            sell_total=der.total_sell_volume,
            mode=f.mode, incomplete=f.incomplete, footprint=fp, big_trades=big,
            absorption=abs0, exhaustion=exh0, level_reactions=react0,
            dev_poc=dev_poc, dev_vah=dev_vah, dev_val=dev_val, tps=tps,
        )
