"""P7 (STEP 7) — teste pentru validation harness (scripts/validate_context.py).
Verifica logica de categorisire + outcome descriptiv, fara scan real (rapid)."""

from types import SimpleNamespace as NS

import numpy as np

from scripts.validate_context import categorize, outcome_after, _expected_dir


def _res(**comp):
    base = dict(delta="NEUTRAL", pp="NEUTRAL", abst="NONE", abk=None, exst="NONE", exk=None,
                cvst="NONE", cvstate="NO_DIVERGENCE", lvn_det=False, lvn="INSUFFICIENT_EVIDENCE",
                poc="POC_SIDEWAYS", poc_str="NONE", tape="NORMAL", accel="STEADY", overall="NEUTRAL")
    base.update(comp)
    return NS(overall=base["overall"], last_price=100.0, now_epoch=0, components={
        "delta": NS(sequence_state=base["delta"]),
        "price_progress": NS(state=base["pp"]),
        "absorption": NS(status=base["abst"], kind=base["abk"]),
        "exhaustion": NS(status=base["exst"], kind=base["exk"]),
        "cvd_divergence": NS(status=base["cvst"], state=base["cvstate"]),
        "lvn_interaction": NS(detected=base["lvn_det"], state=base["lvn"]),
        "poc_migration": NS(state=base["poc"], migration_strength=base["poc_str"]),
        "tape_speed": NS(speed_level=base["tape"], acceleration=base["accel"]),
    })


def test_categorize_strong_directional():
    cats = categorize(_res(delta="BUYING_AGGRESSION", pp="AGGRESSION_WITH_PROGRESS"))
    assert "A_strong_directional" in cats and "K_clean_continuation" in cats


def test_categorize_absorption_and_expected_dir():
    r = _res(abst="CONFIRMED", abk="bull")
    assert "C_absorption" in categorize(r)
    assert _expected_dir(r) == 1               # bull absorption -> reactie asteptata in sus
    assert _expected_dir(_res(exst="CONFIRMED", exk="top")) == -1


def test_categorize_mixed_and_lvn():
    assert "J_mixed_conflicting" in categorize(_res(overall="CONTRADICTING"))
    assert "F_lvn_rejection" in categorize(_res(lvn_det=True, lvn="REJECTION"))
    assert "G_lvn_acceptance" in categorize(_res(lvn_det=True, lvn="ACCEPTANCE"))


def test_outcome_after_labels():
    up = NS(close=np.array([100., 101, 102, 103, 104, 105]),
            high=np.array([100.5, 101.5, 102.5, 103.5, 104.5, 105.5]),
            low=np.array([99.5, 100.5, 101.5, 102.5, 103.5, 104.5]))
    o = outcome_after(up, 0, n=5)
    assert o["label"] == "reacted up" and o["net_ticks"] > 0
    flat = NS(close=np.array([100., 101, 99, 101, 99, 100]),
              high=np.array([102.] * 6), low=np.array([98.] * 6))
    assert outcome_after(flat, 0, n=5)["label"] == "rotational"
