# Standbetreuung — Kurzanleitung

Alles läuft lokal auf dem Standrechner. Es wird nichts öffentlich
bereitgestellt; beide Dienste lauschen nur auf `localhost`.

## Dienste

| Dienst | Zweck | Start (aus dem Repo-Root `INES-demo/`) | Adresse |
|---|---|---|---|
| Frontend | Spiel im Browser | `cd demo/web && npm run serve` | http://localhost:5173 |
| Push-Pull-Bewertung | bewertet Riff-Pläne mit Krakens Kostenmodell inkl. Push/Pull | `../INES/.venv/bin/python demo/backend/server.py` | http://localhost:8787 (`/health`) |

- **Krakens Schmiede braucht keinen Bewertungsdienst** (alle Optionen sind vorberechnet).
- Ohne Bewertungsdienst bewerten die Riff-Runden nur reine All-Push-Pläne.
  Pläne mit Pull bekommen dann bewusst **keine** Bewertung, statt einer falschen.
- Python-Umgebung: die `.venv` des Haupt-Worktrees `INES/` (networkx, numpy,
  pandas, pyarrow, flask). Im Worktree `INES-demo/` liegt keine eigene
  `pyproject.toml`. **Nicht `uv run` verwenden:** dort greift uv auf das
  pyenv-Python 3.11 zurück, dessen pandas/numpy nicht zusammenpassen
  („numpy.dtype size changed"), und der Dienst startet nicht (geprüft
  2026-11-06).

## Einmalig vor dem Event

```bash
cd demo/web
npm install
npm run build          # baut dist/ inkl. Szenarien
# nur falls engine/src geändert wurde: npm run build:wasm && npm run build
```

Wurden Szenarien neu exportiert (`../INES/.venv/bin/python demo/export/export_scenario.py`),
danach **immer** `npm run build`, sonst zeigt der Server die alten Daten.

## Start am Morgen

1. Terminal 1 (im Repo-Root `INES-demo/`): `../INES/.venv/bin/python demo/backend/server.py`
2. Terminal 2: `cd demo/web && npm run serve`
3. Browser (Vollbild, F11): http://localhost:5173
4. Unten im Bewertungsfeld steht die Statuszeile:
   - grüner Punkt „Push-Pull-Dienst verbunden" → alles bereit
   - roter Punkt „nicht erreichbar" → Terminal 1 prüfen bzw. neu starten

## Ablauf von Krakens Schmiede (ca. 2–3 Minuten)

1. Oben **Krakens Schmiede** antippen. Geschichte: „Maschine A schickt 1000
   Vibrationsmessungen pro Zeitfenster, Bedienfeld B nur 10
   Fehlerbestätigungen. Wo soll der Abgleich laufen?"
2. Besucher tippt oft zuerst einen quellen­nahen Knoten an, z. B. **n1** oder
   **n2** — beide sehen aber nur je eine Quelle und werden abgelehnt
   („n1 erreicht nicht jede Quelle von B …"). Guter Einstieg: „Ein Knoten
   braucht beide Ströme, um den Vergleich zu rechnen."
3. Platziert auf **n3** (wo A und B sich zum ersten Mal treffen) und
   **All-Push** gewählt → 4020 Tupel, Latenz 4.
4. „Und mit Push-Pull?" → **n3 + Push-Pull** → 2240. Genau das macht ein
   sequentieller Planer: erst den Knoten wählen, dann die Kommunikation.
5. „Geht es noch besser?" Wer die Teilabfrage auf **König Cloud** setzt und
   **Push-Pull** wählt, kommt auf **480** und zieht mit Kraken gleich (Blasen).
6. **„Kraken-Plan anzeigen"**: Tabelle mit allen 9 Optionen (3 Knoten × 3
   Push/Pull-Kombinationen — nicht nur die zwei des Papers, auch „A pushen"
   statt B). ★ = beste Option, K = Kraken, S =
   Sequential, I = INEv. Kernsatz: „Unter All-Push ist n3 der beste Knoten. Erst wenn
   man Platzierung und Push-Pull zusammen entscheidet, gewinnt die Cloud. Ein
   Planer, der nacheinander entscheidet, sieht das nie."
7. Optional, guter Aha-Moment: an der Cloud statt **B** mal **A** pushen (Chip
   „A" antippen). Kommt auf dasselbe Volumen wie All-Push, aber mit noch
   schlechterer Latenz — der Hinweistext über den Chips sagt vorher, warum:
   B ist 100× seltener, A komplett zu pushen bringt nichts.
8. Optional: Stufe **Schnell** antippen. Dann gewinnt n3 + All-Push (kürzeste
   Latenz). Botschaft: Kosten gegen Latenz ist eine Gewichtung.

Gut zu wissen: Die Zeile „PrePP" (alles in der Cloud, Push-Pull) ist hier
gleich gut wie Kraken. Das ist richtig so, das Optimum liegt in diesem
Beispiel in der Cloud. Der Vergleich, um den es geht, ist mit „Sequential".

„INEv" ist der tupel-günstigste All-Push-Knoten (n3, 4020 Tupel). INEv
kennt kein Push-Pull, deshalb ist sein Plan in jeder Stufe derselbe.

## Zurücksetzen

- **Nächster Besucher:** „Nochmal versuchen". Nach dem Aufdecken springt
  das Spiel dabei auf eine andere Topologie.
- **Gezielt eine Runde:** Topologie- bzw. Q-Knopf oben antippen (setzt die Platzierung zurück).
- **Komplett:** Seite neu laden (F5). Die gewählte Sprache bleibt erhalten.
- Sprache: Knopf **DE/EN** oben rechts.

## Störungen und Wiederanlauf

| Symptom | Ursache | Abhilfe |
|---|---|---|
| Statuszeile rot, „Dieser Plan kann gerade nicht bewertet werden" | Bewertungsdienst aus | Terminal 1: `../INES/.venv/bin/python demo/backend/server.py`. Die Seite merkt es binnen ~15 s und bewertet den offenen Plan automatisch, ohne Neuladen. Bis dahin: Krakens Schmiede spielen oder „alles pushen" wählen. |
| Seite leer / „Szenarien konnten nicht geladen werden" | Frontend-Server aus oder `dist/` fehlt | Terminal 2: `npm run build && npm run serve`, dann F5 |
| Alte Zahlen nach Re-Export | `dist/` nicht neu gebaut | `npm run build`, F5 |
| Rechner neu gestartet | — | Abschnitt „Start am Morgen" wiederholen |
| Port belegt | alter Prozess läuft noch | `PORT=5174 npm run serve` bzw. `PORT=8788 ../INES/.venv/bin/python demo/backend/server.py`. Achtung: `web/index.html` erwartet das Backend auf 8787. |

## Nicht tun

- Keine öffentliche URL oder QR-Code ausgeben: Es gibt kein Deployment, und
  der Bewertungsdienst ist nur für `localhost` gedacht (CORS offen, ohne
  Authentifizierung).
