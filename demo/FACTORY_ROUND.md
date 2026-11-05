# Paper-Runde „Krakens Schmiede" — Herleitung

Die Runde spielt das Motivationsbeispiel aus `Kraken_DEBS_Long_Version.pdf`
nach (Example 1–4, Fig. 1 und 3, Sec. 4.3) und erweitert es um eine Topologie,
die auch das „ein Knoten erreicht nicht jede Quelle"-Prinzip zeigt, das jede
Riff-Runde schon demonstriert. Sie zeigt an einem kleinen, vollständig
nachrechenbaren Fall: **Die unter All-Push günstigste Platzierung ist nicht
die beste, sobald Push-Pull mitentschieden wird.**

**Wichtig:** Die Topologie ist **nicht** mehr Fig. 1 des Papers (siehe
Abschnitt 1) — deshalb sind die Kosten-/Latenzzahlen unten **nicht** die im
Paper gedruckten Zahlen (3010, 2120, 1240, 3030, 360 …), sondern diese
Runde-eigenen, mit derselben Strenge berechneten und gegengeprüften Werte
(Engine vs. unabhängige Formel, Kraken vs. Enumeration). Die Paper-*Regeln*
(Raten, Selektivität, Kosten-/Latenzformeln, Score F) sind unverändert; nur
die *Form* des Netzwerks ist erweitert.

Code: `demo/export/factory_example.py` (Eingaben, Enumeration, Planer,
unabhängige Formel), Export in `export_scenario.py → build_factory_scenario`,
Daten in `demo/web/scenarios/factory/factory_join.json`.

## 1. Eingaben

