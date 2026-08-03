"""
Vizualizare grafica statica (matplotlib): Volume Profile + Delta in doua panouri.
Panou 1: Volume Profile (forma profilului). Panou 2: Delta (verde=buy, rosu=sell).
POC/VAH/VAL marcate pe ambele.

Nota: aceasta e varianta STATICA (PNG). Pentru interactiv, vezi app/ (Streamlit).

Foloseste:
    python scripts/visualize_profile.py glbx-mdp3-20260706.trades.csv
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")  # backend fara fereastra - salvam direct PNG (robust pe orice masina)
import matplotlib.pyplot as plt

from core import VolumeProfileEngine, DeltaEngine
from data import load_ticks

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/visualize_profile.py nume_fisier.csv")
        sys.exit(1)

    filepath = sys.argv[1]
    print(f"Incarc {filepath}...")

    st = load_ticks(filepath)
    print(f"Simbol: {st.symbol}  |  Tick-uri: {len(st)}")

    vp = VolumeProfileEngine(tick_size=0.25)
    vp.add_ticks_bulk(st.price_volume())
    vp_result = vp.result(va_percent=0.70)

    de = DeltaEngine(tick_size=0.25)
    de.add_ticks_bulk(st.price_volume_side())
    delta_result = de.result()

    prices = sorted(vp_result.profile.keys())
    volumes = [vp_result.profile[p] for p in prices]
    deltas = [delta_result.delta_per_level.get(p, 0.0) for p in prices]
    delta_colors = ["#2ca02c" if d >= 0 else "#d62728" for d in deltas]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 12), sharey=True)

    ax1.barh(prices, volumes, height=0.2, color="#4a6fa5", alpha=0.85)
    ax1.axhline(vp_result.poc, color="black", linewidth=1.5, label=f"POC ({vp_result.poc})")
    ax1.axhline(vp_result.vah, color="orange", linewidth=1, linestyle="--", label=f"VAH ({vp_result.vah})")
    ax1.axhline(vp_result.val, color="orange", linewidth=1, linestyle="--", label=f"VAL ({vp_result.val})")
    ax1.set_xlabel("Volum total")
    ax1.set_ylabel("Pret")
    ax1.set_title("Volume Profile")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, axis="x", alpha=0.3)
    ax1.invert_xaxis()

    ax2.barh(prices, deltas, height=0.2, color=delta_colors, alpha=0.85)
    ax2.axvline(0, color="black", linewidth=0.8)
    ax2.axhline(vp_result.poc, color="black", linewidth=1.5)
    ax2.axhline(vp_result.vah, color="orange", linewidth=1, linestyle="--")
    ax2.axhline(vp_result.val, color="orange", linewidth=1, linestyle="--")
    ax2.set_xlabel("Delta (buy - sell)")
    ax2.set_title("Delta pe nivel\n(verde = cumparatorii domina, rosu = vanzatorii domina)")
    ax2.grid(True, axis="x", alpha=0.3)

    fig.suptitle(f"{st.symbol}  |  {os.path.basename(filepath)}", fontsize=11, y=1.0)
    plt.tight_layout()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(filepath))[0]
    output_path = os.path.join(OUTPUT_DIR, f"{stem}_profile.png")
    plt.savefig(output_path, dpi=120)
    print(f"\nGrafic salvat: {output_path}")


if __name__ == "__main__":
    main()
