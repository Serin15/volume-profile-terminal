# UX / LOOK — listă prioritizată spre nivel DeepCharts / ATAS / Sierra

> Bazat pe capturi reale ale aplicației (randate offscreen) + paleta din `theme.py`.
> Adevărul dur: 80% din „look-ul pro" NU vine din features, ci din **RESTRICȚIE +
> IERARHIE + CONSISTENȚĂ**. Structura ta e deja corectă; problema e că se văd prea multe
> lucruri, la fel de tare, în prea multe culori. Astea sunt reparabile, majoritatea în theme.py.

---

## TOP 3 (dacă faci doar atât, sar cel mai mult în ochi)
1. **Ierarhie de culoare** — fă POC + ultim preț cele mai tari; TOT restul mai stins/subțire. (P0)
2. **Un singur loc pentru straturi** — bara de jos are ~15 bife; mută-le într-o listă de „studii" cu punct on/off + ⚙ (modelul DeepCharts). (P1)
3. **Diferențiază cele 3 panouri stivuite** (lumânări / CVD / grid) — acum toate verde/mov. (P1)

---

## P0 — DISCIPLINA DE CULOARE (cel mai mare salt, cel mai ieftin — mai tot în theme.py)

**Problema:** ~13 nuanțe pot apărea deodată, toate la intensitate similară → „fierăstrău de culori".
Pro-ul folosește PUȚINE culori + o ierarhie clară primar/secundar/terțiar.

- **Stabilește 3 niveluri de importanță vizuală:**
  - **PRIMAR (cel mai tare):** POC (`#ff2d7e`) + ultim preț. Mereu cele mai vizibile. Linie groasă (POC 3px ok).
  - **SECUNDAR (mediu):** margini Value Area + VWAP. **DAR fă-le culori DIFERITE** — acum `VWAP` și
    `VA_LINE` sunt AMÂNDOUĂ `#ff9d2e` portocaliu → nu le deosebești. Lasă VWAP portocaliu, fă VAH/VAL
    slate/gri-albastru discret (ai deja `VA_BAND` slate — pune și liniile la fel).
  - **TERȚIAR (stins, subțire, ≤1px, punctat):** HVN/LVN, nivelurile „ieri", sesiuni, composite.
    Idee pro: terțiarele „se aprind" doar la **hover**, altfel stau șterse.
- **Reduce nr. de familii de accent.** Prea multe concurează: magenta, portocaliu, teal, albastru,
  cyan, galben, coral, 3× auriu, indigo/verde/mauve. Ține maxim ~4-5 accente reale; restul = nuanțe
  ale unei familii neutre (slate/gri).
- **Pastilele de pe axa dreaptă** (etichetele de nivel): acum sunt cutii pline în ~5 culori, stivuite
  = zgomot. Unifică-le la UN stil compact: pastilă închisă + punct/bordură colorată subțire + valoarea.
  Nu cutii mari colorate.
- **Markere:** bine că pornesc OFF. Când sunt ON, bulele Big Trades pot fi doar **contur** (nu pline)
  ca să nu domine; galben/coral (abs/exh) sunt ok ca „categorie proprie" dar ține-le rare (ai deja LOD).

---

## P1 — IERARHIE PE GRAFIC

- **Default = „Curat".** Prima impresie trebuie să fie chart curat (lumânări + VP + POC/VA + VWAP),
  nu „Tot". „Tot" = mod power-user, nu vitrina. (Ai deja preset-urile „Vederi" — doar fă „Curat" implicit.)
- **Grosimi de linie:** doar POC gros; tot restul ≤1px, secundarele dotted. Consistență, nu 5 grosimi aleatorii.
- **Overlay-ul VP din stânga** (slate translucid): ok ca idee, dar ține-l discret (alpha mic) ca să nu
  „umple" jumătatea stângă — lumânările trebuie să domine.

---

## P1 — PANOURILE DE JOS (CVD + grid statistici)

**Problema:** CVD + grid folosesc ACEEAȘI paletă verde/mov ca lumânările → 3 zone verde/mov stivuite,
ochiul nu le separă. Grid-ul heatmap e foarte „greu".

- **CVD:** ia în calcul o **linie single-color** (teal/alb) cu umplere foarte discretă la zero, în loc de
  umplere verde/mov care copiază lumânările. Așa panoul se distinge clar de preț.
- **Grid statistici:** e dens și saturat. Fă-l opțional/colapsabil (ai toggle „Grid"), redu saturația,
  și/sau fă-l mai subțire. Nu trebuie să concureze cu CVD-ul de deasupra.
- **Separatoare + etichete clare** între cele 3 zone (preț / CVD / grid) ca să se parseze ușor.

---

## P1 — CONTROALE / CHROME (problema „15 bife")

- **Consolidează straturile într-un singur loc.** Bara de jos are ~15 checkbox-uri = încărcare cognitivă.
  Modelul pro (ATAS/Sierra/DeepCharts): o **listă de „studii/indicatori"** (rail vertical sau panou), fiecare
  cu punct on/off + iconiță ⚙ de settings. Ai început deja cu ⚙ per-tool — extinde ideea la o listă.
- **Rebalansează bara de sus:** grupare cu separatoare + etichete mici (ai deja), dar folosește spațiul
  gol din dreapta-sus (acum aproape gol) pentru stat cards / simbol, compact.
- **Ia în calcul un rail vertical de iconițe** (stânga) pentru moduri (ca Sierra/ATAS), în loc de
  dropdown-uri împrăștiate sus. Reduce zgomotul din bară.

---

## P2 — PANOUL CONTEXT (dreapta)

- E text dens. Fă-l **compact**: rânduri cu **chip de status** color-codat (punct verde/roșu/neutru +
  o linie), secțiuni colapsabile, în loc de paragrafe. Scanabil dintr-o privire.
- **Rezolvă ambiguitatea „SUPPORTIVE" verde** = poate fi bearish. Arată **direcția** (săgeată ↑/↓) sau
  scoate culoarea verde/roșu de pe cuvânt (verde=long e prea puternic în trading). Ex: „Coerent ↓ (2 bearish)".

---

## P2 — FINISAJ (detalii care „se simt" pro)

- **Tipografie consistentă:** o scală clară de mărimi (titlu / valoare / label), padding generos, aliniere.
- **Axa de preț (dreapta):** curată, doar pastilele cheie (last, POC); nu un teanc de pastile rainbow.
- **Colțuri/panouri:** rounded consistent (ai deja parțial în QSS), borduri subtile `#1e1e24`.
- **Umbrirea sesiunii:** deja discretă (alpha 13) — bine, păstreaz-o așa.

---

## Cinstit despre „nivel DeepCharts/ATAS/Sierra"
Ei au ani + designeri. Egalitate pixel-cu-pixel = proiect mare. DAR **senzația de „pro" e 80%
restricție + ierarhie + consistență** — și aia e la îndemână, aproape toată în theme.py + așezarea
controalelor. Cu P0 (culoare) + TOP 3 faci deja un salt mare de percepție.

**Ordinea de atac recomandată:** P0 (culoare) → P1 panouri → P1 controale → P2. Le pot face
incremental, câte una, fiecare verificată vizual de tine (offscreen confirmă layout-ul, dar ochiul tău
pe GPU real decide).
