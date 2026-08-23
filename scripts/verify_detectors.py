"""
P8 — VERIFY DETECTORS: harness de verificare pentru markerele de ORDER FLOW de pe chart
(Big Trades / Absorption / Exhaustion / Acceptance-Rejection din `data_service`).

De ce exista: markerele pe care le vezi si le bifezi in bara ORDER FLOW folosesc detectori
PROPRII (`_big_trades`, `detect_absorption`, `detect_exhaustion`, `detect_level_reactions`),
separati de motorul `context_engine`. Acest harness ii verifica IN INTREGIME, pe date reale.

Doua straturi:

  STRAT 1 — INVARIANTI (CORECTITUDINE, automat): fiecare detectie e RE-VERIFICATA din datele
    brute (footprint + OHLC + dev VAH/VAL) fata de DEFINITIA ei, cu pragurile EXACTE folosite
    de aplicatie. Verifica: extrema corecta, clauzele de prag, delta/volum raportate corect,
    epoca aliniata la o lumanare, dedupe. Orice incalcare = BUG REAL -> harness-ul iese != 0.

  STRAT 2 — JURNAL + OUTCOME (CALIBRARE, pt ochi uman): fiecare detectie cu ora RO (DST-aware),
    pret, numerele declansatoare, sesiunea (RTH NY vs overnight) si ce a facut pretul in
    urmatoarele N bare (follow-through in directia asteptata). Asa vezi daca detectorii se
    aprind pe lucrurile POTRIVITE (ex: exhaustion overnight vs pe NY open).

NU e semnal / scor / BUY-SELL. Doar verifica ca detectorii fac exact ce spun ca fac.

Rulare:
    .venv\\Scripts\\python.exe scripts/verify_detectors.py                    # zile default, 1min
    .venv\\Scripts\\python.exe scripts/verify_detectors.py 20260817 20260818  # zile alese
    .venv\\Scripts\\python.exe scripts/verify_detectors.py --interval 1min --bars 10 --show all
"""
import argparse
import datetime
import sys
from zoneinfo import ZoneInfo

import numpy as np

try:                                  # consola Windows e cp1252 -> fortam UTF-8 pt Δ/✓/✗
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.desktop.data_service import (load_day, BIG_TRADE_MIN, _detector_defaults,
                                      INTERVAL_SECONDS, ABS_DOM, ABS_REJECT, ABS_ZONE)

TICK = 0.25                       # NQ tick size (pt outcome in ticks)
TZ_RO = ZoneInfo("Europe/Bucharest")
TZ_NY = ZoneInfo("America/New_York")
EPS = 1e-6

# Zile default (recente, cu date reale). Suprascrise de argumentele din linia de comanda.
DEFAULT_DAYS = ["20260817", "20260818", "20260819", "20260820", "20260821"]


# ------------------------------------------------------------------ utilitare timp/sesiune
def _ro(ep):
    return datetime.datetime.fromtimestamp(int(ep), TZ_RO).strftime("%H:%M")


def _et(ep):
    return datetime.datetime.fromtimestamp(int(ep), TZ_NY)


def _session(ep):
    """RTH = sesiunea de cash NY (09:30-16:00 ET); restul = overnight."""
    t = _et(ep)
    mins = t.hour * 60 + t.minute
    return "RTH" if (9 * 60 + 30) <= mins < (16 * 60) else "overnight"


def _index_map(day):
    return {int(round(e)): i for i, e in enumerate(day.t)}


# ================================================================== STRAT 1 — INVARIANTI
def check_big_trades(day, min_size):
    """Big Trade: size >= prag, side valid, epoca = lumanare reala, pret in [low, high]."""
    viol, idx = [], _index_map(day)
    for (ep, price, size, side) in day.big_trades:
        tag = f"big {_ro(ep)}@{price:.2f}"
        if size < min_size:
            viol.append(f"{tag}: size {size:.0f} < prag {min_size}")
        if side not in ("B", "A"):
            viol.append(f"{tag}: side '{side}' invalid (nu B/A)")
        i = idx.get(int(round(ep)))
        if i is None:
            viol.append(f"{tag}: epoca {int(ep)} nu corespunde niciunei lumanari")
            continue
        if not (day.low[i] - EPS <= price <= day.high[i] + EPS):
            viol.append(f"{tag}: pret in afara [low {day.low[i]:.2f}, high {day.high[i]:.2f}]")
    return viol


