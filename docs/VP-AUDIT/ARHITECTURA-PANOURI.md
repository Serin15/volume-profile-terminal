# ARHITECTURĂ PANOURI — audit + plan (2026-08-20)

> Cerere: Main Chart curat (fără VP-uri istorice peste el), panouri secundare
> independente (Historical Profile Panel etc.), pregătite pentru sincronizare cu
> replay-ul, VP mult mai profesional. Fără BUY/SELL automat. Principiu: „order flow-ul
> arată ce se întâmplă; TU decizi." Acest doc e AUDIT + PLAN. Nicio linie de cod
> încă schimbată.

---

## PARTEA I — AUDIT (starea reală, cu referințe la cod)

### 1. Cum e construit acum UI-ul
- **Un singur monolit:** `app/desktop/main.py` = clasa `MainWindow(QMainWindow)`, **2537 linii**.
  Central widget unic, VBox: `_build_topbar` → `_build_stats` → `_build_charts` →
  `_build_layerbar` → `_build_replaybar` (main.py:254-258). **Zero QDockWidget.**
- **Un singur grafic de preț:** `_build_charts` (main.py:803) creează UN
  `GraphicsLayoutWidget` cu 3 plot-uri stivuite și X-linked: preț (row 0), CVD (row 1),
  grid stats (row 2). **Absolut tot** se adaugă în `self.price` (PlotItem-ul de preț):
  lumânări, profil overlay, footprint, period-profiles, markere, linii POC/VA, noduri,
  dev-curves, benzi de sesiune. → de-aia se „murdărește" graficul.
- **Panoul Context** = un `QTextEdit` (`self.ctx_panel`) încastrat în central widget la
  dreapta (main.py:1065-1091). NU e fereastră/dock separat — e cusut în layout.
- **State-ul** trăiește ca atribute pe `MainWindow` (`self._data`, `self._replay`,
  `self._mode`, `self._span`, `self._vp_scope`, `self._sessions`, caches...). Toate
  handler-ele sunt metode ale aceleiași clase → cuplare strânsă.

### 2. Cum e construit actualul Volume Profile
Aici e vestea bună — **e deja stratificat curat**:
- **Calcul (pur, fără UI):** `core/vp_engine.py` (`VolumeProfileEngine`: POC, Value Area
  à la Sierra, HVN/LVN prin peak-detection real, noduri structurate cu margini/tier) +
  `core/delta_engine.py` (`DeltaEngine`: buy/sell per nivel, delta per nivel, CVD).
  **Datele pentru un VP profesional (buy/sell split, delta/nivel) EXISTĂ deja.**
- **Orchestrare calcul:** `app/desktop/data_service.py` — funcții care întorc dict-uri/
  `DayData`: `load_day`, `profile_from_footprint`, `session_profiles`, **`period_profiles`**
  (data_service.py:600 — produce deja „un VP per zi" SAU „NY/Asia/Londra per zi" pe un span;
  exact `08→NY, 07→NY, 06→NY`), `prior_session_levels`, detectorii.
- **Randare (reutilizabilă):** `app/desktop/charts.py` — `GraphicsObject`-uri pyqtgraph,
  fiecare se atașează la un viewbox și face culling la viewport:
  - `ProfileOverlayItem` — VP suprapus pe chart (single / split buy-sell, VA highlight, POC).
  - `PeriodProfilesItem` — „Profile Only": mai multe VP-uri așezate pe **axa timpului** real.
  - `FootprintItem`, `GridStatsItem`, `ProfileItem`, `CandlestickItem`.
- **Ce face Profile Only azi:** `_render_profile_only` (main.py:1587) cheamă
  `period_profiles(...)` (cache `_po_cache`), bagă în `period_profiles_item` care e
  **în același `self.price`** → desenat peste Main Chart pe timeline-ul real.
- **Compare:** există deja un al DOILEA profil (`self.cmp_profile`, ancorat pe dreapta,
  culoare distinctă — main.py:911). Dovadă că „mai multe profile simultan" e fezabil.

