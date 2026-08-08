"""
P7 — VALIDATION HARNESS pentru Context Engine pe DATE REALE.

Scop: sa analizam MOMENTE reale, nu doar synthetic. Pentru fiecare moment (bara T):
  - contextul cauzal LA T (toate componentele + overall + reasons);
  - ce s-a intamplat DUPA N bare (DOAR pentru validare - NU intra in calculul la T);
  - un outcome descriptiv (reacted up / continued down / rotational).

NU hardcodam ore/preturi/zile: harness-ul SCANEAZA sesiunile si GASESTE singur exemple
pentru fiecare categorie (A..L). Contextul la T e strict cauzal (upto_index=T).

Rulare:
    python scripts/validate_context.py            # scaneaza zilele default, rezumat + exemple
"""

import datetime

import numpy as np

from app.desktop.data_service import (load_day, build_reference_levels,
                                      build_composite_levels, SESSION_DEFS)
from core import ContextEngine, snapshot_from_daydata

ENG = ContextEngine()


def _ro(ep):
    return datetime.datetime.fromtimestamp(int(ep) + 3 * 3600, datetime.timezone.utc).strftime("%H:%M")


def load_context_day(name, interval="1min", row_size=2.0):
    """Ziua + niveluri (prev session + composite 15D, cache implicit prin build_*)."""
    day = load_day(name, mode="session", interval=interval, row_size=row_size)
    refs = build_reference_levels(name, mode="session", row_size=row_size,
                                  sessions=SESSION_DEFS["real"])
    comps = build_composite_levels(name, spans=(15,), row_size=row_size)
    return day, refs, comps


def context_at(day, refs, comps, i):
    """ContextResult CAUZAL la bara i (foloseste doar bare <= i)."""
    snap = snapshot_from_daydata(day, upto_index=i, reference_levels=refs, composite_levels=comps)
    return ENG.analyze(snap)


def outcome_after(day, i, n=5, tick=0.25):
    """Ce a facut pretul in urmatoarele n bare - DOAR pentru validare (nu la calculul de la T)."""
    last = len(day.close) - 1
    j = min(i + n, last)
    if j <= i:
        return None
    seg = day.close[i:j + 1]
    net = (day.close[j] - day.close[i]) / tick
    hi = (np.max(day.high[i:j + 1]) - day.close[i]) / tick
    lo = (day.close[i] - np.min(day.low[i:j + 1])) / tick
    if abs(net) < max(hi, lo) * 0.4:
        label = "rotational"
    elif net > 0:
        label = "reacted up"
    else:
        label = "continued/ moved down"
    return dict(net_ticks=net, up_ticks=hi, down_ticks=lo, label=label, bars=j - i)


# ---- categorii (detectate DIN outputul engine-ului la fiecare bara, fara hardcoding) ----
def categorize(res):
    cats = set()
    c = res.components
    dl, pp = c["delta"].sequence_state, c["price_progress"].state
    ab, ex, cv = c["absorption"], c["exhaustion"], c["cvd_divergence"]
    lvn, poc, tp = c["lvn_interaction"], c["poc_migration"], c["tape_speed"]
    if dl in ("BUYING_AGGRESSION", "BUYING_ACCELERATION", "SELLING_AGGRESSION",
              "SELLING_ACCELERATION") and pp == "AGGRESSION_WITH_PROGRESS":
        cats.add("A_strong_directional")
    if pp == "AGGRESSION_WITHOUT_PROGRESS":
        cats.add("B_aggression_no_progress")
    if ab.status == "CONFIRMED":
        cats.add("C_absorption")
    if ex.status == "CONFIRMED":
        cats.add("D_exhaustion")
    if cv.status == "CONFIRMED" and cv.state in ("BULLISH_DIVERGENCE", "BEARISH_DIVERGENCE"):
        cats.add("E_cvd_divergence")
    if lvn.detected and lvn.state == "REJECTION":
        cats.add("F_lvn_rejection")
    if lvn.detected and lvn.state == "ACCEPTANCE":
        cats.add("G_lvn_acceptance")
    if poc.state in ("POC_RISING", "POC_FALLING") and poc.migration_strength == "STRONG":
        cats.add("H_poc_migration")
    if tp.speed_level == "HIGH":
        cats.add("I_high_tape")
    if res.overall == "CONTRADICTING":
        cats.add("J_mixed_conflicting")
    if pp == "AGGRESSION_WITH_PROGRESS" and tp.acceleration != "DECELERATING":
        cats.add("K_clean_continuation")
    if lvn.state == "FAILED_REJECTION" or ex.status == "CONFIRMED":
        cats.add("L_failed_or_reversal")
    return cats


