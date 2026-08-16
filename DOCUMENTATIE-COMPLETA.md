# Volume Profile Terminal — DOCUMENTAȚIE COMPLETĂ (backup)

> Documentul ăsta descrie **tot tool-ul**, la zi (august 2026), ca să-l poți înțelege
> peste 6 luni fără să citești codul. Scris pe baza codului REAL, nu din memorie.
> Înlocuiește `DOCUMENTATIE.md` (care e dinainte de Context Engine + Profile Only).

---

## 0. Ce este, pe scurt

Terminal **desktop** de **Volume Profile + Order Flow** pentru futures **NQ** (E-mini
Nasdaq-100), date **Databento**. Python (PySide6 + pyqtgraph). Uz personal: backtesting
prin replay + învățat order flow, drum spre date live la NY open.

**Regula de aur (non-negociabilă):**
> „Asta face order flow-ul în zona în care ești. **TU** decizi dacă setup-ul tău de price
> action merită executat." Tool-ul e **analiză de CONTEXT**. ZERO BUY/SELL, zero semnale
> automate, scoruri, probabilități, ML sau verdict de trade.

**Principiul de arhitectură:** motoarele **calculează**, nu desenează. `core/` nu știe
nimic de UI. Orice interfață se construiește peste același „creier".

---

## 1. Unde e tot (GitHub + backup)

- **Repo (privat):** `github.com/Serin15/volume-profile-terminal`
- **`main` = commit `b3217da`** — tot tool-ul + 62 zile de date parquet + 261 teste.
- **Branch `feat/profile-only` = `9c9e7a6`** — feature-ul Profile Only (așteaptă merge).
- **Datele sunt pe git** (62 fișiere parquet, ~186MB) → backup complet, reproductibil.

**Rulare app:**
```powershell
cd "D:\Volume Profile"
.\.venv\Scripts\python.exe run_desktop.py
```
**Teste:** `.\.venv\Scripts\python.exe -m pytest -q` → **267 passed** (~13 min; unele ating date reale).
**Date noi:** CSV Databento în `data\raw\` → `python scripts\convert_to_parquet.py`.

---

## 2. Harta fișierelor

```
core/                       CREIERUL (fără UI, fără desen)
  vp_engine.py              VolumeProfileEngine: POC/VA/HVN-LVN + VolumeNode (zone cu low/high)
  delta_engine.py           DeltaEngine: buy/sell per nivel, CVD
  context_engine.py  ★      CONTEXT ENGINE: Snapshot cauzal + 11 componente + overall
data/
  loader.py                 Citire parquet/CSV, alege contractul activ, granița sesiune 22:00 UTC
  parquet/                  62 zile (4 mai → 6 aug 2026)
app/desktop/
  data_service.py           Pod loader↔engine → DayData; developing POC/VA; niveluri context; period_profiles
  replay.py                 Replay tick-cu-tick (cauzal, determinist, seek prin checkpoints)
  charts.py                 Itemuri de randare (lumânări, profil, footprint, PeriodProfilesItem)
  main.py                   UI: controale, grafic, panou Context, Profile Only
  drawings.py / theme.py    Unelte de desen / paletă dark
