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
    tick_size: float = 0.25  # tick-ul instrumentului (NQ=0.25) - pt "ticks de progres"

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
                        symbol=getattr(day, "symbol", ""),
                        tick_size=float(getattr(day, "tick_size", 0.25)))

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
        tick_size=float(getattr(day, "tick_size", 0.25)),
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


# ================================================================== P4.1 — DELTA
# Praguri IMPLICITE (adaptive, NU absolute). Toate sunt raportate la o SCALA calculata
# din delta recenta (mediana |delta| pe fereastra) -> se adapteaza la activitatea zilei,
# nu la un numar fix de contracte. Configurabile prin ContextEngine(config={"delta": {...}}).
DELTA_DEFAULTS = {
    "lookback": 7,           # cate bare inapoi formeaza secventa recenta + scala
    "neutral_ratio": 0.5,    # |delta| < neutral_ratio * scala -> flow neglijabil (NEUTRAL)
    "aggression_ratio": 1.2,  # |delta| >= aggression_ratio * scala -> nivel de "agresiune"
    "accel_tol": 0.15,       # toleranta la variatia de magnitudine (accelerare/decelerare)
}


@dataclass
class DeltaContext:
    """
    Interpretarea Delta la momentul T - OBSERVATII, nu semnal. Expune componentele
    individual (userul le vede pe fiecare), NU "pozitiv=BUY". Clasificarea se bazeaza pe
    EVOLUTIA delta (directie + magnitudine + variatie), cu praguri adaptive la scala recenta.
    """
    current_delta: float            # delta barei curente (la T)
    previous_delta: float           # delta barei anterioare (None daca nu exista)
    delta_change: float             # current - previous (None daca nu exista precedenta)
    delta_direction: str            # POSITIVE | NEGATIVE | FLAT
    momentum: str                   # BUYING | SELLING | NEUTRAL (directia neta recenta)
    acceleration: str               # ACCELERATING | DECELERATING | STEADY (magnitudine vs precedenta)
    recent_sequence: list           # ultimele `lookback` delta (cronologic)
    scale: float                    # scala adaptiva (mediana |delta| recent) - expusa pt transparenta
    sequence_state: str             # vezi DELTA_STATES


# Starile posibile ale secventei de delta (descriptive, simetrice):
DELTA_STATES = (
    "NEUTRAL", "DELTA_FLIP",
    "BUYING_AGGRESSION", "BUYING_ACCELERATION", "BUYING_DECELERATION",
    "SELLING_AGGRESSION", "SELLING_ACCELERATION", "SELLING_DECELERATION",
)


def _classify_delta_state(cur, prev, neutral, acceleration, side):
    """Regula de clasificare (pura). Ordine: neutral -> flip -> accel/decel -> agresiune sustinuta."""
    if cur == 0.0 or abs(cur) < neutral:
        return "NEUTRAL"
    # DELTA_FLIP: semnul curent difera de al barei anterioare (ambele non-neglijabile)
    if prev is not None and prev != 0.0 and (cur > 0) != (prev > 0):
        return "DELTA_FLIP"
    if acceleration == "ACCELERATING":
        return f"{side}_ACCELERATION"
    if acceleration == "DECELERATING":
        return f"{side}_DECELERATION"
    return f"{side}_AGGRESSION"          # sustinut (magnitudine ~constanta)


def analyze_delta(snapshot: Snapshot, cfg=None) -> DeltaContext:
    """
    Componenta Delta - functie PURA, DETERMINISTA, CAUZALA de Snapshot.
    Delta per bara = diferenta CVD-ului (cvd e cauzal, feliat la <= T). Nu foloseste
    pretul, nu stie de Price Action, nu emite BUY/SELL.
    """
    c = {**DELTA_DEFAULTS, **(cfg or {})}
    cvd = np.asarray(snapshot.cvd, dtype=float)
    deltas = np.diff(cvd, prepend=0.0) if len(cvd) else np.zeros(0)
    n = len(deltas)
    if n == 0:
        return DeltaContext(0.0, None, None, "FLAT", "NEUTRAL", "STEADY", [], 0.0, "NEUTRAL")

    cur = float(deltas[-1])
    prev = float(deltas[-2]) if n >= 2 else None
    recent = deltas[-int(c["lookback"]):]
    scale = float(np.median(np.abs(recent)))
    if scale <= 0.0:
        scale = max(abs(cur), 1e-9)      # degenerat (delta recent ~0) -> evita impartirea la 0
    neutral = c["neutral_ratio"] * scale

    direction = "POSITIVE" if cur > 0 else "NEGATIVE" if cur < 0 else "FLAT"

    rmean = float(np.mean(recent))
    momentum = "NEUTRAL" if abs(rmean) < neutral else ("BUYING" if rmean > 0 else "SELLING")

    if prev is None:
        acceleration = "STEADY"
    else:
        ap, ac, tol = abs(prev), abs(cur), c["accel_tol"]
        if ac > ap * (1 + tol):
            acceleration = "ACCELERATING"
        elif ac < ap * (1 - tol):
            acceleration = "DECELERATING"
        else:
            acceleration = "STEADY"

    side = "BUYING" if cur > 0 else "SELLING"
    state = _classify_delta_state(cur, prev, neutral, acceleration, side)

    return DeltaContext(
        current_delta=cur,
        previous_delta=prev,
        delta_change=(cur - prev) if prev is not None else None,
        delta_direction=direction,
        momentum=momentum,
        acceleration=acceleration,
        recent_sequence=[float(x) for x in recent],
        scale=scale,
        sequence_state=state,
    )


