# SEMS Inverter Viewer

## Summary
This project reads GoodWe SEMS+ current values and daily power statistics using `pygoodwe` and
exposes them via `FastAPI`. The single-page frontend displays live PV, meter, and house values,
historical daily curves, CSV export, and a rendered PNG snapshot endpoint for the mobile dashboard.

## Local Setup (Python 3.12+; virtual environment recommended)

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Set environment variables (or use a `.env` file):

```bash
export SEMS_USER="your_username"
export SEMS_PASSWORD="your_password"
export SEMS_STATION_ID="your_station_uuid"
```

Use the station UUID from your SEMS+ station URL for `SEMS_STATION_ID`; do not use the inverter
serial number. `pygoodwe` uses this ID to retrieve station flow and device status. A Classic station
ID works only if the station has been migrated to SEMS+. All three variables can also be placed in
`.env`.

3a. Start the server directly with Uvicorn (development):

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

3b. Alternatively, use the convenience start script (ensures unbuffered output):

```bash
./start_server.sh .env 8000
```

Open the Web UI at: http://localhost:8000

## Docker / Docker Compose

Recommended: use `docker compose` with a `.env` file or `--env-file`.

Build & start (from the project folder):

```bash
docker compose build
docker compose up -d
```

View logs:

```bash
docker compose logs -f
```

## Available API Endpoints

- `GET /` — serves the frontend (`frontend/index.html`).
- `GET /api/pc_all` — Returns historical daily power series in kW for PV, meter, and house:
  `{ pv: {labels: [...], data: [...]}, meter: {labels: [...], data: [...]}, house: {labels: [...], data: [...]} }`.
  Accepts `target_date=YYYY-MM-DD`; defaults to today. Data comes from SEMS+ `statisticsAndPreV2`.
- `GET /api/pc_now` — Returns the latest live measurement from SEMS+ station flow, for example:
  `{ date: "YYYY-MM-DD", pv: {labels:["HH:MM"], data:[<kW|null>]}, meter: {labels:["HH:MM"], data:[<kW|null>]}, house: {labels:["HH:MM"], data:[<kW|null>]} }`.
- `GET /api/pc_snapshot` — Returns a rendered PNG snapshot of the mobile dashboard.

`target_date` selects the day shown in the chart and snapshot. The live value cards always use the
latest reading, regardless of the selected chart date.

```bash
curl "http://localhost:8000/api/pc_all?target_date=2026-10-26"
curl "http://localhost:8000/api/pc_now"
```

## Frontend Features

- **Chart**: displays daily PV / meter / house power curves in kW.
- **Live values** with icons: 🌞 PV, 🏭 Meter, 🏠 House; measurement time above the chart.
- **Meter status**: `😎 Grid feed-in` (positive), `😢 Grid draw` (negative),
  `😕 No feed-in/draw` (null/0).
- **Auto-refresh**: initial load + automatic refresh every 5 minutes.
- **Buttons**: `Refresh` (immediate reload), `Export CSV` (downloads the selected day's series as CSV).

## Data Format (CSV)

```csv
label,pv,meter,house
14:35,2.4,-0.3,2.7
```

## Notes

- Set `SEMS_USER`, `SEMS_PASSWORD`, and `SEMS_STATION_ID` correctly. You can use a `.env` file;
  `start_server.sh` loads it automatically if present.
- `pc_all` requests `pSystem`, `pConsum`, and `pGrid` through the SEMS+ `statisticsAndPreV2` API.
  `pc_now` uses the station flow endpoint. The meter indicator describes grid export/import, not PV
  production. The API keeps the station's `pGrid` sign: positive means feed-in and negative means
  grid draw. House consumption comes directly from `pConsum`/`load`.
- For troubleshooting: check logs via `docker compose logs -f` or the `./start_server.sh` output.
- If you'd like SVG icons, localized labels, or a Prometheus/InfluxDB export option, feel free to
  open an issue — contributions are welcome.

## Architecture

For frontend changes, see `frontend/index.html`. Backend logic is in `api/main.py`.

## Authors

- Thomas Rosenkranz
- GitHub Copilot (LLM assistance)

## License

This project is licensed under the **GNU General Public License v3.0** — see [LICENSE](LICENSE) for details.

Third-party dependencies and their licenses are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).