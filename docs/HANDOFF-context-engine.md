# Volume Profile Terminal + Context Engine — HANDOFF pentru chat nou

> Lipește acest fișier în chat-ul nou ca să ai tot contextul.
> Data: 07.08.2026. Stare pe GitHub: commit `d666448`, **261 teste trec**, branch `main`.

---

## 0. Ce e proiectul
Terminal desktop de **Volume Profile & Order Flow** pentru **NQ** (Python, PySide6 + pyqtgraph, date Databento), în **`D:\Volume Profile`**. Uz personal: backtesting + învățat order flow, drum spre date live la NY open (16:30 RO).

**GitHub (PRIVAT):** `https://github.com/Serin15/volume-profile-terminal` — branch `main`.
**Rulare app:** `cd "D:\Volume Profile"; .venv\Scripts\python.exe run_desktop.py` (sau `start.bat`).
**Teste:** `.venv\Scripts\python.exe -m pytest -q` → **261 passed** (~12 min; unele teste ating date reale + composite 90D lent).

**FILOSOFIA PRODUSULUI (regula de aur, non-negociabilă):**
> „Asta este ce face order flow-ul în zona în care te afli. TU decizi dacă setup-ul tău de price action merită executat."
> Tool-ul e ANALIZĂ DE CONTEXT. **ZERO** BUY/SELL, semnale automate, scoruri, probabilități, ML, verdict de trade.

---

## 1. Date
- **62 zile parquet** pe git (`data/parquet/`, ~186MB): **mai (04-08) + iunie complet + iulie complet + 03-06 august 2026**. Contract activ NQU6.
- Adăugare zile noi: CSV Databento → `data/raw/` → `python scripts/convert_to_parquet.py`. Fișierele **DBN (.dbn.zst)** se convertesc cu `databento` (instalat în venv) — vezi `scratchpad` istoric sau `DBNStore.from_file().to_csv(pretty_px=True, pretty_ts=True, map_symbols=True)`.
- `data/raw/` (CSV brut) NU e pe git (mare, regenerabil).

---

## 2. Arhitectura (regula: engine-urile CALCULEAZĂ, nu desenează)
```
data/loader.py            citire parquet/CSV, alege contractul activ, granita sesiune 22:00 UTC
core/vp_engine.py         VolumeProfileEngine: POC/VA/HVN-LVN. + VolumeNode + compute_nodes (P1a)
core/delta_engine.py      DeltaEngine: buy/sell per nivel, CVD
core/context_engine.py    ★ CONTEXT ENGINE (P4-core..P6) - 11 componente + overall
app/desktop/data_service.py  load_day -> DayData; + build_reference_levels/build_composite_levels (P2/P3, aditive)
app/desktop/replay.py     Replay tick-cu-tick (cauzal, neatins de P4-P7)
app/desktop/charts.py     itemuri de randare
app/desktop/main.py       UI + panoul Execution Context (P6/P7)
scripts/validate_context.py  ★ harness validare pe date reale (P7)
```

**Context Engine — cum funcționează (cauzal prin construcție):**
- `Snapshot` (frozen) = TOATĂ informația la momentul T și NIMIC după. Câmpuri: `t/open/high/low/close/volume/cvd/poc/vah/val/footprint/row_size/tick_size/poc_series/tps/reference_levels/composite_levels`.
- `snapshot_from_daydata(day, upto_index=k, reference_levels, composite_levels)` = **granița anti-look-ahead**: feliază la ≤ k, ia POC/VA din valorile **developing** (dev_poc[k]) — nu din ziua întreagă.
- `ContextEngine.analyze(snapshot) -> ContextResult` = funcție PURĂ, DETERMINISTĂ. Produce `components` (11) + `overall` + `reasons`.
- Pattern comun: praguri **adaptive** la activitatea recentă; stări **FORMING → CONFIRMED** (comportamentul ulterior citit doar din bare ≤ T; nimic din viitor).

---

## 3. Cele 11 componente (în `ContextResult.components`)
1. **delta** — evoluția delta: `BUYING/SELLING _AGGRESSION/_ACCELERATION/_DECELERATION`, `DELTA_FLIP`, `NEUTRAL`. NU „pozitiv=BUY".
2. **price_progress** — efort (delta) vs rezultat (ticks): `AGGRESSION_WITH/WITHOUT_PROGRESS`, `PROGRESS_WITHOUT_AGGRESSION`, `QUIET`, `NEUTRAL`, + efficiency + direction_alignment.
3. **absorption** / **exhaustion** — stări cu confirmation window: `BULL/BEAR_ABSORPTION_FORMING/CONFIRMED/FADED`, `TOP/BOT_EXHAUSTION_*`. Condiții proprii (NU = aggression-without-progress).
4. **cvd_divergence** — swing structural: `BULLISH/BEARISH_DIVERGENCE` / `NO` / `INSUFFICIENT`, status FORMING→CONFIRMED, strength (magnitudine, NU scor).
5. **poc_migration** — POC developing: `POC_RISING/FALLING/SIDEWAYS` + STRONG/WEAK. NU „rising=bullish".
6. **lvn_interaction** — zona reală VolumeNode: `TEST/REJECTION/ACCEPTANCE/FAST_TRAVERSAL/FAILED_REJECTION`.
7. **acceptance_rejection** — același motor pe nivelul cel mai apropiat (POC/VAH/VAL).
8. **tape_speed** — trades/sec, contracts/sec, delta/sec; `HIGH/NORMAL/LOW` + ACCELERATING/DECELERATING. Viteza SEPARATĂ de direcție.
9. **session_context** — sesiuni precedente (POC/VAH/VAL/HVN/LVN), poziția pretului (ABOVE/INSIDE/BELOW_VALUE). Gate cauzal `available_from` (Asia/Londra apar doar după ce se închid).
10. **composite_context** — 15D/90D + confluențe/conflicte între timeframe-uri; `context` SUPPORTIVE/NEUTRAL/CONTRADICTING prin reguli transparente + `reasons`.
11. **overall** (P6) — rezumat transparent {SUPPORTIVE/NEUTRAL/CONTRADICTING/INSUFFICIENT_EVIDENCE} din reguli explicite; dovezi direcționale DOAR din delta/cvd/absorption/exhaustion; poc/tape/lvn/sesiune/composite = context/reasons, NU leans. Fiecare overall are `reasons`.

