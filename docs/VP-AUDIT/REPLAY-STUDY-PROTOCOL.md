# REPLAY STUDY PROTOCOL — Order Flow Context Engine

**Scop:** să afli, cinstit, dacă panoul de Context **te ajută să citești order flow-ul mai bine** — sau e doar zgomot / confirmation bias. Și *care* componente/stări îți sunt de fapt utile ca om. Nu e validare statistică (aia vine doar dacă studiul ăsta îți arată ceva care merită cuantificat). E validarea potrivită pentru un tool **discreționar de context**.

**Durată realistă:** ~20–30 min per sesiune × 10 sesiuni. Poți face 2–3 pe zi. Nu le înghesui — oboseala strică observația.

---

## REGULA DE AUR (fără ea, studiul nu valorează nimic)

> **COMMIT ÎNAINTE DE REVEAL.**
> La fiecare moment notabil: **pui pe pauză**, citești panoul, **scrii ce te aștepți să urmeze ȘI dacă panoul ți-a schimbat citirea** — și ABIA APOI avansezi ca să vezi ce s-a întâmplat.

Dacă te uiți întâi la ce a făcut prețul și pe urmă „interpretezi" ce zicea panoul, o să raționalizezi orice și o să crezi că tool-ul e genial. Replay-ul e cauzal exact ca să te forțeze să te angajezi înainte să vezi viitorul. **Folosește-l pentru commit.**

---

## SETUP (o dată)

**Lansează:**
```
cd "D:\Volume Profile"
.venv\Scripts\python.exe run_desktop.py
```

**Configurare pentru studiu:**
- **Rezoluție:** `5min` ca principal (structură). `1min` doar ca zoom la deschidere dacă vrei detaliu. (La 5min, orizonturile de mai jos au sens; la 1min sunt prea scurte.)
- **View:** pornește pe **„Order Flow"** sau **„NY Open"**, apoi **bifează panoul Context** (toggle-ul din bara de straturi, dreapta graficului). Markerele rămân OFF — nu vrem chartul aglomerat; vrem panoul.
- `row_size` = 2.0, VA = 70% (default). Nu umbla la praguri în timpul studiului.
- **Technical Details:** ține-l OFF la început (propozițiile umane sunt destule). Deschide-l doar când vrei să vezi cifra brută din spatele unei stări.

**Două mecanici pe care te bazezi:**
1. **Replay** (play/pauză/viteză/seek): lumânarea curentă se formează live, panoul se actualizează pe bara în formare, **cauzal** (nu vede viitorul). Ăsta e modul principal de studiu.
2. **Context-at-Cursor** (hover): treci cu mouse-ul peste orice bară închisă → panoul îți arată contextul **de la acel T** (tot cauzal). Bun pentru explorare după ce ai terminat commit-ul.

---

## CE E UN „MOMENT NOTABIL" (ca să nu notezi fiecare bară)

Pune pauză și logează DOAR când apare unul din astea:
- **Prețul ajunge la un nivel** cheie: POC / VAH / VAL, nivel de sesiune precedentă, composite 15D, sau un LVN/HVN.
- **Panoul arată o stare CONFIRMED**: absorption / exhaustion / CVD divergence *confirmed* (nu forming), sau un FLOW tare: „aggression without progress", „delta flip", Tape HIGH.
- **Overall se schimbă** în SUPPORTIVE sau CONTRADICTING.
- **Setup-ul TĂU de price action** se declanșează — ca să compari: panoul e de acord, te contrazice, sau te avertizează?

Țintă: **~5–10 momente per sesiune**. Dacă notezi 30, filtrezi prea puțin.

---

## BUCLA LA FIECARE MOMENT (30 secunde)

1. **Pauză.** Notează: ora (RO), prețul, **ce l-a făcut notabil** (nivel / stare / overall / setup-ul tău).
2. **Citește panoul** — Overall + liniile din FLOW / STRUCTURE / LEVELS / LOCATION care nu-s goale.
3. **COMMIT (înainte de reveal):**
   - Ce aștepți? **U** (sus) / **D** (jos) / **R** (rotație/range) / **?** (habar n-am) + **încredere 1–3**.
   - **Efectul panoului asupra citirii tale:** `Sharper` (m-a făcut mai clar/mai convins corect) · `No-change` (știam deja / n-a adăugat nimic) · `Misled` (m-a împins în direcția greșită) · `Talked-me-out` (m-a oprit dintr-un trade — bun sau rău, vezi la reveal).
4. **Avansează** ~**4 bare** (scurt ≈ 20 min) și uită-te; apoi până la ~**12 bare** (mediu ≈ 1h). Notează: net ticks, și cât s-a dus în favoarea ta / împotriva ta (MFE / MAE) — aproximativ, la ochi.
5. **Verdict pentru momentul ăsta:** `Helped` / `Neutral` / `Misled` + **care componentă** a condus citirea (delta / progress / absorption / exhaustion / cvd / lvn / tape / location / overall).

