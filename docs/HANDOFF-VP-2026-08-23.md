# HANDOFF — VP Terminal (2026-08-23) → chat nou

> Lipește acest fișier în chat-ul nou. Continuăm de aici. Scris de Claude la finalul unei
> sesiuni lungi de dezvoltare + audit + fix-uri + packaging.

---

## 0. Proiectul (context de bază)
Terminal desktop **Volume Profile + Order Flow** pentru NQ (Python, **PySide6 + pyqtgraph**,
date **Databento**), în **`D:\Volume Profile`**. Uz personal (Ali = **scalper pe 1min**),
**backtesting/replay** (NU live încă). Repo PRIVAT: `github.com/Serin15/volume-profile-terminal`.
`gh` NU e instalat.

- **Rulare (dev):** `.venv\Scripts\python.exe run_desktop.py`
- **Teste:** `.venv\Scripts\python.exe -m pytest -q` → **336 passed** (~20 min; date reale în `data/parquet`)
- **Regula de aur:** tool de **CONTEXT**, ZERO BUY/SELL/semnale automate. „Order flow-ul arată
  ce se întâmplă; TU decizi." Fără scoring/ML/BUY-SELL engine.

## 1. Starea Git (IMPORTANT)
- **`main`** = neatins (înghețat). **Nimic pe main, nimic pushed.**
- **`feat/panels-arch`** = branch-ul ACTIV, conține TOATĂ munca sesiunii. Local.
- Working tree: curat, cu excepția artefactelor PyInstaller (`build/`, `dist/`,
  `VolumeProfileTerminal.spec`) — untracked, **NU se comit** (de adăugat în `.gitignore`).

### Commit-urile sesiunii (vechi → nou)
```
b45d1be feat(arch): SessionStore cache (Faza 0)
235d80e feat(panels): HistoricalProfilePanel dock (Faza 1)
694e22b feat(panels): Faza 1 completari (HVN/LVN + total/Δ/high-low + teste)
3e41b18 feat(panels): Faza 2 — sync cauzal cu replay (opt-in, no look-ahead)
b399c87 feat(panels): Faza 3 — Professional VP (TOTAL/SPLIT/DELTA + hover)
4cb4075 fix(loader): DST-aware session boundary + teste
c3264f2 ux(vp): HVN/LVN ca tick-uri pe margine (in dock)
6f7d461 fix(ui): panouri vizibile pe 1920 + etichete prior + dock lisibil
e7781cd data: adauga zilele August 07-21 2026 (13 sesiuni)
7b1c449 fix(ui): Acc/Rej hover + raza 22px   ← suita NU re-rulata (schimbare triviala)
```

---

## 2. Ce s-a FĂCUT în sesiunea asta

### A. Arhitectură de panouri (Fazele 0-3) — COMPLET
Obiectiv: Main Chart curat (fără VP-uri istorice peste el) + panouri secundare.
- **Faza 0 — `app/desktop/session_store.py`**: `SessionStore` = cache LRU peste `data_service`
  (ticks/day/period), chei deterministe, **stateless față de replay** (fără look-ahead prin el).
- **Faza 1 — `app/desktop/historical_panel.py`**: `HistoricalProfilePanel` (QDockWidget) +
  `ProfileCard`. „Profile Only" (buton în topbar) **NU mai desenează peste Main Chart** — deschide
  dock-ul. Selectezi Date + Session (Full Day/Asia/London/New York) + „+ Add Profile" pt mai multe.
- **Faza 2 — sync cauzal opt-in**: checkbox „🔗 Sync to replay cursor". Ziua de replay se taie
  CAUZAL la cursor (`profile_from_footprint` pe footprint-ul snapshot ≤ cursor); zilele istorice
  rămân complete. **Zero look-ahead** (verificat pe 04.08 NY 16:37/16:56).
- **Faza 3 — `app/desktop/vp_view.py`**: `VolumeProfileView` PROFESIONAL. 3 moduri: **TOTAL**
  (default), **SPLIT** (buy verde/sell mov), **DELTA** (divergent din centru). + **hover pe nivel**
  (Price/Total/Buy/Sell/Delta + tag POC/VA/HVN/LVN) + POC/VAH/VAL + bandă VA.
- Toate reutilizează engine-urile existente (`vp_engine`/`delta_engine`/`data_service`), **fără
  motor nou**. Teste: `test_session_store`, `test_historical_panel`, `test_replay_sync`, `test_vp_pro`.