def check_absorption(day, min_vol, frac, dom=ABS_DOM, reject=ABS_REJECT, zone=ABS_ZONE):
    """Absorption re-verificat din footprint: extrema corecta, dominanta agresorului,
    concentrare, respingere (close), si buy/sell raportate = sumele din zona."""
    viol, idx = [], _index_map(day)
    for (ep, price, kind, buyv, sellv) in day.absorption:
        tag = f"abs {kind} {_ro(ep)}@{price:.2f}"
        i = idx.get(int(round(ep)))
        cells = day.footprint.get(int(round(ep)))
        if i is None or not cells:
            viol.append(f"{tag}: epoca/footprint lipsa")
            continue
        h, l, c = float(day.high[i]), float(day.low[i]), float(day.close[i])
        rng = h - l
        if rng <= 0:
            viol.append(f"{tag}: range <= 0")
            continue
        v_total = sum(b + s for (b, s) in cells.values())
        prices = sorted(cells.keys())
        low_zone, high_zone = prices[:zone], prices[-zone:]
        buy_lo = sum(cells[p][0] for p in low_zone); sell_lo = sum(cells[p][1] for p in low_zone)
        buy_hi = sum(cells[p][0] for p in high_zone); sell_hi = sum(cells[p][1] for p in high_zone)
        if kind == "bull":
            if abs(price - l) > EPS:
                viol.append(f"{tag}: pret raportat {price:.2f} != low {l:.2f}")
            if not (sell_lo >= min_vol):
                viol.append(f"{tag}: sell zona {sell_lo:.0f} < min_vol {min_vol}")
            if not (sell_lo >= dom * buy_lo):
                viol.append(f"{tag}: sell {sell_lo:.0f} nu domina buy {buy_lo:.0f} (x{dom})")
            if not (sell_lo >= frac * v_total):
                viol.append(f"{tag}: sell {sell_lo:.0f} < {frac:.0%} din volum {v_total:.0f}")
            if not ((c - l) / rng >= reject):
                viol.append(f"{tag}: close nu e sus ({(c-l)/rng:.2f} < reject {reject})")
            if abs(buyv - buy_lo) > EPS or abs(sellv - sell_lo) > EPS:
                viol.append(f"{tag}: buy/sell raportate ({buyv:.0f}/{sellv:.0f}) != zona ({buy_lo:.0f}/{sell_lo:.0f})")
        elif kind == "bear":
            if abs(price - h) > EPS:
                viol.append(f"{tag}: pret raportat {price:.2f} != high {h:.2f}")
            if not (buy_hi >= min_vol):
                viol.append(f"{tag}: buy zona {buy_hi:.0f} < min_vol {min_vol}")
            if not (buy_hi >= dom * sell_hi):
                viol.append(f"{tag}: buy {buy_hi:.0f} nu domina sell {sell_hi:.0f} (x{dom})")
            if not (buy_hi >= frac * v_total):
                viol.append(f"{tag}: buy {buy_hi:.0f} < {frac:.0%} din volum {v_total:.0f}")
            if not ((h - c) / rng >= reject):
                viol.append(f"{tag}: close nu e jos ({(h-c)/rng:.2f} < reject {reject})")
            if abs(buyv - buy_hi) > EPS or abs(sellv - sell_hi) > EPS:
                viol.append(f"{tag}: buy/sell raportate ({buyv:.0f}/{sellv:.0f}) != zona ({buy_hi:.0f}/{sell_hi:.0f})")
        else:
            viol.append(f"{tag}: kind necunoscut '{kind}'")
    return viol


