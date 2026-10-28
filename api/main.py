from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from datetime import datetime, date as datetime_date
from typing import Optional
from pygoodwe import SingleInverter
from pygoodwe.sems_plus import FailureKind, SemsPlusError
from starlette.concurrency import run_in_threadpool
import os
import logging
from playwright.async_api import async_playwright, Error as PlaywrightError


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.middleware("http")
async def log_requests(request, call_next):
    logger.info("HTTP %s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info("Response %s %s -> %s", request.method, request.url.path, response.status_code)
    return response

# Serve static files under /static and root serves index.html
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


def _create_inverter():
    account = os.getenv('SEMS_USER')
    password = os.getenv('SEMS_PASSWORD')
    station_id = os.getenv('SEMS_STATION_ID')
    if not account or not password or not station_id:
        raise HTTPException(
            status_code=500,
            detail="Missing SEMS_USER, SEMS_PASSWORD, or SEMS_STATION_ID environment variable",
        )

    return SingleInverter(station_id, account, password, skipload=True)


def _fetch_current_readings():
    inverter = _create_inverter()
    return inverter.get_current_readings(maxretries=1, delay=0)


def _fetch_daily_statistics(target_date: datetime_date):
    inverter = _create_inverter()
    if not inverter.do_login():
        raise SemsPlusError(FailureKind.AUTH, "SEMS+ login failed")

    station_id = os.getenv('SEMS_STATION_ID')
    client = inverter._web_client()
    return client.request(
        "/sems-plant/api/v1/hems/power/statisticsAndPreV2",
        method="POST",
        payload={
            "stationId": station_id,
            "items": ["pSystem", "pConsum", "pGrid"],
            "timeScale": 1,
            "timeZone": -1,
            "startTime": f"{target_date.isoformat()} 00:00:00",
            "endTime": f"{target_date.isoformat()} 23:59:59",
        },
    )


def _to_kw(value):
    if value is None:
        return None
    try:
        return round(float(str(value).removesuffix('(W)')) / 1000, 1)
    except (TypeError, ValueError):
        return None


def _current_power_response(readings, timestamp: datetime):
    powerflow = readings.get('powerflow') or {}
    inverter = readings.get('inverter') or {}
    inverter_full = inverter.get('invert_full') or {}

    pv = _to_kw(powerflow.get('pv'))
    meter = _to_kw(powerflow.get('grid', inverter_full.get('pmeter')))
    house = _to_kw(powerflow.get('load'))
    label = timestamp.strftime('%H:%M')

    return {
        "date": timestamp.date().isoformat(),
        "pv": {"labels": [label], "data": [pv]},
        "meter": {"labels": [label], "data": [meter]},
        "house": {"labels": [label], "data": [house]},
        "plant_statistics": "",
    }


def _statistics_power_response(statistics, target_date: datetime_date):
    series_by_item = {}
    data_list = statistics.get('dataList', []) if isinstance(statistics, dict) else []
    for series in data_list:
        if not isinstance(series, dict) or not isinstance(series.get('powerData'), list):
            continue
        points = {}
        for point in series['powerData']:
            if not isinstance(point, dict) or not isinstance(point.get('tp'), str):
                continue
            try:
                value = float(point.get('power'))
            except (TypeError, ValueError):
                value = None
            points[point['tp']] = round(value, 1) if value is not None else None
        series_by_item[series.get('item')] = points

    timestamps = sorted(set().union(*(points.keys() for points in series_by_item.values())))
    labels = []
    for timestamp in timestamps:
        try:
            labels.append(datetime.fromisoformat(timestamp).strftime('%H:%M'))
        except ValueError:
            labels.append(timestamp)

    def values_for(item):
        return [series_by_item.get(item, {}).get(timestamp) for timestamp in timestamps]

    return {
        "date": target_date.isoformat(),
        "pv": {"labels": labels, "data": values_for('pSystem')},
        "meter": {"labels": labels, "data": values_for('pGrid')},
        "house": {"labels": labels, "data": values_for('pConsum')},
        "plant_statistics": "",
    }


def _sems_http_exception(exc: SemsPlusError):
    logger.warning("SEMS+ readings failed (%s)", exc.kind.value)
    if exc.kind is FailureKind.RATE_LIMIT:
        status_code, detail = 429, "SEMS+ rate limit exceeded"
    elif exc.kind is FailureKind.NO_INVERTERS:
        status_code, detail = 404, "No inverter found for SEMS_STATION_ID; verify the station ID and SEMS+ migration status"
    else:
        status_code, detail = 502, "SEMS+ data request failed; verify credentials and service availability"
    return HTTPException(status_code=status_code, detail=detail)


@app.get("/api/pc_now")
async def get_pc_now(target_date: Optional[datetime_date] = Query(
    default=None)
    ):
    """Return current PCurve_Power series as kW for Chart.js.

    Response: {"date": date.strftime("%Y-%m-%d"), "pv": {"labels": [pv_labels], "data": [pv_data]}, "meter": {"labels": [meter_labels], "data": [meter_data]}, "house": {"labels": [house_labels], "data": [house_data]}}}
    """
    today = datetime.now().date()
    if target_date is not None and target_date != today:
        raise HTTPException(status_code=400, detail="/api/pc_now only returns the latest live measurement")
    try:
        readings = await run_in_threadpool(_fetch_current_readings)
        return _current_power_response(readings, datetime.now().astimezone())
    except HTTPException:
        raise
    except SemsPlusError as exc:
        raise _sems_http_exception(exc) from exc
    except Exception as exc:
        logger.exception("Error fetching current SEMS+ readings")
        raise HTTPException(status_code=502, detail="Unable to fetch current SEMS+ readings") from exc

@app.get("/api/pc_all")
async def get_pc_all(target_date: Optional[datetime_date] = Query(
        default=None,
        description="Datum für die historische SEMS+ Tageskurve im Format YYYY-MM-DD"
    )):
    """Return historical SEMS+ PV, grid, and consumption power series for one day."""
    date = target_date or datetime.now().date()

    try:
        logger.info("Fetching SEMS+ statistics for %s", date.isoformat())
        statistics = await run_in_threadpool(_fetch_daily_statistics, date)
        return _statistics_power_response(statistics, date)
    except HTTPException:
        raise
    except SemsPlusError as exc:
        raise _sems_http_exception(exc) from exc
    except Exception as exc:
        logger.exception("Error fetching SEMS+ statistics")
        raise HTTPException(status_code=502, detail="Unable to fetch SEMS+ daily statistics") from exc


async def _render_mobile_snapshot(request: Request, target_date: datetime_date, width: int = 960, height: int = 540):
    page_url = f"{request.base_url}?target_date={target_date.isoformat()}&snapshot=1"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
        page = await context.new_page()
        await page.goto(page_url, wait_until='networkidle', timeout=30000)
        await page.wait_for_selector('#pvChart', timeout=20000)
        await page.wait_for_function(
            "() => window.dashboardDataReady === true && window.chart && window.chart.data && window.chart.data.datasets && window.chart.data.datasets.length > 0",
            timeout=60000,
        )
        await page.evaluate(
            f"() => {{"
            "  const screen = document.querySelector('.screen');"
            "  if (!screen) return;"
            f"  screen.style.width = '{width}px';"
            f"  screen.style.minWidth = '{width}px';"
            f"  screen.style.maxWidth = '{width}px';"
            f"  screen.style.height = '{height}px';"
            "  screen.style.minHeight = screen.style.height;"
            "  screen.style.maxHeight = screen.style.height;"
            "  screen.style.padding = '0';"
            "  screen.style.margin = '0 auto';"
            "  document.documentElement.style.margin = '0';"
            "  document.documentElement.style.padding = '0';"
            "  document.body.style.margin = '0';"
            "  document.body.style.padding = '0';"
            "  document.body.style.overflow = 'hidden';"
            "  window.dispatchEvent(new Event('resize'));"
            "}"
        )
        await page.wait_for_timeout(600)
        screen = await page.query_selector('.screen')
        if not screen:
            raise HTTPException(status_code=500, detail='Screenshot region not found')

        image_bytes = await screen.screenshot(type='png')
        await browser.close()
        return image_bytes


@app.get('/api/pc_snapshot')
async def get_pc_snapshot(request: Request, target_date: Optional[datetime_date] = Query(
        default=datetime.now().date(),
        description='Datum im Format YYYY-MM-DD'
    )):
    """Return a rendered PNG snapshot of the mobile dashboard."""
    try:
        image_bytes = await _render_mobile_snapshot(request, target_date)
        return Response(content=image_bytes, media_type='image/png')
    except PlaywrightError as exc:
        logger.exception('Snapshot rendering failed')
        raise HTTPException(status_code=500, detail=f'Browser snapshot failed: {exc}')
    except Exception as exc:
        logger.exception('Snapshot generation failed')
        raise HTTPException(status_code=500, detail=str(exc))

