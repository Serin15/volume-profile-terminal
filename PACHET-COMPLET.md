# Pachet complet — Volume Profile Terminal (ce avem + TESTAT)

Stare la zi a proiectului: tot ce e construit + tot ce e verificat. Tool desktop de
order flow pentru NQ (E-mini Nasdaq-100), date reale Databento, look stil DeepCharts.

---

## 1. FEATURE-URI COMPLETE (ce avem)

### Volume Profile
- **POC** (Point of Control)
- **Value Area** (VAH/VAL) — algoritm corect de expansiune din POC
- **HVN** (High Volume Nodes) — vârfuri de volum, linii cyan cu etichetă
- **LVN** (Low Volume Nodes) — goluri de volum, linii gri cu etichetă
- Profil **overlay** translucid peste preț (stil DeepCharts 1:1), split buy/sell
- **Composite** pe săptămână (mai multe zile combinate)

### Order Flow / Delta
- **Delta per nivel** (buy vs sell agresiv)
- **Cumulative Delta** (cifra sesiunii)
- **CVD** — panou separat sub grafic, linie developing în timp (divergențe preț vs delta)
- **VWAP** developing
- **Big Trades** — bule la tranzacțiile individuale mari (≥25 pe NQ), mărime = volum, verde/mov, on/off
- **Absorption** — markere la extrema respinsă (volum agresiv absorbit, preț nu continuă):
  triunghi verde sub minim = suport (bull), mov peste maxim = rezistență (bear); on/off
- **Nivelurile sesiunii precedente** (backtesting) — yPOC / yVAH / yVAL + PDH / PDL ale zilei de
  ieri, linii de referință fixe pe ziua curentă (auriu + albastru-oțel), etichete pe stânga; on/off

### Footprint (Deep Print)
- **Celule bid/ask** colorate pe imbalance (verde=buy domină, mov=sell)
- **Numere „sell×buy"** în celule (apar la zoom)
- **Delta total per lumânare** (impuls) — rând la baza graficului
- **Imbalances** — contur luminos (metoda diagonală ATAS, prag 3:1), verde/mov;
  consecutive = stacked imbalance
- **Readout pe crosshair** — buy/sell/delta la celula de sub mouse

### Replay (tick-by-tick)
- Lumânarea curentă **se formează tick cu tick** (open fix, high/low se întind, close se mișcă)
- Profilul/footprint/CVD/VWAP/delta **se dezvoltă live**
- **Auto-follow** — urmărește prețul; la zoom manual se dezactivează singur; buton „Follow" re-centrează
- Play / Pauză + viteze (lent → 10x)
- **Backtesting — control replay complet:** scrubber (tragi oriunde, înainte/înapoi), pas ±1
  lumânare (butoane + săgeți ← →), ⏮/⏭ start/final, sari la minut exact (HH:MM), spațiu = play/pauză;
  seek instant prin checkpoints (median ~25ms chiar pe sesiuni de 300k+ tick-uri)
- **Unelte de desen (backtesting):** nivel, trendline, dreptunghi/zonă (editabile: mut+redimensionez),
  fib, măsură (puncte/ticks/%/timp), **Long/Short position** (3 clickuri Entry/Stop/Target → puncte + R:R + $);
  **magnet cu Ctrl** (lipit de OHLC, ca TV); preview live, undo/clear, Esc/Delete; pe durata sesiunii
- **Intrare replay pe pauză** (arată sesiunea completă, derulezi cu scrubber unde vrei) · toggle-uri
  (HVN/LVN, VP, Footprint) și schimbarea intervalului **nu resetează** poziția/zoom-ul din replay
- **VP + Footprint simultan** (checkbox VP independent) · **zoom pe scala de preț** (trage de axă)