def check_exhaustion(day, window, vol_mult, delta_frac, min_vol=0):
    """Exhaustion re-verificat: extrema NOUA pe fereastra, climax de volum (absolut + relativ),
    delta in trend, si volum/delta raportate = cele ale barei."""
    viol, idx = [], _index_map(day)
    hi, lo, vol = np.asarray(day.high, float), np.asarray(day.low, float), np.asarray(day.volume, float)
    for (ep, price, kind, v, delta) in day.exhaustion:
        tag = f"exh {kind} {_ro(ep)}@{price:.2f}"
        i = idx.get(int(round(ep)))
        cells = day.footprint.get(int(round(ep)))
        if i is None or not cells:
            viol.append(f"{tag}: epoca/footprint lipsa")
            continue
        if i < window:
            viol.append(f"{tag}: bara {i} < window {window} (nu se putea evalua)")
            continue
        med = float(np.median(vol[i - window:i]))
        bar_delta = sum(b - s for (b, s) in cells.values())
        if abs(v - vol[i]) > EPS:
            viol.append(f"{tag}: volum raportat {v:.0f} != volum bara {vol[i]:.0f}")
        if abs(delta - bar_delta) > EPS:
            viol.append(f"{tag}: delta raportata {delta:.0f} != delta bara {bar_delta:.0f}")
        if vol[i] < min_vol:
            viol.append(f"{tag}: sub pragul absolut (vol {vol[i]:.0f} < min_vol {min_vol})")
        if not (med > 0 and vol[i] >= vol_mult * med):
            viol.append(f"{tag}: nu e climax (vol {vol[i]:.0f} < {vol_mult}x mediana {med:.0f})")
        new_high = hi[i] >= hi[i - window:i + 1].max() - 1e-9
        new_low = lo[i] <= lo[i - window:i + 1].min() + 1e-9
        if kind == "top":
            if abs(price - hi[i]) > EPS:
                viol.append(f"{tag}: pret {price:.2f} != high {hi[i]:.2f}")
            if not new_high:
                viol.append(f"{tag}: nu e maxim nou pe {window} bare")
            if not (delta > 0 and delta >= delta_frac * v):
                viol.append(f"{tag}: delta {delta:.0f} nu e >0 si >= {delta_frac:.0%} din vol {v:.0f}")
        elif kind == "bot":
            if abs(price - lo[i]) > EPS:
                viol.append(f"{tag}: pret {price:.2f} != low {lo[i]:.2f}")
            if not new_low:
                viol.append(f"{tag}: nu e minim nou pe {window} bare")
            if not (delta < 0 and -delta >= delta_frac * v):
                viol.append(f"{tag}: delta {delta:.0f} nu e <0 si |.| >= {delta_frac:.0%} din vol {v:.0f}")
        else:
            viol.append(f"{tag}: kind necunoscut '{kind}'")
    return viol


def check_reactions(day, lookback=20, poke_ratio=0.35, accept_ratio=0.5, min_sep=5):
    """Acc/Rej re-verificat din OHLC + dev VAH/VAL: relatia se potriveste cu tipul,
    nivelul (vah/val) corect, si separarea minima (dedupe global) respectata."""
    viol, idx = [], _index_map(day)
    dev_vah = np.asarray(getattr(day, "dev_vah", []), float)
    dev_val = np.asarray(getattr(day, "dev_val", []), float)
    rng_series = np.asarray(day.high, float) - np.asarray(day.low, float)
    prev_i = None
    for (ep, price, kind, lvl) in day.level_reactions:
        tag = f"react {kind} {_ro(ep)}@{price:.2f}"
        i = idx.get(int(round(ep)))
        if i is None or i >= len(dev_vah):
            viol.append(f"{tag}: epoca/dev lipsa")
            continue
        if prev_i is not None and (i - prev_i) < min_sep:
            viol.append(f"{tag}: separare {i - prev_i} < min_sep {min_sep} (dedupe incalcat)")
        prev_i = i
        seg = rng_series[max(0, i - lookback):i]
        rng = float(np.median(seg)) if len(seg) else 0.0
        if rng <= 0:
            viol.append(f"{tag}: range median <= 0")
            continue
        poke, acc, tol = poke_ratio * rng, accept_ratio * rng, 0.5 * day.row_size
        oi, hh, ll, cc = float(day.open[i]), float(day.high[i]), float(day.low[i]), float(day.close[i])
        vah, val = float(dev_vah[i]), float(dev_val[i])
        ok = False
        if kind == "rejection_down":     # respins la VAH (bearish): wick peste VAH, close inapoi sub
            ok = vah > 0 and hh > vah + poke and cc < vah - tol
            if abs(price - vah) > EPS or lvl != "vah":
                viol.append(f"{tag}: nivel raportat {price:.2f}/{lvl} != VAH {vah:.2f}")
        elif kind == "rejection_up":     # respins la VAL (bullish)
            ok = val > 0 and ll < val - poke and cc > val + tol
            if abs(price - val) > EPS or lvl != "val":
                viol.append(f"{tag}: nivel raportat {price:.2f}/{lvl} != VAL {val:.2f}")
        elif kind == "acceptance_up":     # acceptat peste VAH (bullish)
            ok = vah > 0 and oi <= vah + tol and cc > vah + acc
            if abs(price - vah) > EPS or lvl != "vah":
                viol.append(f"{tag}: nivel raportat {price:.2f}/{lvl} != VAH {vah:.2f}")
        elif kind == "acceptance_down":   # acceptat sub VAL (bearish)
            ok = val > 0 and oi >= val - tol and cc < val - acc
            if abs(price - val) > EPS or lvl != "val":
                viol.append(f"{tag}: nivel raportat {price:.2f}/{lvl} != VAL {val:.2f}")
        else:
            viol.append(f"{tag}: kind necunoscut '{kind}'")
            continue
        if not ok:
            viol.append(f"{tag}: conditia OHLC-vs-VA nu se confirma (O{oi:.2f} H{hh:.2f} L{ll:.2f} C{cc:.2f} vah{vah:.2f} val{val:.2f})")
    return viol


