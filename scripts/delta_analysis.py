"""
Volume Profile + Delta (cumparare vs vanzare agresiva) pentru O zi.

Foloseste loader-ul unic. Campul `side` din schema Trades e deja clasificat de
Databento (A=sell aggressor, B=buy aggressor).

Foloseste:
    python scripts/delta_analysis.py glbx-mdp3-20260706.trades.csv
"""

import sys

from core import VolumeProfileEngine, DeltaEngine
from data import load_ticks


def main():
    if len(sys.argv) < 2:
        print("Foloseste: python scripts/delta_analysis.py nume_fisier.csv")
        sys.exit(1)

    filepath = sys.argv[1]
    print(f"Incarc {filepath}...\n")

    st = load_ticks(filepath)
    print(f"Simbol: {st.symbol}  |  Tick-uri: {len(st)}  (sursa: {st.source})\n")

    vp_engine = VolumeProfileEngine(tick_size=0.25)
    vp_engine.add_ticks_bulk(st.price_volume())
    vp_result = vp_engine.result(va_percent=0.70)

    delta_engine = DeltaEngine(tick_size=0.25)
    delta_engine.add_ticks_bulk(st.price_volume_side())
    delta_result = delta_engine.result()

    print("=== Volume Profile (referinta) ===")
    print(f"POC: {vp_result.poc}  |  VAH: {vp_result.vah}  |  VAL: {vp_result.val}\n")

    print("=== Delta - rezumat general ===")
    print(f"Volum cumparare agresiva (buy):  {delta_result.total_buy_volume:>12.0f}")
    print(f"Volum vanzare agresiva (sell):   {delta_result.total_sell_volume:>12.0f}")
    print(f"Cumulative Delta (buy - sell):   {delta_result.cumulative_delta:>+12.0f}")
    if delta_result.cumulative_delta > 0:
        print("=> Per total, CUMPARATORII au dominat sesiunea (delta pozitiv).")
    else:
        print("=> Per total, VANZATORII au dominat sesiunea (delta negativ).")

    print("\n=== Top 10 niveluri cu cel mai mare DEZECHILIBRU (delta absolut) ===")
    top_imbalance = sorted(
        delta_result.delta_per_level.items(), key=lambda kv: abs(kv[1]), reverse=True
    )[:10]
    print(f"{'Pret':>10} | {'Buy':>10} | {'Sell':>10} | {'Delta':>10} | POC/VAH/VAL")
    for price, delta in top_imbalance:
        buy = delta_result.buy_volume_per_level.get(price, 0)
        sell = delta_result.sell_volume_per_level.get(price, 0)
        marker = ""
        if price == vp_result.poc:
            marker = "<- POC"
        elif price == vp_result.vah:
            marker = "<- VAH"
        elif price == vp_result.val:
            marker = "<- VAL"
        print(f"{price:>10.2f} | {buy:>10.0f} | {sell:>10.0f} | {delta:>+10.0f} | {marker}")

    print("\n=== Delta exact la POC ===")
    poc_price = vp_result.poc
    if poc_price in delta_result.delta_per_level:
        buy_poc = delta_result.buy_volume_per_level[poc_price]
        sell_poc = delta_result.sell_volume_per_level[poc_price]
        delta_poc = delta_result.delta_per_level[poc_price]
        print(f"La POC ({poc_price}): Buy={buy_poc:.0f}, Sell={sell_poc:.0f}, Delta={delta_poc:+.0f}")
        if delta_poc > 0:
            print("=> La nivelul POC, cumparatorii au fost mai agresivi.")
        else:
            print("=> La nivelul POC, vanzatorii au fost mai agresivi.")


if __name__ == "__main__":
    main()
