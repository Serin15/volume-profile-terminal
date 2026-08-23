"""Guard permanent: Stratul 1 (INVARIANTI de corectitudine) al harness-ului
`scripts/verify_detectors.py` trebuie sa fie CURAT pe date reale.

Daca vreun detector de order flow (Big Trades / Absorption / Exhaustion / Acc-Rej) incepe
sa emita ceva ce NU respecta definitia lui — extrema gresita, prag neatins, delta/volum
raportate gresit, epoca nealiniata la o lumanare, dedupe incalcat, sau side 'N' la big
trades — acest test cade. Asa nu regresam corectitudinea detectorilor.

Date reale (skip daca lipsesc). Fara Qt.
"""
import glob
import os

import pytest

from data.loader import PARQUET_DIR
from app.desktop.data_service import load_day
from scripts.verify_detectors import verify_day

_HAVE = bool(glob.glob(os.path.join(PARQUET_DIR, "*.parquet")))
pytestmark = pytest.mark.skipif(not _HAVE, reason="date reale lipsesc (data/parquet)")

# 17.08 continea exact cazul 'N' la big trades (acum exclus) + toate cele 4 tipuri de markere;
# 18.08 = a doua zi independenta, toate tipurile.
DAYS = ["20260817", "20260818"]


@pytest.mark.parametrize("ymd", DAYS)
def test_no_invariant_violations(ymd):
    """Pe o zi reala, la 1min, niciun invariant nu trebuie incalcat."""
    name = f"glbx-mdp3-{ymd}.trades"
    try:
        day = load_day(name, mode="session", interval="1min", row_size=2.0)
    except Exception as e:
        pytest.skip(f"ziua {ymd} indisponibila: {e}")
    res = verify_day(day, "1min", 10)
    viol = [v for lst in res["viol"].values() for v in lst]
    assert not viol, f"{ymd}: {len(viol)} invarianti picati:\n  " + "\n  ".join(viol)


def test_big_trades_exclude_unknown_side():
    """Fix 'N': niciun big trade emis nu are side in afara de B/A (agresor cunoscut)."""
    try:
        day = load_day("glbx-mdp3-20260817.trades", mode="session", interval="1min", row_size=2.0)
    except Exception as e:
        pytest.skip(f"ziua indisponibila: {e}")
    bad = [bt for bt in day.big_trades if bt[3] not in ("B", "A")]
    assert not bad, f"big trades cu side necunoscut (ar trebui excluse): {bad[:5]}"