### B. Fix DST (Pasul 1 din audit) — COMPLET
`data/loader.py`: granița de sesiune era hardcodată `hour>=22 UTC` (corect DOAR vara). Fix:
convertim în **America/New_York** și comparăm ora locală (**18:00 ET**, DST-aware): vara 22:00 UTC,
iarna 23:00 UTC. Constante noi: `SESSION_TZ`, `SESSION_BOUNDARY_HOUR`. Robust și la `ts` tz-naive
(parquet). Vara = IDENTIC (0 regresii). Teste: `test_dst.py` (11).

### C. HVN/LVN mai discrete (în DOCK) — COMPLET
`vp_view.py`: HVN/LVN în dock desenate ca **tick-uri scurte pe marginea axei** (nu linii full-width).
**DECIS: pe Main Chart le lăsăm full-width** (sunt S/R pe grafic timp×preț — ok așa).

### D. Fix-uri UI (raportate pe screenshot 1920) — COMPLET
`main.py` + `historical_panel.py`:
1. **Panourile ieșeau off-screen pe 1920**: `LayerBar` forța lățimea minimă a ferestrei > ecran.
   Fix: LayerBar în `QScrollArea` + `glw.setMinimumWidth(400)` + combo-uri constrânse (cbo_day,
   cbo_compare). Window minimumSizeHint: **2864 → 1053**. Context + dock încap acum pe 1920.
2. **Etichete prior „0.00"**: `InfLineLabel.valueChanged` face early-return cât linia e ascunsă
   la setPos → text stale. Fix: helper `_refresh_line_label()` după ce liniile-s vizibile
   (prior + compare).
3. **Dock prea îngust** (Date/Session/× + DELTA se tăiau): card compact (lbl_levels wordwrap 473→351)
   + dock `setMinimumWidth(390)`.
Teste: `test_ui_fixes.py` (3).

### E. Date noi August — COMPLET
Adăugate **Aug 07-21 2026** (13 sesiuni) din batch-ul Databento de pe Desktop → convertite în
`data/parquet` (comise, versionate). Acoperire: până la **21 Aug**. `data/parquet` = ~219 MB, 75 zile.
(Sursa CSV = pe Desktop-ul lui Ali + zip `GLBX-20260822-...`.)

### F. Audit complet — `Desktop\VP-AUDIT\AUDIT-2026-08-20.md`
Concluzie: **tool bine inginerit, fundație anti-look-ahead reală, „context nu semnal" respectat.**
NU e produs de vândut (fără live, licență date, suport). Verdicte per componentă. Un singur
REWORK/REMOVE: **Composite 90D** (nesigur peste rollover). Restul KEEP / KEEP+SIMPLIFY.
Vezi și `Desktop\VP-AUDIT\ARHITECTURA-PANOURI.md` (planul de panouri).

### G. Packaging pentru un prieten (feedback OF) — COMPLET
Build PyInstaller → **`Desktop\VolumeProfileTerminal.zip` (324 MB)**, cu TOATE datele bundle-uite.
Prietenul dezarhivează → dublu-click `.exe` → zero setup (fără Python/cont/Databento). E build
**--console** (fereastra de consolă apare intenționat, pt erori). Comanda de rebuild:
```
.venv\Scripts\python.exe -m PyInstaller --noconfirm --console --name VolumeProfileTerminal \
  --collect-all pyqtgraph --collect-all tzdata --add-data "data/parquet;data/parquet" run_desktop.py
```
(Instalate în venv: `pyinstaller`, `tzdata`.) Testat: pornește + încarcă datele (260 MB memorie).
De făcut opțional: versiune **--windowed** (fără consolă). ⚠️ exe nesemnat → SmartScreen „Run anyway".

---

## 3. ÎN LUCRU / DESCHIS (unde ne-am oprit)

### 🔴 Bug hover — „nu apare nimic pe niciun marker" (Ali, pe mașina lui)
- **Status:** NEreprodus. În testele mele (offscreen, dev) **hover-ul MERGE** — big trade / absorption
  / exhaustion / (acum) Acc/Rej arată cardul cu date corecte.
- **Reparat deja** (commit 7b1c449): `_marker_hover_at` verifica abs/exh/big dar **NU react** →
  Acc/Rej n-avea tooltip. Adăugat react + rază 16→22px.
- **De aflat de la Ali (test pe `run_desktop.py`, NU exe-ul vechi):**
  1. Când mută mouse-ul, **crosshair-ul** (crucea + preț/oră) se mișcă?
     - DA → sigMouseMoved merge → hover ar trebui să meargă cu fix-ul.
     - NU → evenimentele nu ajung la grafic → de săpat acolo.
  2. Apare acum tooltip-ul la hover pe markere?