---

## 4. UI (P6/P7) — în `main.py`
- **Clean Chart:** markerele Big Trades/Absorption/Exhaustion pornesc **OFF**. Grafic curat (candles+VP+POC/VA+VWAP). Engine-ul calculează tot; doar overlay-ul e separat.
- **Panou „Context"** (toggle în bara de straturi, dreapta graficului): secțiuni FLOW/STRUCTURE/LEVELS/LOCATION, **human-readable**, ascunde NONE, + disclaimer „Order flow context only. Your price-action setup decides execution."
- **Context-at-Cursor:** panoul urmărește bara de sub cursor (throttle pe bară) + bara curentă din replay, **cauzal** (upto_index). FORMING→CONFIRMED se dezvoltă în replay.
- **Technical Details:** toggle deasupra panoului → câmpurile brute ale componentelor.
- Niveluri (prev session + composite 15D) cache-uite per zi. 90D NU e în panoul live (lent).

---

## 5. STARE: FROZEN. Ce e gata
- P1a, P4-core, P4.1–P4.5, P1b, P5, P2, P3, P6 + P7 (Clean Chart/UX + harness) — **toate commit-uite, 261 teste verzi**, fiecare fază commit separat.
- `data_service` atins doar aditiv; `replay` + detectorii legacy **neatinși**.
- **Decizia curentă (a userului): STOP pe funcționalitate.** Nu se mai adaugă componente/indicatori/semnale/UI. Nu se modifică algoritmii existenți.

---

## 6. URMĂTOAREA FAZĂ (când decide userul): VALIDARE EMPIRICĂ — NU componente noi
Scop: să separăm **informația cu valoare reală** din Context Engine de **zgomot**, ÎNAINTE de orice schimbare de arhitectură.
- Harness: `python scripts/validate_context.py` — scanează sesiuni reale, auto-descoperă exemple pentru 12 categorii (A-L), context cauzal la T + outcome după N bare (doar validare).
- **Descoperire cheie (onestă):** follow-through absorption/exhaustion/CVD-divergence pe 5 bare ≈ **48-52%** = nivel de șansă → **confirmă că sunt CONTEXT, nu semnal**. Corect conceptual; de decis empiric ce e util vs zgomot.

---

## 7. Riscuri / de validat ulterior
1. **Ce e semnal util vs zgomot** — de stabilit empiric (faza următoare). NU transforma componentele în semnale.
2. **Praguri sensibile:** high-tape ~13% din bare, LVN rejection ~63/zi, absorption ~30/zi — poate prea permisive pentru „eveniment notabil". Semnalate, **NETUNATE** (nu se tunează pe exemple izolate; se testează pe tot setul).
3. **Stări persistente:** un eveniment apare ~scan_lookback bare (poate părea „nou" la fiecare bară). Propus (nefăcut): „bars since" în panou.
4. **Performanță Context-at-Cursor:** `analyze_lvn_interaction` reconstruiește VP din footprint la fiecare bară → posibil lag pe hover într-o sesiune întreagă; de măsurat pe GPU real.
5. **VERIFICARE VIZUALĂ REALĂ nefăcută** — offscreen confirmă textul, nu GUI-ul nativ. Userul trebuie să deschidă app, bifeze „Context", testeze hover + replay pe câteva zile.
6. Cosmetice: warning-uri LF→CRLF (inofensive pe Windows).

---

## 8. Nota operațională (din handoff-uri vechi, încă validă)
`run_desktop.py` lasă 2 procese python/instanță. La debugging: închide TOATE instanțele întâi, apoi lansează una singură.

---

## 9. TL;DR pentru chat nou
Context Engine complet (11 componente + overall transparent), cauzal, determinist, testat (261), pe GitHub `d666448`. UI curat cu panou Context la cursor + Technical Details. **Următorul pas NU e cod nou — e validarea empirică** a ce informație are valoare reală. Principiul: context descriptiv, niciodată BUY/SELL. Toate fazele P1a-P7 sunt înghețate.
