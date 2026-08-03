"""
Volume Profile pe SESIUNE REALA futures (22:00 UTC -> 22:00 UTC), nu pe ziua
calendaristica UTC bruta. Combina mai multe fisiere si re-grupeaza tick-urile
pe sesiuni corecte (regula: ora UTC >= 22 => sesiunea zilei urmatoare).

Foloseste:
    python scripts/session_reanalysis.py glbx-mdp3-20260706.trades.csv glbx-mdp3-20260707.trades.csv ...

Nota: primele si ultimele sesiuni pot fi incomplete (le lipsesc tick-uri de la
marginile intervalului de fisiere). Sesiunile din mijloc sunt cele de incredere.
"""

import sys

from core import VolumeProfileEngine
from data import load_many


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/session_reanalysis.py fisier1 fisier2 ...")
        sys.exit(1)

    filepaths = sys.argv[1:]
    print(f"Incarc {len(filepaths)} fisiere...\n")

    combined = load_many(filepaths)
    print(f"Simbol: {combined.symbol}  |  Tick-uri totale: {len(combined)}\n")

    sessions = combined.by_session()

    print("=== Volume Profile per SESIUNE REALA (22:00 UTC -> 22:00 UTC) ===\n")
    print(f"{'Sesiune':<14} | {'Tick-uri':>10} | {'Volum':>10} | {'POC':>10} | {'VAH':>10} | {'VAL':>10}")
    print("-" * 80)
    for sess in sorted(sessions.keys()):
        st = sessions[sess]
        engine = VolumeProfileEngine(tick_size=0.25)
        engine.add_ticks_bulk(st.price_volume())
        r = engine.result(va_percent=0.70)
        print(f"{sess:<14} | {len(st):>10} | {r.total_volume:>10.0f} | "
              f"{r.poc:>10.2f} | {r.vah:>10.2f} | {r.val:>10.2f}")

    print("\nNota: prima si ultima sesiune pot fi incomplete (margini de interval).")


if __name__ == "__main__":
    main()
