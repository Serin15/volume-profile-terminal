# Cum sunt construite platformele mari (Sierra / ATAS / DeepCharts / Bookmap) — și ce furăm

Document de cercetare: cum e construită fiecare, ce tool-uri au, și **ce merită adăugat
la noi**, prioritizat. Concluzia cheie: **fundamentul real e STRATUL DE DATE**, nu UI-ul.

---

## 1. Cum e construită fiecare

| Platformă | Bază tehnică | Date | Notă |
|---|---|---|---|
| **Sierra Chart** | motor **C++ nativ** (viteză), studii custom în **ACSIL** (C++) | order book real (tick-by-tick, DOM) | cel mai rapid/granular; desktop; "cumperi un schelet + construiești" |
| **ATAS** | **.NET / C#**, API de indicatori custom | order flow + DOM (Level II) | **400+ variații de footprint**, Smart DOM; desktop |
| **DeepCharts** | **web (browser)**, fără download | **MBO** (market-by-order) prin Rithmic/CQG | footprint "Deep Print", DOM ladder, 80+ indicatori, risk manager, trade copier |
| **Bookmap** | rendering **GPU 40fps** | **MBO** | specializat pe **heatmap de lichiditate** (ordine limită în timp) |

**Lecția pentru noi:** arhitectura noastră (motor Python în `core/` = "creierul", separat
de UI pyqtgraph) e exact modelul Sierra/DeepCharts — engine reutilizabil + interfață peste.
"ACSIL-ul" nostru sunt engine-urile din `core/`. Direcția e corectă; diferența e maturitatea
și **stratul de date**.

---

## 2. STRATUL DE DATE = fundamentul real (cea mai importantă concluzie)

Ce feature-uri poți construi depinde DIRECT de granularitatea datelor. Trei niveluri:

| Schema Databento | Ce conține | Ce DEBLOCHEAZĂ | Noi |
|---|---|---|---|
| **Trades** ($28/GB) | tranzacții executate + `side` (agresor) | Volume Profile, **Footprint**, **Delta/CVD**, **Big Trades** | ✅ **folosim asta** |
| **MBP-1** | top of book (bid/ask 1 nivel) | delta mai precis, clasificare | testat parțial |
| **MBP-10** | top **10 niveluri** de preț | **DOM ladder** (10 niveluri), imbalance de carte | de adăugat |
| **MBO** | **fiecare ordin** individual (queue, iceberg) | **heatmap de lichiditate** (Bookmap), iceberg detection, DOM complet | de adăugat |

**Trei familii de tool-uri de order flow:**
1. **Volum executat** (din Trades) → VP, Footprint, Delta/CVD, Big Trades — **avem baza**
2. **Lichiditate curentă** (din MBP/DOM) → DOM ladder, imbalance — *ne trebuie MBP-10*
3. **Lichiditate în timp** (din MBO) → **heatmap Bookmap** — *ne trebuie MBO*

**Vestea bună:** Databento (furnizorul nostru) are **toate** schemele astea (MBP-1, MBP-10, MBO)
și chiar publică un exemplu de **heatmap de lichiditate pe MBO în Python**. Deci putem construi
DOM + heatmap din **aceeași sursă** — doar schimbăm schema descărcată (mai scumpă ca Trades).

---

## 3. Inventar de feature-uri ("furăm din fiecare") — AVEM / DE ADĂUGAT

### ✅ Avem deja
- Volume Profile (POC, VAH/VAL, HVN/LVN) — verificat, testat
- Delta per nivel + Cumulative Delta
- **Footprint** (Bid×Ask în celule, imbalance) — modul de bază, ca "Deep Print"
- VWAP developing
- Sesiune + composite multi-zi
- **Replay tick-by-tick** (ca "Deep Replay" / market replay Sierra) + **control complet de
  backtesting** (scrub oriunde înainte/înapoi, pas ±1 bar, jump-to-minut) — ca TradingView/DeepCharts
- **Unelte de desen** (nivel, trendline, dreptunghi, fib, măsură) — ca TradingView
- **Big Trades** (bule la tranzacții ≥ prag) — ca "Big Trades" ATAS
- **Absorption** — markere la extreme respinse (volum agresiv absorbit) — semnal order flow ATAS/DeepCharts
- Look dark stil DeepCharts, fus orar reglabil