# ================================================================== STRAT 2 — OUTCOME
# directia "asteptata" a follow-through-ului (DOAR pt validare, NU semnal)
_EXPECTED = {
    ("abs", "bull"): +1, ("abs", "bear"): -1,
    ("exh", "bot"): +1, ("exh", "top"): -1,
    "rejection_up": +1, "acceptance_up": +1,
    "rejection_down": -1, "acceptance_down": -1,
}


def outcome_after(day, i, n):
    """Ce a facut pretul in urmatoarele n bare (DOAR validare). Net + excursii, in ticks."""
    last = len(day.close) - 1
    j = min(i + n, last)
    if j <= i:
        return None
    net = (float(day.close[j]) - float(day.close[i])) / TICK
    up = (float(np.max(day.high[i:j + 1])) - float(day.close[i])) / TICK
    dn = (float(day.close[i]) - float(np.min(day.low[i:j + 1]))) / TICK
    if abs(net) < max(up, dn) * 0.4:
        label = "rotational"
    else:
        label = "up" if net > 0 else "down"
    return dict(net=net, up=up, dn=dn, label=label, bars=j - i)


# ================================================================== RAPORT
def verify_day(day, interval, bars):
    """Ruleaza ambele straturi pe o zi. Returneaza dict cu violari + detectii adnotate."""
    bar_sec = INTERVAL_SECONDS[interval]
    abs_base, exh_base = _detector_defaults(bar_sec)
    idx = _index_map(day)

    viol = {
        "big": check_big_trades(day, BIG_TRADE_MIN),
        "abs": check_absorption(day, abs_base["min_vol"], abs_base["frac"]),
        "exh": check_exhaustion(day, exh_base["window"], exh_base["vol_mult"], exh_base["delta_frac"],
                                exh_base.get("min_vol", 0)),
        "react": check_reactions(day),
    }

    # adnotari (sesiune + outcome) pt jurnal si statistici de follow-through
    def annotate(items, key_fn):
        rows = []
        for it in items:
            ep = int(round(it[0]))
            i = idx.get(ep)
            out = outcome_after(day, i, bars) if i is not None else None
            exp = _EXPECTED.get(key_fn(it))
            hit = None
            if exp and out:
                hit = (out["net"] * exp > 0)
            rows.append(dict(item=it, i=i, ep=ep, sess=_session(ep), out=out, exp=exp, hit=hit))
        return rows

    ann = {
        "big": annotate(day.big_trades, lambda it: ("big", it[3])),
        "abs": annotate(day.absorption, lambda it: ("abs", it[2])),
        "exh": annotate(day.exhaustion, lambda it: ("exh", it[2])),
        "react": annotate(day.level_reactions, lambda it: it[2]),
    }
    return dict(thresholds=dict(big=BIG_TRADE_MIN, abs=abs_base, exh=exh_base),
                viol=viol, ann=ann)


def _fmt_item(kind, it, r):
    """O linie de jurnal pt o detectie."""
    ep = r["ep"]
    sess = r["sess"]
    out = r["out"]
    tail = ""
    if out:
        ft = ""
        if r["hit"] is not None:
            ft = "  ✓" if r["hit"] else "  ✗"
        tail = f" -> {out['bars']}b: {out['label']:9} (net {out['net']:+6.1f}t){ft}"
    if kind == "big":
        _, price, size, side = it
        return f"    {_ro(ep)} {sess:9} {'BUY' if side=='B' else 'SELL':4} {size:5.0f} @ {price:.2f}"
    if kind == "abs":
        _, price, k, buyv, sellv = it
        return f"    {_ro(ep)} {sess:9} {k:4} @ {price:.2f}  buy {buyv:.0f} / sell {sellv:.0f}{tail}"
    if kind == "exh":
        _, price, k, vol, delta = it
        return f"    {_ro(ep)} {sess:9} {k:4} @ {price:.2f}  vol {vol:.0f}  Δ {delta:+.0f}{tail}"
    if kind == "react":
        _, price, k, lvl = it
        return f"    {_ro(ep)} {sess:9} {k:16} {lvl} @ {price:.2f}{tail}"
    return "    ?"


