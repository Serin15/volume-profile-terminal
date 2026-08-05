# Volume Profile Terminal — Handoff pentru chat nou

> Document de continuare. Lipește-l în chat-ul nou ca să am tot contextul.
> Data: 05.08.2026. Ultima stare cod pe GitHub: commit `d57444f`, 78 teste trec.

---

## 1. Ce e proiectul

Terminal desktop de **Volume Profile & Order Flow** pentru **NQ** (E-mini Nasdaq futures),
scris în **Python (PySide6 + pyqtgraph)**, pe date reale **Databento**. Uz personal pentru
**backtesting + învățat order flow**, drum spre date live pentru tranzacționare la NY open
(16:30 RO / 09:30 ET).

- **Locație:** `D:\Volume Profile`
- **GitHub (PRIVAT):** `https://github.com/Serin15/volume-profile-terminal` — branch `main`
- **Rulare:** `cd "D:\Volume Profile"; .venv\Scripts\python.exe run_desktop.py` (sau `start.bat`)
- **Teste:** `.venv\Scripts\python.exe -m pytest -q` → **78 passed**
- **Arhitectură:** `core/` (vp_engine, delta_engine — calculează, NU desenează) → `data/` (loader + Parquet) → `app/desktop/` (main.py, charts.py, data_service.py, replay.py, drawings.py, theme.py)
- **Python 3.14, pyqtgraph 0.14.0, PySide6** (versiuni noi — relevant pentru bug-ul de hover, vezi §4)

## 2. Cum îl mut pe alt PC

**Codul ȘI datele parquet sunt pe git acum** (parquet = doar 55MB, versionat intenționat).
Pe PC nou:
1. Instalezi Python 3.14 (Add to PATH) + Git.
2. `git clone https://github.com/Serin15/volume-profile-terminal.git "Volume Profile"`
3. Dublu-click **`setup.bat`** → gata (cod + date + app).
- Update-uri: `git pull`. Modificări: `git add -A && git commit -m "..." && git push`.
- CSV brut (`data/raw`, 767MB) NU e pe git (regenerabil, opțional).
- **Deschidere rapidă de oriunde:** butonul **📂** (lângă ZIUA) încarcă orice CSV/Parquet de pe Desktop, fără git.

---

## 3. Ce am făcut în sesiunea asta (tot, grupat)

Punctul de plecare: discuție cu un trader „pro" (DeepChart) → 4 features + apoi multe altele.

### Features „pro" (din workflow-ul lui)
- **LVN pe tot profilul** — toggle în ⚙ VP; detectează LVN inclusiv spre margini (discount/premium), nu doar între HVN. Motorul avea `lvn_within_hvn`, l-am expus.
- **Composite configurabil** — opțiuni noi „Composite 15 zile" + „Composite 90 zile (bias)" (funcția `_last_n_days_block`, span-uri `15d`/`90d`).
- **Profile per-sesiune (Asia/Londra/NY)** — VP separat pe fiecare sesiune (POC/VAH/VAL + LVN), 2 moduri: „Fus real" (auto DST via zoneinfo) sau „Ore RO fixe", ore editabile. Checkbox „Sesiuni". Culori: Asia indigo / Londra verde / NY mauve. Etichete decalate pe 3 coloane să nu se suprapună.
- **Speed of tape** — rând nou „T/s" în grid = print-uri/secundă per lumânare (independent de volum). Colorat pe **delta** (histogramă: înălțime=viteză, culoare=cine domină, stil DeepChart).

### Footprint
- **POC per lumânare** — conturul magenta pe nivelul cu volum max din fiecare bară.
- **Numere colorate** — `sell×buy` colorat după cine domină (verde/mov).
- **Delta duplicată scoasă** (era și footer footprint, și rând ΔV în grid).
- **Stil „Bule"** — footprint ca pastile rotunjite (un număr/nivel), comutabil din ⚙ Footprint (Căsuțe / Bule). Cerut după un reel DeepChart.

