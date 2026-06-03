Projekt: SEMS inverter viewer

Kurz
-----
Dieses Projekt liest Leistungsreihen von der SEMS-API und stellt sie per `FastAPI` als Zeitreihen bereit. Eine einfache Single-Page-Frontend zeigt die PCurve-Serien für PV, Meter und House (PV − Meter) an, inklusive Live-Werte, Chart und CSV-Export.

Lokal starten (virtuelle Umgebung empfohlen)
------------------------------------------------
1. Virtuelle Umgebung anlegen und Abhängigkeiten installieren:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Umgebungsvariablen setzen (oder `.env` verwenden):

```bash
export SEMS_USER="dein_benutzer"
export SEMS_PASSWORD="dein_passwort"
```

3a. Server direkt mit Uvicorn starten (Entwicklung):

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

3b. Alternativ: bequemes Start-Skript verwenden (sorgt für unbuffered output):

```bash
./start_server.sh .env 8000
```

Web-UI öffnen: http://localhost:8000

Docker / Docker Compose
------------------------
Empfohlen: `docker compose` mit einer `.env`-Datei oder `--env-file` nutzen.

Build & Start (im Projektordner):

```bash
docker compose build
docker compose up -d
```

Logs ansehen:

```bash
docker compose logs -f
```

Verfügbare API-Endpunkte
------------------------
- `GET /` — liefert das Frontend (`frontend/index.html`).
- `GET /api/pc_pv` — PCurve_Power_PV als JSON: `{ labels: [...], data: [...] }` (kW).
- `GET /api/pc_meter` — PCurve_Power_Meter als JSON (kW). Falls Serie fehlt, wird eine leere/null-gefüllte Serie zurückgegeben.
- `GET /api/pc_house` — PCurve_Power_House (PV − Meter) als JSON (kW). (Wird auch clientseitig berechnet, falls nicht verfügbar.)
- `GET /api/pc_all` — Liefert alle drei Serien als Objekt: `{ pv: {labels,data}, meter: {labels,data}, house: {labels,data} }`. Das Frontend verwendet standardmäßig diesen Endpunkt.
- `GET /api/pc_now` — aktuellster Datenpunkt: `{ Uhrzeit: <x>, "PV-Strom": <kW|null>, "Netzeinspeisung/-Bezug": <kW|null>, "Haus-Strom": <kW|null> }`.

Frontend-Funktionen
-------------------
- Chart: glatte Linien (ohne Punkte), zeigt PV / Meter / House in kW. Das Frontend tauscht PV/Meter Farben und zeigt House als eigene Kurve.
- Aktuelle Werteleiste über dem Chart mit Icons: 🌞 PV, 🏭 Meter, 🏠 House; rechts laufende Uhr.
- Meter-Status: unter dem Zählerwert erscheint ein Indikator mit Emoji: `😎 Netzeinspeisung` (positiv), `😢 Netzbezug` (negativ), `😕 Keine Einspeisung/Bezug` (null/0).
- Automatische Aktualisierung: initialer Load + automatisches Refresh alle 5 Minuten.
- Buttons: `Refresh` (sofortiger Reload), `Export CSV` (download aller Zeitreihen als CSV).
- Tabelle: standardmäßig die letzten 10 Einträge, ausklappbar (`Show all`) um alle Werte anzuzeigen.

Datenformat (Beispiel für einzelne Zeile im CSV / Tabelle)
--------------------------------------------------------
```json
{"Uhrzeit":"17:45","PV-Strom":0.0,"Netzeinspeisung/-Bezug":5.765,"Haus-Strom":0}
```

Hinweise
--------
- Setze `SEMS_USER` und `SEMS_PASSWORD` korrekt, damit der Server die SEMS-API erreichen kann. Du kannst eine `.env`-Datei nutzen; `start_server.sh` lädt diese automatisch, falls vorhanden.
- Das Frontend bevorzugt `/api/pc_all`; wenn `house` in der Antwort fehlt, berechnet das Frontend `house = pv - meter` und zeigt negative Werte als leer an (Haus kann nicht negativ sein).
- Bei Problemen: Logs prüfen (`docker compose logs -f` oder `./start_server.sh` Ausgaben).
- Falls du SVG-Icons, deutsche Beschriftungen oder eine Prometheus-/Influx-Export-Option möchtest, sag Bescheid — ich kann das ergänzen.

Kontakt
-------
Für Änderungen am Frontend schaue in `frontend/index.html`. Backend-Logik ist in `api/main.py`.

