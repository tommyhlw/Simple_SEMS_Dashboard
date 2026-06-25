# SEMS Inverter Viewer

## Summary
This project reads power series from the SEMS API and exposes them via `FastAPI` as time series.
A simple single-page frontend displays the PCurve series for PV, Meter and House (PV − Meter),
including live values, a chart, and CSV export.

## Local Setup (virtual environment recommended)

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
```

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
- `GET /api/pc_pv` — PCurve_Power_PV as JSON: `{ labels: [...], data: [...] }` (kW).
- `GET /api/pc_meter` — PCurve_Power_Meter as JSON (kW). Returns an empty/null-filled series if
  the series is missing.
- `GET /api/pc_house` — PCurve_Power_House (PV − Meter) as JSON (kW). Also calculated
  client-side if not available.
- `GET /api/pc_all` — Returns all three series as an object:
  `{ pv: {labels,data}, meter: {labels,data}, house: {labels,data} }`. Used by the frontend by default.
- `GET /api/pc_now` — Latest data point:
  `{ time: <x>, "pv-power": <kW|null>, "grid-feed-in/draw": <kW|null>, "house-power": <kW|null> }`.

## Frontend Features

- **Chart**: smooth lines (no dots), displays PV / Meter / House in kW. The frontend swaps PV/Meter
  colors and shows House as its own curve.
- **Live value bar** above the chart with icons: 🌞 PV, 🏭 Meter, 🏠 House; running clock on the right.
- **Meter status**: an emoji indicator below the meter value:
  `😎 Grid feed-in` (positive), `😢 Grid draw` (negative), `😕 No feed-in/draw` (null/0).
- **Auto-refresh**: initial load + automatic refresh every 5 minutes.
- **Buttons**: `Refresh` (immediate reload), `Export CSV` (downloads all time series as CSV).
- **Table**: last 10 entries by default, expandable (`Show all`) to display all values.

## Data Format (example row in CSV / table)

```json
{"time":"17:45","pv-power":0.0,"grid-feed-in/draw":5.765,"house-power":0}
```

## Notes

- Set `SEMS_USER` and `SEMS_PASSWORD` correctly so the server can reach the SEMS API. You can use
  a `.env` file; `start_server.sh` loads it automatically if present.
- The frontend prefers `/api/pc_all`; if `house` is missing from the response, the frontend
  calculates `house = pv - meter` and treats negative values as empty (house power cannot be negative).
- For troubleshooting: check logs via `docker compose logs -f` or the `./start_server.sh` output.
- If you'd like SVG icons, localized labels, or a Prometheus/InfluxDB export option, feel free to
  open an issue — contributions are welcome.

## Architecture

For frontend changes, see `frontend/index.html`. Backend logic is in `api/main.py`.

## License

This project is licensed under the **GNU General Public License v3.0** — see [LICENSE](LICENSE) for details.

Third-party dependencies and their licenses are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).