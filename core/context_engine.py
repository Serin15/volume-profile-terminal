"""
Order Flow Context Engine — FUNDATIE (P4-core)
==============================================

Stratul de analiza contextuala dintre datele/replay-ul CAUZAL si UI. Traduce ce s-a
intamplat in order flow in OBSERVATII individuale (NU semnale BUY/SELL, NU scor, NU
black-box). In P4-core exista DOAR scheletul + granita anti-look-ahead demonstrata;
componentele (Delta, Price Progress, Absorption/Exhaustion, CVD divergence, POC
migration, LVN interaction, Acceptance/Rejection, Tape) se adauga in fazele urmatoare.

Principiul central — NO LOOK-AHEAD (cauzalitate garantata prin CONSTRUCTIE):
    ContextEngine NU primeste ziua intreaga + un timestamp si "promite" ca nu se uita
    in viitor. Primeste un `Snapshot` care CONTINE FIZIC doar informatia disponibila la
    momentul T (bar index k) si NIMIC dupa. Snapshot-ul se construieste prin FELIERE
    (`snapshot_from_daydata(day, upto_index=k)`), care taie orice bar > k si foloseste
    valorile DEVELOPING (POC/VA cumulative pana la k) — NU POC-ul zilei intregi (care ar
    fi look-ahead). Astfel engine-ul nu are cum sa vada viitorul: nu-l primeste.

Layering: acest modul traieste in `core/` si depinde DOAR de numpy + core.vp_engine.
NU importa nimic din `app/` (data_service). `snapshot_from_daydata` accepta orice obiect
cu forma unui DayData (duck typing) -> core ramane independent de UI.
"""

from dataclasses import dataclass, field

import numpy as np

from core.vp_engine import VolumeProfileEngine


# ------------------------------------------------------------------ Snapshot
@dataclass(frozen=True)
class Snapshot:
    """
    Intrarea CAUZALA a ContextEngine: toata informatia disponibila la momentul T
    (bar index k) si nimic dupa. Imutabil (frozen) -> analiza e o functie pura de el.

    Toate array-urile au aceeasi lungime (k+1 bare, ultima = bara curenta la T).
    poc/vah/val sunt valorile DEVELOPING la T (cumulative pana la k), NU ale zilei
    intregi -> nu exista scurgere din viitor.
    """
    now_epoch: int          # T = epoca barei curente (t[-1])
    bar_seconds: int
    t: np.ndarray           # epoci bare [0..k]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    cvd: np.ndarray         # Cumulative Delta pana la fiecare bara (cauzal)
    poc: float              # developing POC la T (cauzal)
    vah: float
    val: float
    footprint: dict         # DOAR barele <= T: {epoca: {pret: [buy, sell]}}
    row_size: float
    symbol: str = ""

    def __len__(self):
        return len(self.t)


def _levels_from_footprint(footprint, row_size, va_percent=0.70):
    """POC/VAH/VAL cauzale reconstruite din footprint-ul (deja feliat la <= T).
    Folosit doar ca fallback cand ziua nu are array-urile developing."""
    vp = VolumeProfileEngine(tick_size=row_size)
    for cells in footprint.values():
        for price, (buy, sell) in cells.items():
            total = buy + sell
            if total > 0:
                vp.add_tick(price, total)
    r = vp.result(va_percent=va_percent)
    return (r.poc or 0.0, r.vah or 0.0, r.val or 0.0)