### Interfață / control
- **Ziua** (bearish/range-bound etichetat)
- **Tip**: Profil / Footprint
- **Perioada**: 1 zi / Săptămână (composite)
- **Vedere**: Sesiune (22:00→22:00 UTC) / Zi UTC
- **Interval**: 1min → 1D (1/5/15/30min, 1/2/4h, 1D)
- **VA %**, **Rezoluție** (0.25→5.0), **HVN/LVN** on/off
- **Fus orar**: Romania (implicit) / New York / Chicago / UTC — ora de vară/iarnă corectă
  automat per data zilei (zoneinfo); implicit RO ca 16:30 = deschiderea NY (potrivire cu TradingView)
- Carduri: Simbol, POC, VAH/VAL, Volum total, Cumulative Delta
- Temă dark, lumânări verde/mov crisp, crosshair cu snap la lumânare

### Unelte CLI (scripts/) + prototip web (Streamlit)

---

## 2. FIȘIERE

```
core/        vp_engine.py, delta_engine.py            (motoare calcul)
data/        loader.py + raw/ (10 CSV) + parquet/     (strat date)
app/desktop/ data_service.py, charts.py, replay.py, drawings.py, theme.py, main.py
app/         streamlit_app.py                          (prototip web)
scripts/     8 unelte CLI
tests/       test_vp_engine, test_delta_engine, test_loader, test_nodes, test_footprint
run_desktop.py, pyproject.toml, requirements.txt
DOCUMENTATIE.md, INSPIRATIE-platforme.md, PACHET-COMPLET.md
```

---

## 3. TESTAT — verificare completă

### ✅ 53 teste automate (pytest) — toate trec

**Volume Profile engine (5):**
| Test | Ce verifică |
|---|---|
| test_poc_value_area_synthetic | POC + Value Area corecte (date sintetice) |
| test_tick_index_no_float_key_errors | bucketing preț fără erori de float |
| test_hvn_peaks_bimodal | HVN detectate corect (2 vârfuri) |
| test_lvn_within_hvn_range | LVN restrânse în intervalul HVN (fără zgomot din cozi) |
| test_empty_engine | engine gol nu crapă |

**Delta engine (2):**
| Test | Ce verifică |
|---|---|
| test_delta_basic | buy/sell/delta/cumulative corecte |
| test_side_normalization | normalizare side (B/A, spații, litere mici) |

**Loader (5):**
| Test | Ce verifică |
|---|---|
| test_symbol_auto_selection | alege simbolul activ (volum max, NQU6) |
| test_side_preserved | câmpul `side` păstrat corect |
| test_price_volume_side_shape | structura tick-urilor (price, size, side) |
| test_session_boundary | granița de sesiune 22:00 UTC → grupare corectă |
| test_session_date_for_rule | regula de sesiune futures |

**HVN/LVN/POC — pe DATE REALE (5):**
| Test | Ce verifică |
|---|---|
| test_hvn_are_peaks_above_mean | fiecare HVN are volum PESTE medie (vârf real) |
| test_lvn_are_valleys_below_mean | fiecare LVN are volum SUB medie (vale reală) |
| test_node_counts_bounded | max 5 HVN / 3 LVN (fără aglomerare) |
| test_poc_is_the_highest_volume_level | POC = nivelul cu volumul maxim |
| test_poc_is_the_tallest_displayed_bar | POC = cea mai groasă bară afișată (aliniere) |

**Footprint + CVD — pe DATE REALE (4):**
| Test | Ce verifică |
|---|---|
| test_footprint_totals_match_raw | suma celulelor = total buy/sell real (la unitate) |
| test_footprint_cell_matches_raw | o celulă = recalcul direct din tick-uri brute |
| test_footprint_delta_sums_to_cumulative | delta/lumânare, sumă = Cumulative Delta |
| test_cvd_last_equals_cumulative_delta | CVD final = Cumulative Delta, aliniat cu lumânările |

**Backtesting / seek replay — pe DATE REALE (3):**
| Test | Ce verifică |
|---|---|
| test_seek_forms_exact_candles | seek la lumânarea j → exact j+1 lumânări, epoca corectă |
| test_backward_seek_matches_forward | seek înapoi (checkpoint) = stepping forward, fără drift |
| test_last_candle_equals_full_day | ultima lumânare din replay = încărcarea full-day |