| Größe | Wert | Stelle im Paper |
|---|---|---|
| Quelle A (Maschine, Vibration) | r(A) = 1000 Tupel/Fenster | Example 2 |
| Quelle B (Bedienfeld, Fehlerbestätigung) | r(B) = 10 Tupel/Fenster | Example 2 |
| Selektivität des Joins | s_AB = 0,1 | Example 1 |
| Pull-Selektivität | σ(A \| B) = 0,1 | Example 1 und 4 |
| Ausgaberate | r_out = s_AB · r(A) · r(B) = 1000 | Sec. 2.2; Example 4 setzt 1000 an |
| Ergebnisweiterleitung | Ausgabe geht zur Senke c (Egress) | Sec. 4.3.1 |
| Schemata pro Knoten | All-Push und PrePP-Push-Pull ⟨(∅,{B}), ({B},{A})⟩ | Sec. 4.2 Schritt 6, Example 4 |
| Latenzgewicht | ξ = 0 | Example 4 |
| Kapazität, L_max | nicht Teil des Beispiels („ignoring capacity and latency constraints") | Sec. 2.3 |

**Topologie — erweitert, nicht Fig. 1.** Im Paper (Fig. 1) laufen A und B
direkt in denselben ersten Knoten; dort sehen zwangsläufig alle drei echten
Kandidaten (1, 2, c) beide Quellen. Diese Runde gibt A und B stattdessen
**je einen eigenen Fog-Knoten** (n1 nur A, n2 nur B); beide treffen sich
erst in n3, dann geht es über n4 zur Cloud:

```
A → n1 ↘
         n3 → n4 → c
B → n2 ↗
```

Jede Kante ist 1 Hop (ℓ(e) = 1, wie im Paper). Knoten-IDs in der Engine:
c = 0, n1 (`FOG_A`) = 1, n2 (`FOG_B`) = 2, n3 (`FOG_MERGE`) = 3, n4
(`FOG_PRE_CLOUD`) = 4, A (`SRC_A`) = 5, B (`SRC_B`) = 6. Die Quellen tragen
keinen Sondernamen ("Maschine A"/"Bedienfeld B" wurden entfernt), sondern
denselben schlichten Buchstaben-Chip wie jede andere Quelle im Riff.

**Kandidatenknoten:** n3, n4, c (Quellen rechnen nicht, cpu = 0; n1/n2 sehen
je nur eine Quelle und sind deshalb — wie die Quellen selbst — nie
Platzierungskandidaten für `get_possible_placement_nodes_optimized`, siehe
Abschnitt 4 Punkt 7).

## 2. Kostenregeln (Sec. 4.3.1) und alle neun Optionen

Tupelvolumen V = Ingress + Egress. Push-Schritt: r · dist. Pull-Schritt:
Anfrage r(B) · dist(n, A) plus Antwort r(A) · σ(A|B) · dist(A, n).
Egress: r_out · dist(n, c). Latenz L: je Schritt die weiteste Distanz zum
Provider (Pull: Hin- und Rückweg), plus dist(n, c). Die Distanzen sind jetzt
dist(A, n3) = dist(B, n3) = 2, dist(n3, c) = 2 usw. (ein Hop mehr pro Stufe
als im Paper, weil A und B erst in n3 statt im ersten Knoten zusammentreffen).

| Knoten | Schema | Ingress | Egress | **V** | **L** |
|---|---|---|---|---|---|
| n3 | All-Push | 1000·2 + 10·2 = 2020 | 1000·2 = 2000 | **4020** | max(2,2) + 2 = **4** |
| n3 | Push-Pull | 10·2 + 10·2 + 1000·0,1·2 = 240 | 2000 | **2240** | 3·2 + 2 = **8** |
| n4 | All-Push | 1000·3 + 10·3 = 3030 | 1000·1 = 1000 | **4030** | max(3,3) + 1 = **4** |
| n4 | Push-Pull | 10·3 + 10·3 + 1000·0,1·3 = 360 | 1000 | **1360** | 3·3 + 1 = **10** |
| c | All-Push | 1000·4 + 10·4 = 4040 | 0 | **4040** | max(4,4) = **4** |
| c | Push-Pull | 10·4 + 10·4 + 1000·0,1·4 = 480 | 0 | **480** | 3·4 = **12** |

Die Werte im Spiel stammen **nicht** aus dieser Tabelle, sondern aus Krakens
`CostCalculator`. Der Exporter rechnet jede Zelle zusätzlich mit
`paper_cost_model()` nach (angepasst an die neuen Distanzen, siehe Abschnitt
1) und bricht bei Abweichung ab — `EXTENDED_EXAMPLE_GOLDENS` in
`test_factory_example.py` pinnt diese fünf Zellen als Regressionsanker.

Das Spiel zeigt (und bewertet) pro Knoten eine weitere, vom Paper nicht
benannte Kombination — „A pushen" —, die die freie Push/Pull-Wahl zulässt
(siehe Abschnitt 4 Punkt 3). Sie landet exakt beim Volumen von All-Push,
aber mit schlechterer Latenz; für die Tabelle oben und die Bewertung ändert
das nichts, da sie nie gewinnt. „Beides pullen" (nichts pushen) bietet die
Runde gar nicht erst an — ohne gepushte Tupel gibt es nichts, wonach gepullt
werden könnte (siehe Abschnitt 4 Punkt 3).

## 3. Bewertung, Sequential, Kraken, Enumeration

Score (Sec. 4.3.2): F = α · (V − V_min)/(V_max − V_min) + (1 − α) · (L − L_min)/(L_max − L_min),
min/max über alle neun Optionen (V: 480…4040, L: 4…12). Das Spiel
normalisiert mit genau diesen Ankern (geprüft in
`web/tests/factory_wasm.test.mjs`).

**Gewicht:** Hauptvergleich bei **α = 0,6** (Stufe „Ausgewogen", die
Standardstufe der Demo; das Paper nennt α ≥ 0,6 bei diesem Beispiel
„intermediate weights"). Die Stufen „Schnell" (0,2) und „Günstig" (0,9) sind
ebenfalls exportiert, jeweils mit eigenem Kraken-Lauf.

| Knoten / Schema | V | L | F bei α = 0,6 |
|---|---|---|---|
| n3 / All-Push | 4020 | 4 | 0,597 |
| n3 / Push-Pull | 2240 | 8 | 0,497 ← **Sequential** |
| n4 / All-Push | 4030 | 4 | 0,598 |
| n4 / Push-Pull | 1360 | 10 | 0,448 |
| c / All-Push | 4040 | 4 | 0,600 |
| c / Push-Pull | 480 | 12 | **0,400** ← **Kraken = Optimum** |

(„A pushen" liegt bei F = 0,697/0,748/0,800 an n3/n4/c — immer schlechter
als All-Push am selben Knoten, da gleiches V aber höhere L.)

- **Sequential** (Example 1), auf derselben Tabelle und mit demselben F wie
  Kraken: (1) Knoten wählen, der unter All-Push am besten ist. Alle
  All-Push-Optionen haben L = 4, also entscheidet V → n3 (4020, am
  günstigsten unter All-Push, weil am nächsten an den Quellen). (2) An n3
  das bessere Schema wählen → Push-Pull, 2240 / 8.
- **Kraken**: echter `run_kraken_solver` (Greedy) auf denselben Eingaben → c / Push-Pull, 480 / 12.
- **Vollständige Enumeration**: Minimum von F über alle 9 Optionen → c / Push-Pull.
  Krakens Ergebnis wird damit **verglichen**, nicht gleichgesetzt
  (`matches_reference` im JSON, Test `test_kraken_compared_with_enumeration_per_stage`).
  Es stimmt für alle drei Stufen überein.
- **Kopplung (Kriterium 2):** Unter All-Push bevorzugt: n3. Beste
  Kombination: Cloud + Push-Pull. Der Effekt hängt an der Gewichtung, wie im
  Paper.
- **Hinweis für die Standbetreuung:** Die Zeile „PrePP" (alles in der Cloud,
  Push-Pull) ist in diesem Beispiel identisch mit Kraken. Das ist korrekt,
  denn das gemeinsame Optimum liegt hier zufällig in der Cloud. Die Aussage
  der Runde ist der Vergleich mit Sequential.

## 4. Modellgrenzen und wie sie behandelt sind

1. **Operator.** Das Paper-Beispiel ist ein ungeordneter Window-Join
   [A ∘ B]. Das Engine-`AND(A, B)` ist als SEQ(A,B) ∪ SEQ(B,A) modelliert und
   liefert r_out = 2000; das widerspricht der Paper-Formel. `SEQ(A, B)` mit
   s = 0,1 liefert exakt r_out = s · r(A) · r(B) = 1000. Θ darf laut Paper
   zeitliche Ordnung enthalten (Sec. 2.1). Die Runde nutzt deshalb SEQ, zeigt
   aber den Titel „[A ∘ B]". Test: `test_output_rate_follows_paper_rate_model`.
2. **Pull-Selektivität.** PrePP liest im deterministischen Modus eine feste
   Tabelle aus dem 12-Knoten-Riff (`"A|AB": 0.0013437`) statt der
   Szenariowerte. Für die Fabrik-Runde wird diese Tabelle **nur innerhalb**
   von `factory_model()` durch σ(A|B) = 0,1 ersetzt und danach
   zurückgesetzt (Test `test_patch_is_scoped`). Der Forschungscode selbst ist
   unverändert.
3. **σ(B | A) ist im Paper nicht angegeben.** Gesetzt wird er nach der
   Engine-Invariante σ(A|AB) · σ(B|AB) = s_AB, also 1,0. „A pushen, B pullen"
   wird **nicht abgelehnt** — das Spiel gibt jeder Teilabfrage dieselben
   freien Push/Pull-Chips wie im Riff (nicht nur die zwei Paper-Schemata als
   Buttons), also ist auch diese dritte Kombination eine echte, von der
   Engine bewertete Option (`enumerate_decisions`, `ALL_SCHEMES`). Der Test
   zeigt, dass sie beim **Volumen** exakt mit All-Push übereinstimmt
   (σ(B|A)=1,0 macht das Pullen von B nie günstiger als es einfach zu
   pushen), bei der **Latenz** aber schlechter ist: die exakte Suche
   realisiert sie als zwei sequentielle Push-Schritte statt All-Pushs einem
   parallelen Schritt, zahlt also dist(Knoten,A) + dist(Knoten,B) statt deren
   Maximum. Die vierte Kombination — **nichts pushen** ("beides pullen") —
   bietet die Runde dagegen gar nicht an: dafür gibt es keinen Pull-all-
   Schnellknopf in der Schublade, und `score_one.py`s `paper_round`-
   Validierung lehnt eine leere Push-Gruppe ab. Pullen braucht ein bereits
   gepushtes Tupel als Filter/Auslöser; ohne das gibt es nichts, wonach
   gefiltert werden könnte — das ist kein günstig-aber-gültiger Sonderfall
   wie „A pushen", sondern schlicht keine sinnvolle Operation (dasselbe gilt
   für den Pull-all-Knopf im Riff, siehe
   [BACKLOG.md](BACKLOG.md)). Die paper-eigenen Zellen hängen weiterhin
   nicht von σ(B|A) ab (sie pullen B nie); „push_a" jetzt schon — beides
   geprüft in `test_push_a_is_all_push_in_cost_and_latency` und
   `test_unquantified_sigma_B_given_A_does_not_matter`.