# ================================================================== P4.2 — PRICE PROGRESS
# Efort (agresiune delta) vs rezultat (progres de pret in ticks), pe o fereastra scurta.
# Pragurile "mare/mic" sunt ADAPTIVE: se compara efortul/rezultatul CURENT cu scala
# tipica din ferestrele TRECUTE (nu se suprapun cu fereastra curenta) -> nimic absolut.
PRICE_PROGRESS_DEFAULTS = {
    "window": 3,             # cate bare formeaza "miscarea" curenta (efort + rezultat)
    "scale_lookback": 20,    # cate ferestre trecute intra in scala adaptiva (mediana)
    "high_ratio": 1.3,       # >= high_ratio * scala -> MARE (HIGH)
    "low_ratio": 0.6,        # <= low_ratio  * scala -> MIC (LOW); intre -> MEDIUM
}

# Starile (relatia efort vs rezultat). NU spun bullish/bearish - doar agresiune vs progres.
PRICE_PROGRESS_STATES = (
    "AGGRESSION_WITH_PROGRESS",      # efort mare -> progres mare (agresiunea "livreaza")
    "AGGRESSION_WITHOUT_PROGRESS",   # efort mare -> progres mic (agresiune neproductiva)
    "PROGRESS_WITHOUT_AGGRESSION",   # efort mic -> progres mare (pret se misca usor)
    "QUIET",                         # efort mic -> progres mic
    "NEUTRAL",                       # combinatii de mijloc (nici clar mare, nici clar mic)
    "INSUFFICIENT_EVIDENCE",         # prea putine bare pentru o scala adaptiva
)


@dataclass
class PriceProgressContext:
    """
    Relatia dintre AGRESIUNEA delta (efort) si PROGRESUL de pret (rezultat) pe fereastra
    curenta - OBSERVATIE, nu semnal. "Delta negativa + pret in scadere" NU e tratata
    automat ca 'bearish confirmation': masuram cat efort a produs cat progres.
    """
    window: int                     # bare folosite
    delta_sum: float                # agresiune neta pe fereastra (cu semn)
    aggression: float               # |delta_sum| = efort
    price_change: float             # close[T] - close[T-window] (cu semn, puncte)
    progress_ticks: float           # price_change / tick_size
    efficiency: float               # |price_change| / aggression (puncte per unitate de delta)
    aggression_level: str           # HIGH | MEDIUM | LOW (fata de scala adaptiva)
    progress_level: str             # HIGH | MEDIUM | LOW
    direction_alignment: str        # ALIGNED | OPPOSED | FLAT (semnul delta vs semnul pretului)
    agg_scale: float                # scala adaptiva a efortului (mediana ferestre trecute)
    progress_scale: float           # scala adaptiva a rezultatului
    state: str                      # vezi PRICE_PROGRESS_STATES


def _level(value, scale, high_ratio, low_ratio):
    """Clasifica o marime fata de o scala adaptiva: HIGH / LOW / MEDIUM."""
    if scale <= 0:
        return "MEDIUM"
    if value >= high_ratio * scale:
        return "HIGH"
    if value <= low_ratio * scale:
        return "LOW"
    return "MEDIUM"