Completează în `replay-study-log.csv` (o linie per moment). Minim obligatoriu: **ora, trigger, call+conf, efect panou, outcome, verdict**. Restul, opțional.

---

## SESIUNI RECOMANDATE (set echilibrat, din datele tale — NQU6, recente)

Le-am ales să acopere regimuri diferite (calculat pe cele 62 de zile). Fă-le în ordinea asta (trend întâi, e mai ușor de citit; range la final, e testul greu):

| # | Sesiune | Regim | De ce (proxy pe zi) |
|---|---------|-------|---------------------|
| 1 | `2026-07-30` | **TREND ↑** | range 1108, net +901, eff .81, volum mare — trend curat |
| 2 | `2026-08-04` | **TREND ↑** | range 1125, net +864, eff .77 — trend recent, amplu |
| 3 | `2026-07-16` | **TREND ↓** | range 737, net −594, eff .81 — downtrend curat |
| 4 | `2026-07-27` | **TREND ↓** | range 824, net −565, eff .69 |
| 5 | `2026-07-26` | **CLEAN mic** | range 231, eff .98 — direcțional curat, zi liniștită (contrast) |
| 6 | `2026-07-29` | **NEWS / vol mare** | volz +1.3, range 977 — cea mai activă, trend jos |
| 7 | `2026-07-23` | **MIXED vol mare** | range 850, volz +0.7 |
| 8 | `2026-07-31` | **RANGE / rotație** | eff .21 — chop |
| 9 | `2026-08-06` | **RANGE / rotație** | eff .21 — cea mai recentă zi din set |
| 10 | `2026-07-28` | **RANGE pur** | net −62 pe range 592, eff .11 — testul cel mai greu |

*(Vrei variație pre-rollover? Poți adăuga o zi NQM6 din mai–început iunie, dar composite-ul e mai subțire acolo — vezi avertismentul de mai jos.)*

---

## 3 AVERTISMENTE (din audit — ca să nu tragi concluzii greșite despre tool)

1. **„SUPPORTIVE" e VERDE și când contextul e coerent-BEARISH.** Verde ≠ long. **Citește `reasons` (ex. „2 bearish"), nu culoarea.** Când notezi Overall, notează și dacă **culoarea te-a indus în eroare** — e chiar unul din finding-urile de verificat pe viu.
2. **Composite 90D e nesigur peste rollover.** Pentru zilele NQU6 din set, **15D e ok**; nu supra-interpreta linia composite.
3. **Absorption/exhaustion — recalibrate (Aug 2026).** Pe **1min**, exhaustion are acum prag ABSOLUT de volum (min_vol=400) + mult 2.0 → ~5/zi, nu ~30 (vezi `MARKER-STUDY-PROTOCOL.md` + `scripts/verify_detectors.py`). Tratează ca „notabil" doar **CONFIRMED + la un nivel**. Dacă o stare apare tot timpul, e wallpaper, nu semnal — notează asta.

---

## LA FINALUL FIECĂREI SESIUNI (2 min)

- Numără verdictele: câte `Helped` / `Neutral` / `Misled`.
- O propoziție: *ce m-a ajutat cel mai mult azi și ce m-a încurcat?*

---

## LA FINALUL CELOR ~10 SESIUNI — CONCLUZIA (aici e tot câștigul)

Agregă din log, **per componentă/stare**, câte Helped / Neutral / Misled. Apoi aplică regulile:

| Tipar | Ce înseamnă | Decizie |
|-------|-------------|---------|
| Majoritar **Helped**, rar Misled | chiar îți ascute citirea | **KEEP + trust** ca context; candidat pt harness statistic *dacă* vrei să acționezi pe el |
| Majoritar **Neutral** | nu adaugă la ce vezi oricum | **HIDE / deprioritizează** în UI (mai puțin zgomot) |
| Des **Misled** | te împinge greșit | **INVESTIGATE / scoate din Overall** |

Plus întrebările meta (răspunde-le explicit):
- **Overall (verde/roșu) te-a indus vreodată în eroare?** (finding-ul de culoare — confirmă-l sau infirmă-l pe viu)
- **Ce componentă s-a aprins atât de des încât a devenit wallpaper?** (tape HIGH, absorption)
- **În ce regim a fost tool-ul cel mai util — trend sau range?** (bănuiala: mai util în trend/la extreme; mai slab în chop)
- **POC migration ți-a spus ceva util vreodată, sau era mereu „anchored" târziu în sesiune?** (testează direct concernul de inerție)

**Output final:** o listă scurtă `keep / hide / investigate` per componentă. Aia îți spune:
1. cum să cureți UI-ul (ascunzi ce e Neutral),
2. **dacă** merită harness-ul statistic și **pentru ce anume** (doar componentele „Helped"),
3. dacă vreun finding din audit (culoare, redundanță) chiar te încurcă în practică.

Asta e decizia reală — luată din date proprii, nu din presupuneri.

---

*Însoțit de `replay-study-log.csv` (log de completat, o linie per moment) și versiunea PDF pentru print.*