def print_day_report(name, day, res, show):
    print(f"\n{'='*78}\n{name}   bars={len(day.t)}   praguri: "
          f"big>={res['thresholds']['big']}  abs={res['thresholds']['abs']}  exh={res['thresholds']['exh']}")
    labels = {"big": "BIG TRADES", "abs": "ABSORPTION", "exh": "EXHAUSTION", "react": "ACC/REJ"}
    for kind in ("big", "abs", "exh", "react"):
        rows = res["ann"][kind]
        v = res["viol"][kind]
        rth = sum(1 for r in rows if r["sess"] == "RTH")
        # follow-through (doar directionale cu outcome)
        hits = [r["hit"] for r in rows if r["hit"] is not None]
        ft = f"  follow-through {sum(hits)}/{len(hits)}={100*sum(hits)//max(1,len(hits))}%" if hits else ""
        status = "OK" if not v else f"*** {len(v)} INVARIANTI PICATI ***"
        print(f"\n  [{labels[kind]}] total={len(rows)}  RTH={rth}  overnight={len(rows)-rth}  "
              f"invarianti: {status}{ft}")
        for vi in v:
            print(f"      !! {vi}")
        # jurnal: markerele rare integral; big trades doar cu --show all (altfel doar rezumat)
        if kind == "big" and show != "all":
            biggest = sorted(rows, key=lambda r: r["item"][2], reverse=True)[:5]
            print("      (cele mai mari 5; --show all pt toate)")
            for r in biggest:
                print(_fmt_item(kind, r["item"], r))
        else:
            for r in rows:
                print(_fmt_item(kind, r["item"], r))


def run(days, interval, bars, show):
    total_viol = 0
    agg = {"abs": [0, 0], "exh": [0, 0], "react": [0, 0]}   # follow-through hits/total pe toate zilele
    for ymd in days:
        name = ymd if ymd.startswith("glbx") else f"glbx-mdp3-{ymd}.trades"
        try:
            day = load_day(name, mode="session", interval=interval, row_size=2.0)
        except Exception as e:
            print(f"skip {ymd}: {e}")
            continue
        res = verify_day(day, interval, bars)
        print_day_report(ymd, day, res, show)
        for kind in res["viol"]:
            total_viol += len(res["viol"][kind])
        for kind in ("abs", "exh", "react"):
            for r in res["ann"][kind]:
                if r["hit"] is not None:
                    agg[kind][1] += 1
                    agg[kind][0] += 1 if r["hit"] else 0

    print(f"\n{'='*78}\nREZUMAT")
    print(f"  INVARIANTI incalcati (toate zilele): {total_viol}   "
          f"{'✓ TOTUL CORECT' if total_viol == 0 else '✗ BUG-URI DE INVESTIGAT'}")
    print("  Follow-through agregat (doar validare, NU semnal):")
    for kind in ("abs", "exh", "react"):
        h, t = agg[kind]
        if t:
            print(f"    {kind:6}: {h}/{t} = {100*h//t}% in directia asteptata")
    return total_viol


def main():
    ap = argparse.ArgumentParser(description="Verifica detectorii de order flow pe date reale.")
    ap.add_argument("days", nargs="*", default=DEFAULT_DAYS, help="zile YYYYMMDD (implicit: recente)")
    ap.add_argument("--interval", default="1min", choices=list(INTERVAL_SECONDS.keys()))
    ap.add_argument("--bars", type=int, default=10, help="cate bare de outcome dupa fiecare detectie")
    ap.add_argument("--show", default="rare", choices=["rare", "all"], help="'all' arata si toate big trades")
    args = ap.parse_args()
    days = args.days or DEFAULT_DAYS
    print(f"VERIFY DETECTORS  interval={args.interval}  outcome={args.bars} bare  zile={days}")
    total_viol = run(days, args.interval, args.bars, args.show)
    raise SystemExit(1 if total_viol else 0)


if __name__ == "__main__":
    main()