### UI / anti-aglomerare
- **Vederi (preset-uri)** — dropdown care aprinde un set gândit de straturi: Curat / Order Flow / NY Open / Tot. Anti-aglomerare.
- **Fereastra pornește MAXIMIZATĂ** (era 1500x900) → graficul umple ecranul.
- **Chart pe tot spațiul** — când Grid/CVD stinse, rândurile se colapsează (pretul ia tot); grid stins → dispar și etichetele T/s/ΣV/ΔV/Δ%.
- Bare de sus mai subțiri; card „Cumulative Delta" → „CVD"; VWAP puțin mai stins (context).
- **Buton 📂 „deschide fișier de oriunde"** (CSV/Parquet direct de pe Desktop).

### Instrumente / interacțiune
- **Bar Info la click** — panou „data window" (colț stânga-sus): OHLC, Range, Body, Wick, Vol, Trades, **Average Trade Size**, Δ/Δ%, **Efficiency** (vol/tick, cu descriptor data-driven „efort mare/eficient"), distanță POC/VWAP. **DUBLU-click** arată, **click simplu** ascunde.
- **Long/Short Position stil TradingView** — REFĂCUT: 1 click = Entry, Stop+Target apar automat (R:R 1:2), toate 3 liniile **mobile** (tragi → R:R + $ live). Înainte: 3 clickuri fixe.
- **Tooltips sidebar** corectate + îmbogățite (nume bold + descriere).

### Date pe git
- **`data/parquet/` (17 zile, 55MB) urcat pe GitHub** → pe PC nou vin cu `git clone`, fără copiere manuală. `data/raw/` rămâne exclus.

### Bug-uri reparate
- **Big Trades halo** — bulele aveau contur alb + fill opac → se văd pe orice footprint (culoarea = direcția).
- **Bar-step păstrează zoom** — `_nav_render` nu mai forța „follow" (fereastră fixă 78 bare); acum păstrează exact zoom-ul (X+Y).
- **Footprint LOD** — footprint vizibil până la 220 lumânări (heatmap compact la zoom-out); numere de la 30px (mai multe lumânări lizibile). Sfat: mărește „Grupare (rezoluție)" pe footprint = mai compact.
- **Markere mereu vizibile** — Big Trades/Absorption/Exhaustion nu se mai ascund la zoom-out.

---

## 4. ⚠️ BUG DESCHIS (de continuat) — hover pe Absorption/Exhaustion NU afișează cardul

**Simptom:** treci mouse-ul pe un triunghi (Absorption) sau romb (Exhaustion) → **nu apare tooltip-ul**. (Big Trades — bulele — par să meargă intermitent; abs/exh NU.)

**Ce am reparat deja (3 cauze reale găsite, dar bug-ul persistă):**
1. **pyqtgraph 0.14 nu mai activează `acceptHoverEvents` din `hoverable=True`** → `sigHovered` nu se declanșa. Fix: `setAcceptHoverEvents(True)` explicit pe cele 3 scatter-e. (commit `3fc3908`)
2. **Qt nu livrează deloc `hoverEvent` la scatter** (chiar cu acceptHoverEvents=True) → am făcut **livrare MANUALĂ**: `_marker_hover_at(vb, pt)` apelat din `_on_mouse` (sigMouseMoved merge sigur — crosshair-ul o dovedește), detectează proximitatea markerelor în px. (commit `595d799`)
3. **Cardul se extindea în SUS și ieșea din ecran** la markerele de sus → ancoră dinamică. (commit `de8d685`)
4. **Big Trades fura selecția** când hover-uiai pe lângă centru → prioritate abs/exh peste big trades. (commit `d57444f`)