### 🔨 De adăugat DIN DATELE ACTUALE (Trades) — ieftin, fezabil
1. ✅ **Cumulative Delta ca panou/linie în timp** (CVD) — FĂCUT
2. ✅ **Big Trades / detecție ordine mari** (bule) — FĂCUT
3. **Footprint — moduri multiple** (ATAS are 400+): Volume / Delta / Bid×Ask / imbalance diagonal evidențiat
4. ✅ **Absorption** — FĂCUT (markere la extreme respinse, volum agresiv absorbit)
5. ✅ **Imbalance highlighting** în footprint — FĂCUT (metoda diagonală ATAS 3:1)

### 🔨🔨 De adăugat CU DATE NOI (MBP-10 / MBO) — mai scump, mai mult efort
6. **DOM ladder** (10 niveluri bid/ask) — necesită MBP-10
7. **Liquidity Heatmap (Bookmap-style)** — ordine limită în timp, necesită MBO (Databento are exemplu)
8. **Iceberg / ordine ascunse** — necesită MBO

### 💰 Straturi de produs (nu de analiză)
9. Risk Manager (limite zilnice, per-trade) — DeepCharts/execuție
10. Trade Copier (mirror pe mai multe conturi) — execuție/broker
11. Alerte, unelte de desen, multi-instrument, layout-uri salvate

---

## 4. Recomandare — ordinea de adăugat (valoare × fezabilitate)

**Etapa A — pe datele actuale (Trades), gratis:**
1. ✅ **CVD** (Cumulative Delta ca linie/panou în timp) — FĂCUT
2. ✅ **Big Trades** (bule la tranzacții mari) — FĂCUT
3. ✅ **Absorption** (markere la extreme respinse) — FĂCUT
4. ✅ **Backtesting Bloc 1** (control replay: scrub oriunde înainte/înapoi, pas ±1 bar, jump-to-minut) — FĂCUT
5. ✅ **Backtesting Bloc 2** (unelte de desen: nivel, trendline, dreptunghi, fib, măsură) — FĂCUT
6. **Exhaustion** (climax de volum/delta la extrema trend-ului) · **Footprint moduri** (Volume/Delta) — URMĂTORUL

**Etapa B — decizia de date (MBP-10 / MBO de la Databento):**
5. **DOM ladder** (MBP-10)
6. **Liquidity Heatmap** (MBO) — feature-ul "wow" Bookmap, dar cel mai scump ca date + randare

**Etapa C — LIVE** (Databento Standard $199/lună sau Tradovate/Rithmic) — saltul real spre "ca DeepCharts"

**Etapa D — produs:** risk manager, copier, alerte, multi-instrument (doar dacă comercializezi)

> Principiu: rămânem pe **executed volume** (Trades) cât timp mai avem de stors valoare acolo
> (CVD, Big Trades, footprint modes). DOM + Heatmap = pasul care cere date noi (MBP-10/MBO).
> Live = pasul care cere bani lunari. Le facem în ordinea asta.

---

## Surse
- [ACSIL — Sierra Chart (docs oficiale)](https://www.sierrachart.com/index.php?page=doc%2FAdvancedCustomStudyInterfaceAndLanguage.php)
- [What Is ACSIL? — SCS](https://www.scstudies.com/blog/what-is-acsil-sierra-chart-traders-guide)
- [ATAS — Footprint Analysis](https://atas.net/footprint-charts/)
- [ATAS Order Flow features — AMP Futures](https://www.ampfutures.com/trading-platform/atas)
- [DeepCharts — Deep Print (Footprint)](https://www.deepcharts.com/helpcenter/article/deep-print-(footprint%C2%AE))
- [DeepCharts pe Optimus Futures (MBO, Rithmic/CQG)](https://optimusfutures.com/deepcharts-futures-trading-platform.php)
- [Bookmap — Heatmap & Liquidity](https://bookmap.com/en/features)
- [Databento — Market by order (MBO)](https://databento.com/docs/schemas-and-data-formats/mbo)
- [Databento — Market by price (MBP-10)](https://databento.com/docs/schemas-and-data-formats/mbp-10)
- [Databento — exemplu Liquidity Heatmap pe MBO în Python](https://roadmap.databento.com/roadmap/example-liquidity-heatmap-on-mbo-data-in-python)