4. **Sequential der Engine.** `Simulation.run()` berechnet „Sequential" als
   INEv-Platzierung + PrePP. Die Runde verwendet stattdessen die
   Sequential-Definition aus Example 1 auf Krakens Kostenmodell (Abschnitt 3)
   und lässt die INEv-Zeile weg — siehe Punkt 5 für den Grund.
5. **Befund in der Engine (nicht behoben, umgangen):** INEv schreibt beim
   Lauf seine Weiterleitungsentscheidungen in die gemeinsame Matrix
   `h_eventNodes` (`core/structures.set_event_nodes`). Krakens
   `PlacementOptimizer` liest dieselbe Matrix für die Kandidatenauswahl. Nach
   `Simulation.run()` bietet er in der Fabrik-Topologie nur noch die Cloud
   an. Die Runde rechnet Kraken und die Enumeration deshalb auf einem frisch
   aufgesetzten, nicht gelaufenen `Simulation`-Objekt (`fresh_simulation()`).
   In den vier Riff-Szenarien (12 Knoten, α = 0,6) ändert der Effekt nichts:
   gleiche Platzierung und Kosten mit und ohne. Für die Forschungs-Pipeline
   wäre ein eigenes Issue sinnvoll.
6. **Nicht modelliert:** Kapazitätsgrenzen und L_max.
7. **n1/n2 (FOG_A/FOG_B), nicht im Paper.** Siehe Abschnitt 1 — das ist die
   eigentliche Erweiterung dieser Runde. Beide sind nie Kandidaten
   (`get_possible_placement_nodes_optimized` schließt sie aus wie die
   Quellen selbst), ändern also an keiner Zahl aus Abschnitt 2/3 etwas
   (`test_single_source_hubs_are_unreachable_and_never_candidates`);
   antippen löst dieselbe generische Ablehnung wie im Riff aus
   (`state.ts placementIssue` → „n1 erreicht nicht jede Quelle von B").

## 5. Bewertung im Spiel

- Die Fabrik-Runde wird aus `decision_table` bewertet (Modus „exakt —
  vorberechnete Tabelle"). Das ist Krakens CostCalculator für jede mögliche
  Wahl, daher braucht die Runde keinen Backend-Dienst. Das Backend
  (`score_one.py factory factory_join …`) liefert identische Werte (Test).
- Beim Aufdecken zeigt das Spiel alle 9 Optionen (3 Kandidaten × 3
  Push/Pull-Kombinationen), nach Knoten gruppiert, mit V, L und F, markiert
  mit ★ (Optimum laut Enumeration), K (Kraken), S (Sequential) und „Du"; die
  nie gewinnende Zusatzkombination „A pushen" ist optisch gedimmt.

## 6. Reproduzieren

```bash
# Szenarien neu erzeugen (schreibt auch factory/factory_join.json)
uv run python demo/export/export_scenario.py
# Tests
cd demo/export && uv run python -m unittest tests.test_factory_example tests.test_score_one
cd demo/web && npm run typecheck && npm test
```

Der Exporter gibt die neun Zellen und für jede Stufe Kraken / Optimum /
Sequential / All-Push-Bestwert aus. Bei jeder Abweichung (Engine ≠
unabhängige Formel, Backend-Pfad ≠ freie Suche, WASM-All-Push ≠ Engine,
Baseline ≠ Tabellenzelle, Kraken ≠ Tabelle) endet er mit Fehlercode.