**Diagnostic prin log (în aplicația reală, live):**
- `_marker_hover_at` ESTE apelat (sigMouseMoved merge). ✅
- best_d ajunge la ~1-5px pe absorbție (detecție OK). ✅
- Alege corect abs/exh (`will_show=True`, `info=('abs','bull',...)`). ✅
- `_on_marker_hover` e apelat, `info` e valid, **`card_vis=True`** (cardul E setat vizibil). ✅
- **DAR userul tot nu vede nimic** → problema pare de **POZIȚIE**: cardul e „vizibil" dar plasat unde nu se vede.
- Testele OFFSCREEN trec (cardul se randează + hang-down pe ancoră) — deci codul „merge" izolat.
- `setAnchor` EXISTĂ în pg.TextItem 0.14 (verificat).

**Următorul pas (unde am rămas):** adăugasem log care înregistrează **poziția reală a cardului** (`hover_card.pos()`) vs. **view range** + ancora, ca să văd dacă `in_view=True/False`. Trebuie relansat și verificat log-ul. Ipoteză: cardul ajunge în afara `viewRange` (poziționare greșită la ancora dinamică în app-ul real) SAU e acoperit/clipuit. **De verificat: `card_pos` vs `view_x/view_y` din log; dacă `in_view=False` → fix la poziționare (clamp în vedere).** Codul de debug a fost SCOS (repo curat); se recreează ușor în `_marker_hover_at`.

**Notă operațională importantă (a cauzat mult timp pierdut):** `.venv\Scripts\python.exe run_desktop.py` lasă **2 procese python** per instanță (launcher venv + app = 1 fereastră). Se deschideau **multe ferestre** și userul testa una veche. La debugging: **închide TOATE instanțele** întâi (`Get-CimInstance Win32_Process ... run_desktop.py | Stop-Process`), apoi lansează una singură.

---

## 5. Concluzia strategică despre platformă (discutată, importantă)

Tool-ul e **matur funcțional** — nu-i lipsesc instrumente esențiale. Problema nu e „ce lipsește", ci **rafinarea + folosirea**. Direcția cu impact NU e încă 10 indicatori, ci ca platforma să **explice** piața, nu doar s-o afișeze — dar **descriptiv** (nu prescriptiv „Bias: Short" = semnale = risc). Recomandare onestă:
1. Câștiguri ieftine descriptive (Bar Info, Avg Size, Efficiency — FĂCUTE) care ajută la învățat.
2. UX mic (iconițe, tooltips — parțial).
3. **FOLOSEȘTE-L** pe backtest luni de zile → vezi ce-ți lipsește cu adevărat.
4. Smart Context / narațiune DOAR dacă decizi conștient că faci produs de vândut (nu înainte de a-l folosi).
NU adăuga RSI/MACD/Bollinger — ar dilua identitatea. Superioritatea reală vs. ATAS/Sierra = **înțelegi complet codul și-l modifici în minute.**

---

## 6. Setări recomandate Absorption / Exhaustion (discutate)

Absorbția e rară la NY open (mișcări direcționale, nu resping) = corect. Reglabil în ⚙:
- **Absorption** (mai sensibil): Volum minim 70→55, Dominanță 1.8→1.6, Respingere 60%→50%.
- **Exhaustion** (mai strict, ai prea multe overnight): Climax volum 2.0→2.5, Delta 20%→25%.
Se aplică live. Experimentează pe backtest.

---

## 7. Commits cheie sesiune (pe `main`, toate pushed)

`edd0e43` markere mereu vizibile + Bar Info dublu-click · `3fc3908`/`595d799`/`de8d685`/`d57444f` fix-uri hover (parțiale) · `39e7d4f` Bar Info + tooltips · drawable Long/Short · buton 📂 · `6a90fc9` date parquet pe git · UI maximize/declutter · Vederi · Bule · speed-of-tape/footprint readability · features pro (LVN full, composite, sesiuni, speed of tape).

**Ultimul pe GitHub: `d57444f`. Cod curat (fără debug). 78 teste trec.**