# directia "asteptata" a follow-through-ului pt evenimentele directionale (DOAR validare)
def _expected_dir(res):
    ab, ex, cv = res.components["absorption"], res.components["exhaustion"], res.components["cvd_divergence"]
    if ab.status == "CONFIRMED":
        return +1 if ab.kind == "bull" else -1
    if ex.status == "CONFIRMED":
        return +1 if ex.kind == "bot" else -1
    if cv.status == "CONFIRMED" and cv.state == "BULLISH_DIVERGENCE":
        return +1
    if cv.status == "CONFIRMED" and cv.state == "BEARISH_DIVERGENCE":
        return -1
    return 0


def scan(days, per_cat=3, warmup=30, interval="1min"):
    """Scaneaza zilele. Numara BARE cu conditia (bar_counts) SI evenimente DISTINCTE
    (tranzitii intr-o stare = event_counts). Pt evenimentele directionale calculeaza
    follow-through (outcome-ul de dupa in directia asteptata) - DOAR validare."""
    found, bar_counts, event_counts = {}, {}, {}
    follow = {}   # cat -> [hits, total]
    for name in days:
        try:
            day, refs, comps = load_context_day(name, interval=interval)
        except Exception as e:
            print(f"skip {name}: {e}")
            continue
        n = len(day.t)
        prev = set()
        for i in range(warmup, n - 6):
            res = context_at(day, refs, comps, i)
            cats = categorize(res)
            new = cats - prev
            exp = _expected_dir(res)
            out = outcome_after(day, i)
            for cat in cats:
                bar_counts[cat] = bar_counts.get(cat, 0) + 1
            for cat in new:                                   # doar tranzitiile = evenimente
                event_counts[cat] = event_counts.get(cat, 0) + 1
                bucket = found.setdefault(cat, [])
                if len(bucket) < per_cat:
                    bucket.append((name, i, res, out))
                if cat in ("C_absorption", "D_exhaustion", "E_cvd_divergence") and exp and out:
                    h, tot = follow.get(cat, (0, 0))
                    hit = 1 if (out["net_ticks"] * exp > 0) else 0
                    follow[cat] = (h + hit, tot + 1)
            prev = cats
    return found, bar_counts, event_counts, follow


def _line(name, i, res, out):
    c = res.components
    day_lbl = name.split("-")[-1].replace(".trades", "")
    parts = [f"{day_lbl} {_ro(res.now_epoch)}",
             f"px {res.last_price:.0f}",
             f"Overall={res.overall}",
             f"d={c['delta'].sequence_state}",
             f"Prog={c['price_progress'].state}",
             f"CVD={c['cvd_divergence'].state}",
             f"LVN={c['lvn_interaction'].state}",
             f"Tape={c['tape_speed'].speed_level}/{c['tape_speed'].acceleration}"]
    tail = f"-> after {out['bars']}b: {out['label']} (net {out['net_ticks']:+.0f}t)" if out else ""
    return "  " + " | ".join(parts) + "  " + tail


def main():
    days = ["glbx-mdp3-20260730.trades", "glbx-mdp3-20260731.trades",
            "glbx-mdp3-20260803.trades", "glbx-mdp3-20260804.trades",
            "glbx-mdp3-20260805.trades", "glbx-mdp3-20260806.trades"]
    print("Scanez zilele (1min):", [d.split('-')[-1].replace('.trades', '') for d in days])
    found, bar_counts, event_counts, follow = scan(days, per_cat=3)
    total_bars = sum(1 for _ in [0])  # placeholder; nu e nevoie
    print("\n=== FRECVENTA: BARE-cu-starea vs EVENIMENTE distincte (tranzitii) ===")
    print(f"  {'categorie':26} {'bare':>6} {'evenim.':>8}  follow-through")
    for cat in sorted(bar_counts):
        ft = ""
        if cat in follow and follow[cat][1]:
            h, tot = follow[cat]
            ft = f"{h}/{tot} = {100*h/tot:.0f}% in expected dir"
        print(f"  {cat:26} {bar_counts[cat]:>6} {event_counts.get(cat, 0):>8}  {ft}")
    print("\n=== EXEMPLE (context CAUZAL la T + outcome de dupa, DOAR validare) ===")
    for cat in sorted(found):
        print(f"\n[{cat}]")
        for (name, i, res, out) in found[cat]:
            print(_line(name, i, res, out))


if __name__ == "__main__":
    main()