**Limitările VP-ului actual (pentru „mai profesional"):** e un OVERLAY subțire, translucid,
ancorat la marginea graficului; **fără etichete** pe bare, **fără tooltip** la hover pe nivel,
**fără delta/nivel afișat**, **fără axă/zoom propriu**, fără „highlight zonă". Bun ca fundal,
insuficient ca instrument de analiză dedicat.

### 3. Ce putem REUTILIZA (fără să rescriem)
- **Toate engine-urile** `core/*` — neatinse.
- **Toate funcțiile** din `data_service.py`, în special `period_profiles` (face deja
  fix selecția zi/sesiune × mai multe zile) și `profile_from_footprint`.
- **Toți renderer-ii** din `charts.py` — sunt agnostici de fereastră (se leagă la un viewbox
  dat). `PeriodProfilesItem` se poate muta 1:1 într-un alt `GraphicsLayoutWidget`.
- **`Replay._snapshot()`** (replay.py:169) — întoarce un `DayData` care e **starea cauzală**
  la timpul T (doar lumânări închise + cea în formare). E sursa perfectă de sincronizare.

### 4. Ce trebuie REFACTORIZAT
- **Extras din monolit** ansamblul graficului: `_build_charts` + `_render` + wiring-ul
  viewbox → o clasă reutilizabilă `ChartPanel(QWidget)` care își deține propriul
  `GraphicsLayoutWidget`, item-ele și viewbox-ul. Main Chart = o instanță.
- **State-ul de replay** scos din `MainWindow` într-un mic controller observabil
  (vezi §II) ca să poată alimenta mai multe panouri, nu doar chart-ul principal.
- **Citirea datelor** centralizată (azi `data_service` **nu are cache** — fiecare
  `load_day`/`period_profiles` **recitește parquet-ul**; pt 3 zile = 3 citiri).

### 5. Ce trebuie CONSTRUIT de la zero
- **`SessionStore`** (data hub) — cache partajat de ticks/DayData, o singură sursă.
- **`ReplayController` / „replay clock"** — deține `Replay`, emite semnal Qt la fiecare
  cadru/seek cu snapshot-ul curent + epoca curentă. Panourile se abonează.
- **`HistoricalProfilePanel`** (QDockWidget) — VP-uri istorice **side-by-side** (spațiu
  propriu, NU pe timeline-ul real), selector dată + sesiune + mai multe zile.
- **`ProVolumeProfileItem`** — renderer VP profesional (vezi §II punct 10).
- **`PanelManager`** — registru de panouri (deschide/închide/dock), meniu.

---

## PARTEA II — DECIZII DE ARHITECTURĂ (răspuns la întrebările 6-11)

### 6. Sistemul de ferestre/panouri (cum îl proiectez)
Model: **QMainWindow + QDockWidget-uri**. Main Chart rămâne central widget; fiecare panou
secundar (Historical Profile, Order Flow, Context, Tape) e un **dock** care se poate
detașa/muta/închide independent. Avantaj: nativ Qt, salvăm/restaurăm layout-ul
(`saveState`/`restoreState`), fără management manual de ferestre.

Contract comun pentru orice panou (interfață minimă):
```
class AnalysisPanel(QDockWidget):
    def set_context(self, ctx): ...     # ziua/simbolul/row_size curent
    def on_replay(self, snapshot, epoch): ...   # opțional: sincronizare (poate ignora)
    def refresh(self): ...
```
`MainWindow` ține `self._panels = {}` și un meniu „Panels" (deschide/închide). Fiecare panou
citește din `SessionStore` și (opțional) se abonează la `ReplayController`.

**Principiul de UI (punctul 5 din cerere):** Main Chart = market/replay curat. Orice analiză
(VP-uri istorice, tape, context) = într-un panou dedicat, deschis/închis la nevoie. Nimic nu
se mai adaugă „peste" graficul principal fără scop clar.

### 7. Sincronizarea cu replay-ul
- `ReplayController` deține `Replay` și, la fiecare `step`/`seek`, emite
  `replayAdvanced(snapshot: DayData, epoch: int)`.
- Main Chart se abonează (înlocuiește `_nav_render` actual).
- `HistoricalProfilePanel` se abonează **opțional**:
  - Zilele **anterioare** (07, 06 Aug față de replay pe 08) = complet cunoscute → statice,
    nu depind de cursor.
  - Ziua **curentă** afișată în panou (ex. „08 NY" în timp ce derulezi 08) = **se
    reconstruiește la fiecare bară închisă, tăiată la epoca cursorului** (vezi §8).
- Panourile care nu vor sincronizare pur și simplu nu implementează `on_replay` → rămân
  independente. Arhitectura e „pregătită pentru sync", cerută la punctul 3, dar sync-ul e
  opt-in per panou.

### 8. Cum evităm look-ahead bias
Regula de aur a proiectului. Mecanica sigură:
- **Nu recalcula din DataFrame-ul complet.** Sursa de adevăr pt ziua curentă = tot
  `Replay._snapshot()` (deja `exclude_last=True` pt detectori, `k < cursor` pt big trades,
  checkpoints pt seek înapoi — replay.py:213-234).
- Pt un profil de sesiune din ziua curentă în panou: filtrează footprint-ul din snapshot la
  `epoch <= cursor_epoch` și rulează `profile_from_footprint` pe acele epoci. Niciodată pe
  ticks viitoare.
- Zilele istorice (anterioare zilei de replay) sunt integral cunoscute → fără risc.
- **Guard de test dedicat** (extinde `tests/test_lookahead.py`): profilul curent din panou
  la cursorul C == profilul calculat din snapshot la C, și NU se schimbă dacă avansăm apoi
  derulăm înapoi la C (determinism — deja acoperit de `test_replay_determinism`/`_seek`).

### 9. Cum păstrăm performanța
- **`SessionStore` cu memoizare** pt `get_ticks(file, mode)` și `get_day(...)` → 3 zile
  în panou = citim parquet o dată/zi, nu de N ori (azi zero cache în data_service).
- **Culling la viewport** e deja standard în `charts.py` — îl păstrăm în panouri.
- **Recompute throttled**: profilul curent din panou se recalculează doar **la închiderea
  barei**, nu la fiecare tick (ca `_ctx_last_bar` azi).
- Fiecare panou își deține viewbox-ul; **deconectăm semnalele la închidere** (altfel leak).

### 10. Noul Volume Profile — mai profesional (ce fac Sierra/ATAS/DeepChart bine)
Nu copiem orbește; luăm principiile care contează pt un tool de CONTEXT:
- **Panou dedicat cu axă de preț proprie** (nu overlay subțire): histogramă orizontală
  volume-at-price, cu zoom/scală independentă pe Y.
- **Niveluri clare + etichete:** POC (bara cea mai lată + linie + etichetă), bandă Value Area
  umbrită, VAH/VAL cu etichetă, HVN/LVN marcate. Total volume + VA% afișate.
- **Moduri comutabile (o dată, nu 20 de indicatori):**
  `Total` · `Buy/Sell split` (verde dreapta / mov stânga) · `Delta/nivel` (bare divergente
  din centru). Datele există deja din `DeltaEngine`.
- **Tooltip la hover pe nivel:** total, buy, sell, delta, % din sesiune la acel preț.
- **Highlight zonă:** click pe un nod → evidențiere (S/R de studiat).
- **Lizibilitate/densitate:** numerele apar doar la zoom (pattern deja folosit în
  `FootprintItem`/`GridStatsItem`); format compact K; spacing pe `row_size`.
- **Comparație:** mai multe profile side-by-side în același panou (08 NY / 07 NY / 06 NY),
  aliniate pe aceeași axă de preț → citești migrarea valorii peste zile.

### 11. Riscuri pentru funcționalitățile existente
| Risc | Impact | Mitigare |
|---|---|---|
| Refactor monolit `main.py` rupe wiring (markere, crosshair, LOD, VP scope) | mare | **Aditiv**: nu extragem `ChartPanel` până nu e acoperit de teste; fazele 1-3 nu ating chart-ul principal |
| Look-ahead la sync-ul zilei curente | critic (fundația tool-ului) | Reutilizăm `snapshot`, test dedicat, nu recalculăm din df complet |
| Panouri multiple recitesc parquet | performanță | `SessionStore` cache |
| Leak de semnale viewbox la panouri deschise/închise | degradare în timp | fiecare panou deconectează la `closeEvent` |
| Determinism replay | regresie subtilă | `test_replay_determinism`, `test_replay_seek`, `test_lookahead` = gardienii, verzi la FIECARE fază |
| Task DST (granița 22:00 UTC hardcodată, loader.py:29-30) | date de iarnă | NU legăm de refactor; rămâne task separat, dar sync-ul de sesiuni îl va atinge → de rezolvat înainte de iarnă |

---

## PARTEA III — PLAN DE IMPLEMENTARE (pași mici, fiecare cu teste)

Regulă: după FIECARE fază → suita de 267 teste verde + verificare vizuală. Nimic pe `main`
până Ali validează. Fiecare fază e un commit separat, reversibil.

### Faza 0 — Plasă de siguranță + „seams" (fără schimbare de comportament)
- `SessionStore` cache pt `get_ticks/get_day`; `data_service` citește prin el.
- Test golden: pe o zi cunoscută (2026-07-30), POC/VAH/VAL/total identice înainte/după.
- **Livrare:** zero schimbare vizuală, doar mai puține citiri parquet.

### Faza 1 — Historical Profile Panel (MVP — miezul cererii)
- `HistoricalProfilePanel(QDockWidget)` cu propriul `GraphicsLayoutWidget` +
  `PeriodProfilesItem` în **layout side-by-side** (sloturi sintetice, nu timeline real).
- Selector: **dată(e)** + **sesiune** (Full Day / Asia / London / NY / Custom) + **mai
  multe zile** (ex. 3 rânduri: 08→NY, 07→NY, 06→NY). Alimentat de `period_profiles`.
- Butonul **`Profile Only`** deschide PANOUL, **nu** mai desenează pe Main Chart
  (`period_profiles_item` scos/ascuns din `self.price`).
- **Teste:** N zile selectate → N profile în panou; Main Chart NU mai conține period-item;
  panoul se deschide/închide fără eroare.

### Faza 2 — Schele de sincronizare replay
- `ReplayController` care deține `Replay` și emite `replayAdvanced(snapshot, epoch)`;
  Main Chart devine un simplu abonat (mută `_nav_render`).
- Panoul se abonează opțional: zilele istorice statice; ziua curentă tăiată la cursor.
- **Teste:** `test_replay_determinism/_seek/_lookahead` rămân verzi; profil curent din panou
  la cursor C == snapshot la C; seek înapoi la C → identic.

### Faza 3 — `ProVolumeProfileItem` (VP profesional)
- Renderer nou în panou: etichete POC/VAH/VAL, bandă VA, HVN/LVN, moduri Total/Split/Delta,
  tooltip la hover pe nivel, total volume + VA%, zoom Y propriu, highlight nod.
- **Teste:** profil cunoscut → linii POC/VA corecte; hover pe nivel → (total, buy, sell,
  delta) corecte; smoke vizual.

### Faza 4 — Multi-panou + extragere `ChartPanel` (viitor)
- 2-3 Historical Panels simultan; `PanelManager` + meniu; `saveState/restoreState`.
- Extragere `ChartPanel` din `MainWindow` DOAR acum (acoperit de teste), ca să putem avea
  în viitor și „Order Flow Panel", „Tape Panel" ca instanțe.
- **Teste:** 2 panouri independente cu zile diferite; layout persistă între rulări.

---

## Ordinea recomandată
Fazele **0 → 1 → 2 → 3** livrează exact cererea (Main Chart curat + panou istoric +
sync-ready + VP profesional). Faza 4 (multi-panou generic + refactor monolit) e ultima,
cere testare live și e cea mai riscantă — o facem doar după ce restul e validat.