- **Mecanica hover:** `_on_mouse` (sigMouseMoved) → `_marker_hover_at` (proximitate în px,
  manual, pt că `sigHovered` nativ nu se declanșează în PySide6/pyqtgraph 0.14) → `_on_marker_hover`
  (citește `points[0].data()` = tuplu ("big"/"abs"/"exh"/"react", ...)).

### 🔴 Calibrare Absorption/Exhaustion pe 1min — CONTRAINTUITIVĂ (bug de tuning, nu de cod)
Măsurat pe **17.08 1min** (NQU6, NY open = 16:30 RO = 13:30 UTC):
- **Big Trades:** 90 total, 59 pe NY ✅
- **Acc/Rej:** 25 total, 7 pe NY (16:38, 17:08…) ✅
- **Absorption:** 10 total, dar în open-ul NY (16:30-18:54) = **ZERO** (toate după-amiaza) ⚠️
- **Exhaustion:** 21 total, dar **20 overnight, 1 pe NY** 🔴 **PE DOS**
- **Cauza exhaustion:** caută climax vs **mediana recentă** (`vol_mult=3.5×`). Noaptea (liniște) o
  bară e 3.5× mediana mică → se aprinde. Pe NY (volum mare susținut) mediana e mare → 3.5× e rar.
  → se aprinde pe spike-după-calm, nu pe volumul mare absolut.
- **Praguri:** `_detector_defaults(60)` = abs `{min_vol:85, frac:0.3}`, exh `{window:30, vol_mult:3.5,
  delta_frac:0.25}`; `_detector_defaults(300)` (5min) = abs `{70, 0.22}`, exh `{14, 2.0, 0.2}`.
- **De făcut (proper, NU curve-fit pe 1 zi):** investigație pe 4-5 zile; propunere de re-calibrare
  exhaustion (ex. cere ȘI **volum absolut minim**, nu doar relativ la mediană). Ali poate testa live
  din ⚙ (coboară „Climax volum x mediana" 3.5→2.5 și vede dacă apar mai multe utile sau doar zgomot).

---

## 4. TODO / priorități (în ordine)
1. 🎯 **VALIDARE PE DATE REALE** (`Desktop\VP-AUDIT\REPLAY-STUDY-PROTOCOL.md`, 10 sesiuni,
   `replay-study-log.csv`). **Cel mai important lucru.** Ali are date proaspete August. Fără asta,
   nu se știe care componente chiar ajută vs sunt wallpaper.
2. **Re-calibrare Exhaustion** (și Absorption) — vezi §3. Investigație multi-zi + before/after counts.
3. **Finalizează bug-ul hover** — după diagnosticul crosshair de la Ali.
4. **Rulează suita completă** pentru commit-ul 7b1c449 (nu s-a re-rulat; schimbare trivială dar de bifat).
5. **Composite 90D** — decide rework sau remove (din audit).
6. Opțional: exe **--windowed**; `.gitignore` pt build/dist/*.spec.
7. **NU** porni: refactor monolit main.py (Faza 4), indicatori noi, live streaming — decât la cerere explicită.

## 5. Fișiere/locații cheie
- **Cod:** `core/{vp_engine,delta_engine,context_engine}.py`, `data/loader.py`,
  `app/desktop/{main,data_service,replay,charts,vp_view,historical_panel,session_store,drawings,theme}.py`
- **Docs (Desktop\VP-AUDIT\):** `AUDIT-2026-08-20.md`, `ARHITECTURA-PANOURI.md`,
  `BACKTESTING-PLAYBOOK.md`, `REPLAY-STUDY-PROTOCOL.md`, `DOCUMENTATIE-COMPLETA.md`, `manual.html`
- **Exe pt prieten:** `Desktop\VolumeProfileTerminal.zip`

## 6. Preferințe Ali (pt Claude-ul nou)
Pas-cu-pas, în **română**, validare pe fiecare pas, se pierde în multe feature-uri.
**Prioritatea:** CORRECTNESS → SIMPLICITY → REAL-DATA VALIDATION. Preferă o **concluzie corectă**
în locul uneia care sună bine. Vrea nivel DeepCharts/ATAS/Sierra. **Nu adăuga features/indicatori
noi, fără scoring/ML/BUY-SELL.** Fiecare fază = commit separat + suită verde + STOP pt aprobare.
Nimic pe `main` până nu e mulțumit.

### Context business (discutat)
Cum face bani cu tool-ul: **NU vinde .exe-ul** (fără live, licență Databento nu permite redistribuire,
suport). Valoarea = pârghie: (a) îl face pe EL mai bun la trading/prop, (b) suport vizual pt **predat
metoda** (educație). Blocajul real = **validarea metodei** (pasul 1 de mai sus), nu mai mult cod.