def analyze_price_progress(snapshot: Snapshot, cfg=None) -> PriceProgressContext:
    """
    Componenta Price Progress - functie PURA, DETERMINISTA, CAUZALA de Snapshot.
    Efort = |suma delta pe fereastra|; rezultat = |variatia de pret pe fereastra|.
    Scala adaptiva = mediana ferestrelor TRECUTE (care NU se suprapun cu cea curenta).
    """
    c = {**PRICE_PROGRESS_DEFAULTS, **(cfg or {})}
    w = int(c["window"])
    close = np.asarray(snapshot.close, dtype=float)
    cvd = np.asarray(snapshot.cvd, dtype=float)
    n = len(close)
    tick = snapshot.tick_size or 0.25

    deltas = np.diff(cvd, prepend=0.0) if len(cvd) else np.zeros(0)

    def _insufficient():
        return PriceProgressContext(
            window=w, delta_sum=0.0, aggression=0.0, price_change=0.0, progress_ticks=0.0,
            efficiency=0.0, aggression_level="MEDIUM", progress_level="MEDIUM",
            direction_alignment="FLAT", agg_scale=0.0, progress_scale=0.0,
            state="INSUFFICIENT_EVIDENCE")

    # Avem nevoie de: o fereastra curenta [n-w .. n-1] SI cel putin o fereastra trecuta
    # care nu se suprapune cu ea. Rezultatul foloseste close[j-w] -> j >= w; ferestrele
    # trecute se termina la j <= n-1-w (fara suprapunere) -> e nevoie de n >= 2*w+1.
    if w < 1 or n < 2 * w + 1:
        return _insufficient()

    # Fereastra curenta (la T)
    delta_sum = float(np.sum(deltas[n - w:]))
    aggression = abs(delta_sum)
    price_change = float(close[-1] - close[n - w - 1])
    progress = abs(price_change)

    # Scala adaptiva din ferestrele TRECUTE: cele care se termina la j in [w .. n-1-w]
    # (j >= w -> close[j-w] valid; j <= n-1-w -> nu contin nicio bara din fereastra curenta).
    past_eff, past_res = [], []
    for j in range(w, n - w):
        past_eff.append(abs(float(np.sum(deltas[j - w + 1:j + 1]))))
        past_res.append(abs(float(close[j] - close[j - w])))
    if not past_eff:
        return _insufficient()
    lb = int(c["scale_lookback"])
    agg_scale = float(np.median(past_eff[-lb:]))
    progress_scale = float(np.median(past_res[-lb:]))

    agg_level = _level(aggression, agg_scale, c["high_ratio"], c["low_ratio"])
    prog_level = _level(progress, progress_scale, c["high_ratio"], c["low_ratio"])

    if price_change == 0.0 or delta_sum == 0.0:
        alignment = "FLAT"
    elif (delta_sum > 0) == (price_change > 0):
        alignment = "ALIGNED"
    else:
        alignment = "OPPOSED"

    efficiency = (progress / aggression) if aggression > 0 else 0.0

    # Stare = combinatia efort x rezultat (doar cand ambele sunt clar mari/mici)
    if agg_level == "HIGH" and prog_level == "HIGH":
        state = "AGGRESSION_WITH_PROGRESS"
    elif agg_level == "HIGH" and prog_level == "LOW":
        state = "AGGRESSION_WITHOUT_PROGRESS"
    elif agg_level == "LOW" and prog_level == "HIGH":
        state = "PROGRESS_WITHOUT_AGGRESSION"
    elif agg_level == "LOW" and prog_level == "LOW":
        state = "QUIET"
    else:
        state = "NEUTRAL"

    return PriceProgressContext(
        window=w, delta_sum=delta_sum, aggression=aggression, price_change=price_change,
        progress_ticks=price_change / tick, efficiency=efficiency,
        aggression_level=agg_level, progress_level=prog_level,
        direction_alignment=alignment, agg_scale=agg_scale, progress_scale=progress_scale,
        state=state)


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
        # Componente de order flow (fiecare = functie pura de Snapshot).
        components = {
            "delta": analyze_delta(snapshot, self.config.get("delta")),
            "price_progress": analyze_price_progress(snapshot, self.config.get("price_progress")),
        }
        if n == 0:
            return ContextResult(now_epoch=int(snapshot.now_epoch), n_bars=0,
                                 last_price=0.0, poc=0.0, cvd=0.0, components=components)
        return ContextResult(
            now_epoch=int(snapshot.now_epoch),
            n_bars=n,
            last_price=float(snapshot.close[-1]),
            poc=float(snapshot.poc),
            cvd=float(snapshot.cvd[-1]),
            overall="NEUTRAL",
            components=components,
        )