**Absorption — SINTETIC determinist (6):** bull/bear fires corect, echilibrat/sub-prag/fără-respingere
= niciun semnal, lumânarea în formare exclusă. (fără fals-pozitive)

**VWAP + Big Trades — pe DATE REALE (3):** VWAP finit + în interval [low,high] + = formula
cumulativă; Big Trades = exact tick-urile ≥ prag, cu side/mărime corecte.

**Determinism replay — pe DATE REALE (2):** aceeași stare indiferent de viteză (pas 3 vs 5000);
stepping până la finalul unei lumânări = seek direct la ea.

**Integrare GUI (offscreen) — pe DATE REALE (15):** construiește fereastra reală și parcurge
matricea interval×rezoluție×mod×tip + săptămână + replay-navigare + desen; verifică invarianți
(VA conține POC, POC în interval, CVD=cumΔ, footprint=totaluri) — zero crash-uri, zero încălcări.

**Nivelurile sesiunii precedente — pe DATE REALE (3):** yPOC/yVAH/yVAL/PDH/PDL = valorile zilei
precedente încărcate independent; ordinea coerentă (low≤val≤poc≤vah≤high); prima zi = fără precedent.

### ✅ Verificări independente (manuale, făcute pe parcurs)
- **POC/VAH/VAL/Delta** — recalculate cu pandas brut (fără motorul nostru), potrivire la virgulă
- **HVN/LVN** — mini-histograme locale (fiecare linie = vârf/vale vizibil)
- **Footprint** — celula `1030×1013` (09.07 19:55) = identică cu recalculul din tick-uri brute
- **Granița de sesiune 22:00 UTC** — confirmată cu surse externe (CME Globex)
- **Matrice de combinații**: mod ZI **96/96** OK + mod complet (+ săptămână) **68/68** OK
  (zi/săptămână × sesiune/UTC × toate intervalele × toate rezoluțiile, zero erori)
- **Toate cele 7 scripturi CLI** rulează fără eroare pe date reale
- **CVD final = Cumulative Delta** (-4188 pe 22 iul), **delta/lumânare sumă = total**

---

## 4. SETĂRI TEHNICE
- Instrument: NQ, contract activ **NQU6** (ales automat după volum)
- tick_size real 0.25 · Value Area 70% · sesiune 22:00→22:00 UTC
- Databento schema **Trades** ($28/GB); `side`: A=sell aggressor, B=buy aggressor
- Date: **3 regimuri validate, 15 zile** — bearish (20-24 iul), range-bound (6-10 iul),
  **bullish (4-8 mai, +1510 puncte)**. ~$105 credit Databento rămas (istoric = practic gratis).

---

## 5. CUM RULEZI
```powershell
cd "D:\Volume Profile"
.\.venv\Scripts\python.exe run_desktop.py          # aplicația
.\.venv\Scripts\python.exe -m pytest -q            # testele (53 passed)
```

---

## 6. CE NU E FĂCUT ÎNCĂ (onest)

**Pe datele actuale (Trades) — se pot face (gratis):**
- Exhaustion (climax) · POC per lumânare · Fixed/Visible Range profile · footprint moduri
- Persistență desen pe disc (opțional, dacă se dorește mai târziu)

**Necesită date noi (MBP-10 / MBO de la Databento):**
- DOM (Depth of Market)
- Liquidity Heatmap (Bookmap) · Iceberg detection

**Decizie de bani:**
- **Date LIVE** (Databento Standard $199/lună sau Tradovate/Rithmic)

**Debit tehnic cunoscut:**
- Randare **full-redraw** la fiecare cadru → de trecut la **randare incrementală**
  (doar ultima lumânare) înainte de live / footprint greu, ca să rămână fluid.

**Alte faze:** Backtesting (manual → automat cu reguli/statistici); comercializare (auth/billing).