def snapshot_from_daydata(day, upto_index=None, va_percent=0.70) -> Snapshot:
    """
    Construieste un Snapshot CAUZAL dintr-un DayData, pastrand DOAR barele [0..upto_index].

    Aici e granita anti-look-ahead: feliem array-urile la k, filtram footprint-ul la
    epocile <= T si luam POC/VA din valorile DEVELOPING (dev_poc[k] etc.) — cauzale —
    NU din day.poc (care e calculat pe ziua intreaga = viitor).

    `upto_index=None` -> foloseste toata ziua (util cand `day` e DEJA un snapshot de
    replay, adica deja taiat la bara curenta).
    `day` = orice obiect cu forma unui DayData (duck typing; nu importam clasa).
    """
    t_all = np.asarray(day.t)
    n = len(t_all)
    if n == 0:
        return Snapshot(now_epoch=0, bar_seconds=int(getattr(day, "bar_seconds", 0)),
                        t=np.zeros(0), open=np.zeros(0), high=np.zeros(0), low=np.zeros(0),
                        close=np.zeros(0), volume=np.zeros(0), cvd=np.zeros(0),
                        poc=0.0, vah=0.0, val=0.0, footprint={},
                        row_size=float(getattr(day, "row_size", 0.0)),
                        symbol=getattr(day, "symbol", ""))

    k = (n - 1) if upto_index is None else max(0, min(int(upto_index), n - 1))
    sl = slice(0, k + 1)

    t = np.array(t_all[sl], dtype=float)
    epochs = {int(round(e)) for e in t}
    footprint = {int(round(ep)): cells
                 for ep, cells in getattr(day, "footprint", {}).items()
                 if int(round(ep)) in epochs}

    # POC/VA CAUZALE la T: preferam array-urile developing (cumulative, deja cauzale);
    # fallback = reconstruite din footprint-ul feliat. NICIODATA day.poc (ziua intreaga).
    def dev_at(name):
        arr = np.asarray(getattr(day, name, []))
        return float(arr[k]) if len(arr) > k else None
    poc = dev_at("dev_poc")
    vah = dev_at("dev_vah")
    val = dev_at("dev_val")
    if poc is None or vah is None or val is None:
        poc, vah, val = _levels_from_footprint(footprint, float(day.row_size), va_percent)

    def col(name):
        return np.array(np.asarray(getattr(day, name))[sl], dtype=float)

    return Snapshot(
        now_epoch=int(round(t[-1])), bar_seconds=int(day.bar_seconds),
        t=t, open=col("open"), high=col("high"), low=col("low"), close=col("close"),
        volume=col("volume"), cvd=col("cvd"),
        poc=float(poc), vah=float(vah), val=float(val),
        footprint=footprint, row_size=float(day.row_size),
        symbol=getattr(day, "symbol", ""),
    )


# ------------------------------------------------------------------ ContextResult
@dataclass
class ContextResult:
    """
    Rezultatul analizei contextuale la momentul T. In P4-core contine doar valori de
    FUNDATIE, trivial cauzale (derivate strict din snapshot). Blocurile de componente
    (delta, price_progress, absorption, exhaustion, cvd_divergence, poc_migration,
    node_interaction, accept_reject, tape) se vor pune in `components` in fazele urmatoare.

    `overall` va deveni SUPPORTIVE / NEUTRAL / CONTRADICTING derivat prin REGULI
    transparente din componente — niciodata un scor sau un procent. Acum e "NEUTRAL"
    (nu exista inca componente).
    """
    now_epoch: int          # T
    n_bars: int             # cate bare erau disponibile la T (cauzal)
    last_price: float       # close la T
    poc: float              # developing POC la T (cauzal)
    cvd: float              # Cumulative Delta la T
    overall: str = "NEUTRAL"
    components: dict = field(default_factory=dict)


# ------------------------------------------------------------------ ContextEngine
class ContextEngine:
    """
    Stratul de analiza: functie PURA si DETERMINISTA de un Snapshot cauzal.

    Nu detine niciun obiect de zi intreaga si nu poate privi in viitor — primeste doar
    Snapshot-ul, care contine fizic doar date <= T. `analyze()` nu muta nicio stare
    interna; acelasi Snapshot -> acelasi ContextResult, mereu.

    P4-core: calculeaza doar valori de fundatie (now_epoch, n_bars, last_price, poc
    cauzal, cvd). Componentele de order flow se adauga in fazele urmatoare, fiecare tot
    ca functie pura de Snapshot.
    """

    def __init__(self, config=None):
        # Config imutabila logic (parametri de praguri pt componentele viitoare).
        self.config = dict(config or {})

    def analyze(self, snapshot: Snapshot) -> ContextResult:
        """Snapshot cauzal -> ContextResult. Pura, determinista, fara look-ahead."""
        n = len(snapshot)
        if n == 0:
            return ContextResult(now_epoch=int(snapshot.now_epoch), n_bars=0,
                                 last_price=0.0, poc=0.0, cvd=0.0)
        return ContextResult(
            now_epoch=int(snapshot.now_epoch),
            n_bars=n,
            last_price=float(snapshot.close[-1]),
            poc=float(snapshot.poc),
            cvd=float(snapshot.cvd[-1]),
            overall="NEUTRAL",
            components={},
        )