scripts/                    Unelte CLI + validate_context.py (harness validare pe date reale)
tests/                      267 teste (pytest)
```

---

## 3. Pipeline de date (cum intră datele)

**Sursă:** Databento, schema **Trades** (CME GLBX.MDP3). Fiecare rând = o execuție
(price, size, side, symbol, timestamp).

- **Timestamp:** `ts_recv`, convertit în `datetime64[ns, UTC]` (tz-aware, UTC). Monotonic.
- **Agresor (`side`):** `'A'` = sell aggressor (−delta), `'B'` = buy aggressor (+delta),
  `'N'` = necunoscut (ignorat la delta). ✅ Corect per convenția Databento. Pe date reale
  N ≈ 0%, deci irelevant.
- **Contract activ:** ales automat = simbolul cu **volumul cel mai mare** per zi. Setul de
  date trece un **rollover NQM6→NQU6** pe la mijlocul lui iunie (fiecare zi ia contractul ei).
  Spread-urile (`NQM6-NQU6`) sunt filtrate automat (nu-s dominante).
- **Sesiunea futures:** ziua CME = **22:00 UTC → 22:00 UTC** (18:00 ET). Regula: ora UTC ≥ 22
  → tick-ul e din sesiunea zilei următoare. ⚠️ **Fixat la 22:00** — corect vara (EDT); iarna
  (EST) ar trebui 23:00 UTC (vezi Limitări §8).
- **Lumânări:** resample pe interval (1/5/15min…), barele goale (pauză mentenanță) sunt scoase.
- **Footprint:** per (lumânare, nivel de preț) → `[buy, sell]`. Bază pentru delta/CVD/absorbție.
- **CVD (Cumulative Delta):** suma cumulativă a delta-urilor per bară (developing, cauzal).
- **Developing POC/VA:** valoarea cumulativă **după fiecare bară** (nu ziua întreagă) —
  `developing_levels()` acumulează bară cu bară. Ultima valoare = POC/VA total. **Cauzal.**
- **Tape speed (tps):** print-uri/secundă per bară.

---

## 4. Motoarele de bază

### VolumeProfileEngine (`core/vp_engine.py`)
- **POC** = nivelul cu volum maxim. **Value Area (VAH/VAL)** = 70%, prin expansiune din POC
  (algoritm Sierra Chart: adaugi mereu vecinul cu volum mai mare până acumulezi 70%).
- **HVN/LVN** prin **peak detection real** (maxime/minime locale + prag de prominență + grupare),
  nu praguri globale. **VolumeNode** = nod ca ZONĂ (low/high/width/tier major-minor), nu doar preț.
- Intern lucrează cu `tick_index` (int) ca să evite erori de rotunjire; la ieșire → prețuri reale.

### DeltaEngine (`core/delta_engine.py`)
- Per nivel: volum buy, volum sell, delta = buy − sell. **Cumulative Delta** = suma pe sesiune.
- `B`→+delta, `A`→−delta, `N`→ignorat.

---

## 5. Context Engine (`core/context_engine.py`) — inima tool-ului

Stratul care traduce order flow-ul în **observații de context**, nu semnale. Adăugat în
fazele P1a–P7 (înghețate). Cea mai importantă parte — și cea care lipsea din doc-ul vechi.

### 5.1. Cauzalitate — NO LOOK-AHEAD (garantată prin construcție)
Engine-ul **nu** primește ziua întreagă + un timestamp. Primește un **`Snapshot`** (frozen)
care conține **fizic doar informația de la momentul T** (bara k) și nimic după.
- `snapshot_from_daydata(day, upto_index=k)` = **granița anti-look-ahead**: feliază toate
  array-urile la ≤ k și ia POC/VA din valorile **developing** (`dev_poc[k]`), NU din ziua întreagă.
- `ContextEngine.analyze(snapshot)` = funcție **pură, deterministă**. Același snapshot → același
  rezultat, mereu. Testat: rezultatul la T e identic fie că ziua „continuă" după T, fie că s-ar
  fi terminat la T → viitorul nu se scurge în rezultat. **Verificat în audit: cauzalitatea ține.**
- În replay: forming-ul barei curente reflectă doar tick-urile hrănite; absorbția/exhaustion doar
  pe barele închise. Tot cauzal.

### 5.2. Cele 11 componente (fiecare = funcție pură de Snapshot)

Toate folosesc **praguri ADAPTIVE** (raportate la activitatea recentă), nu valori fixe. Stări
FORMING→CONFIRMED unde are sens (comportamentul ulterior citit doar din bare ≤ T).

| # | Componentă | Ce măsoară | Stări principale |
|---|-----------|------------|------------------|
| 1 | **delta** | evoluția delta (direcție+magnitudine+variație) | BUYING/SELLING _AGGRESSION/_ACCELERATION/_DECELERATION, DELTA_FLIP, NEUTRAL |
| 2 | **price_progress** | efort (delta) vs rezultat (ticks) | AGGRESSION_WITH/WITHOUT_PROGRESS, PROGRESS_WITHOUT_AGGRESSION, QUIET, NEUTRAL |
| 3 | **absorption** | agresor dominant la extremă, absorbit + respingere în bară | BULL/BEAR_ABSORPTION_FORMING/CONFIRMED/FADED |
| 4 | **exhaustion** | climax de volum + delta la o extremă NOUĂ | TOP/BOT_EXHAUSTION_FORMING/CONFIRMED/FADED |
| 5 | **cvd_divergence** | swing structural preț vs CVD | BULLISH/BEARISH_DIVERGENCE, NO_DIVERGENCE, INSUFFICIENT |
| 6 | **poc_migration** | direcția POC-ului **developing** în timp | POC_RISING/FALLING/SIDEWAYS + STRONG/WEAK |
| 7 | **lvn_interaction** | ce face prețul la ZONA LVN reală | TEST/REJECTION/ACCEPTANCE/FAST_TRAVERSAL/FAILED_REJECTION |
| 8 | **acceptance_rejection** | același motor pe nivelul cheie cel mai apropiat (POC/VAH/VAL) | idem |
| 9 | **tape_speed** | contracts/sec + trades/sec + delta/sec | HIGH/NORMAL/LOW + ACCELERATING/DECELERATING |
| 10 | **session_context** | poziția prețului vs sesiuni precedente (Asia/Londra/NY) | ABOVE/INSIDE/BELOW_VALUE + interacțiune |
| 11 | **composite_context** | structura 15D/90D + acord între timeframe-uri | SUPPORTIVE/NEUTRAL/CONTRADICTING (acord de locație) |

**De reținut la câteva:**
- **delta**: NU „pozitiv=BUY". Clasifică evoluția (accelerare/decelerare/flip) cu scală adaptivă.
- **absorption ≠ aggression-without-progress**: are condiții proprii (dominanță ≥1.8×, concentrare
  ≥22% din bară, locație extremă, respingere ≥55% din range, volum adaptiv). Bull = vânzare la minim
  absorbită + închide sus.
- **exhaustion**: climax (volum ≥2× mediana) la extremă nouă cu delta în trend → potențial reversal.
  Distinct de absorption (acolo e respingere în-bară; aici climax + reversal ulterior).
- **poc_migration** folosește **developing POC**, nu ziua întreagă. ⚠️ Inerție târziu în sesiune
  (POC „lipicios") → des SIDEWAYS. Utilitate reală de validat.
- **session_context / composite_context**: gate cauzal `available_from` — Asia/Londra apar ca
  context abia după ce se închid; composite = istorie care se termină IERI (exclude ziua curentă).

### 5.3. `overall` (rezumatul, P6)
`overall ∈ {SUPPORTIVE, NEUTRAL, CONTRADICTING, INSUFFICIENT_EVIDENCE}`, prin **reguli
transparente** (cu listă `reasons`), NU scor/ML/BUY-SELL.
- Dovezi direcționale (bull/bear) DOAR din **delta, cvd_divergence, absorption, exhaustion**.
  poc/tape/lvn/sesiune/composite = context/reasons, nu leans.
- Regula: ambele direcții prezente → **CONTRADICTING**; ≥2 pe o singură direcție → **SUPPORTIVE**;
  altfel **NEUTRAL**; prea puține date → INSUFFICIENT.
- ⚠️ **„SUPPORTIVE" = dovezile sunt COERENTE (o direcție), NU „bullish".** Poate fi 2× bearish.
  Direcția e doar în `reasons`. (Vezi capcana de culoare în §8.)

---

## 6. UI desktop (`app/desktop/main.py`)

- **Clean Chart:** markerele (Big Trades/Absorption/Exhaustion) pornesc **OFF**. Grafic curat.
- **Tip:** `Profil` (lumânări + VP overlay) · `Footprint` (celule bid/ask) · **`Profile Only`** (nou, §7).
- **Vederi** (preset-uri): Curat · Order Flow · NY Open · Tot.
- **Perioadă VP** (⚙): Sesiune · Zi UTC · Composite săptămână/15D/90D · Visible · Custom range.
- **Panou „Context"** (toggle): secțiuni FLOW/STRUCTURE/LEVELS/LOCATION, human-readable, ascunde
  NONE, + `overall` colorat + `reasons` + disclaimer „Order flow context only." **Context-at-cursor:**
  treci cu mouse-ul peste o bară → contextul cauzal de la acel T. Se dezvoltă în replay (FORMING→CONFIRMED).
- **Technical Details:** toggle → câmpurile brute ale componentelor.
- **Replay** tick-cu-tick: play/pauză/viteză, scrubber, pas ±1 bară, seek rapid (checkpoints).
- **CVD** panou jos + grid statistici (ΣV/ΔV/Δ% + T/s). VWAP, POC/VA, HVN/LVN, sesiuni, „Ieri".
- **Fus (display):** Romania / New York / Chicago / UTC — DST-correct per dată (doar etichetele).

---

## 7. Profile Only (feature nou — branch `feat/profile-only`)

Mod fără lumânări: **câte un Volume Profile per perioadă, de-a lungul axei timpului**, split
buy/sell, POC accentuat — stil DeepCharts „Profile Only".

- **Selector nou** lângă Tip: `Zi` (un profil/zi) · `Asia`/`Londra`/`NY` (acea sesiune per zi) ·
  `Toate sesiunile` (3 profile/zi). Span-ul vine din Perioada VP (zi/săptămână/15D/90D).
- **Cum e corect pe fus:** sesiunile sunt ancorate pe **fusul bursei** (Tokyo/London/New York) prin
  `zoneinfo` → auto vară/iarnă, **independent de unde ești tu** (RO/Spania/oriunde).
- **Cod:** `data_service.period_profiles()` (reutilizează engine-urile + ferestrele de sesiune) +
  `charts.PeriodProfilesItem` (randare multi-profil cu culling) + wiring în `main.py`.
- Aditiv: căile Profil/Footprint/replay/context neatinse. 6 teste noi + suita totală verde.

---

## 8. Limitări cunoscute (din audit, cinstit)

1. **Composite 90D peste rollover** e incomplet: `load_many` alege UN singur contract → zilele
   celuilalt contract (pre-rollover) pică. 90D acoperă mai puține zile decât scrie. (15D = ok în contract.)
2. **Granița sesiunii = 22:00 UTC hardcodat** — corect vara (datele actuale), decalat cu o oră pe
   date de **iarnă** (nov–martie). Task de reparat (DST-aware via zoneinfo) — pornit separat.
3. **Detectori dubli** absorbție/exhaustion: legacy în `data_service` (praguri fixe, pt markerele
   de pe chart) vs adaptivi în `context_engine` (pt panou) — pot să nu fie de acord.
4. **„SUPPORTIVE" e colorat VERDE** chiar și când contextul e coerent-BEARISH → verde ≠ long.
   Citește `reasons`, nu culoarea.
5. **Valoarea predictivă a componentelor = NEVALIDATĂ statistic.** Follow-through pe 5 bare ≈ 48–52%
   (nivel de șansă) → confirmă că sunt **context, nu semnal**. Ce e util vs zgomot se află prin
   studiul de replay (`Desktop\VP-AUDIT\REPLAY-STUDY-PROTOCOL.md`), nu presupunând.
6. **Verificarea vizuală GUI** a lui Profile Only e încă de făcut manual (nu se poate auto-randa).
7. Cosmetic: warning-uri LF→CRLF pe Windows (inofensive).

---

## 9. Stare curentă + ce urmează

- **Context Engine** (11 componente + overall), cauzal, determinist, testat — **înghețat** pe `main`.
- **Profile Only** — pe branch, așteaptă verificare vizuală + merge.
- **Următorul pas real NU e cod nou** — e **validarea empirică prin replay** (protocolul de pe Desktop):
  afli ce informație are valoare reală înainte de orice schimbare de arhitectură.
- Task deschis: granița sesiunii DST-aware (înainte de backtesting pe iarnă).

---

*Generat pe baza codului real (commit `b3217da` + branch `feat/profile-only`). Pentru detalii
de implementare, codul e sursa de adevăr; acest document e harta.*
