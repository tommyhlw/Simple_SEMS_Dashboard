from base64 import b64decode, b64encode
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from datetime import datetime, date as datetime_date
from typing import Optional
import sems_portal_api
import aiohttp
import os
import logging
import time
import asyncio
from playwright.async_api import async_playwright, Error as PlaywrightError


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# simple in-memory cache for power_station_id to avoid intermittent None on concurrent calls
_cached_power_station_id: Optional[str] = None
_cached_token: Optional[str] = None
_cache_ts: float = 0.0
_cache_lock = asyncio.Lock()


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


async def do_login(session: aiohttp.ClientSession):
    sems_portal_api.set_region('eu')
    account = os.getenv('SEMS_USER')
    password = os.getenv('SEMS_PASSWORD')
    if not account or not password:
        logger.error("Missing SEMS_USER or SEMS_PASSWORD environment variables")
        raise HTTPException(status_code=500, detail="Missing SEMS_USER or SEMS_PASSWORD")

    data = await sems_portal_api.login_to_sems(session, account, password)
    header_token = sems_portal_api.login_response_to_token(data)
    logger.info("Logged in; uid=%s", data.get('uid'))
    logger.info("Login response data: %s", data)
    # cache power_station_id to avoid intermittent None on concurrent requests
    global _cached_power_station_id, _cached_token, _cache_ts
    # if token changed, invalidate cache
    if _cached_token != header_token:
        _cached_token = header_token
        _cached_power_station_id = None

    # return cached if fresh (5s) and present
    if _cached_power_station_id and (time.time() - _cache_ts) < 5:
        logger.info("Using cached power_station_id: %s", _cached_power_station_id)
        return data, header_token, _cached_power_station_id

    # otherwise fetch under lock with a couple retries
    async with _cache_lock:
        if _cached_power_station_id and (time.time() - _cache_ts) < 5:
            logger.info("Using cached power_station_id (post-lock): %s", _cached_power_station_id)
            return data, header_token, _cached_power_station_id

        power_station_id = None
        for attempt in range(3):
            try:
                power_station_id = await sems_portal_api.get_station_ids(session, token=header_token)
                if power_station_id:
                    break
            except Exception:
                logger.warning("get_station_ids attempt %d failed", attempt + 1)
            await asyncio.sleep(0.2)

        _cached_power_station_id = power_station_id
        _cache_ts = time.time()
        logger.info("Retrieved power_station_id: %s", _cached_power_station_id)
        
        return data, header_token, _cached_power_station_id

@app.get("/api/pc_now")
async def get_pc_now(target_date: Optional[datetime_date] = Query(
        default=datetime.now().date())
    ):
    """Return current PCurve_Power series as kW for Chart.js.

    Response: {"date": date.strftime("%Y-%m-%d"), "pv": {"labels": [pv_labels], "data": [pv_data]}, "meter": {"labels": [meter_labels], "data": [meter_data]}, "house": {"labels": [house_labels], "data": [house_data]}}}
    """
    date=target_date
    get_pc_all_response = await get_pc_all(target_date=date)
    pv_now = get_pc_all_response["pv"]["data"][-1] if get_pc_all_response["pv"]["data"] else None
    house_now = get_pc_all_response["house"]["data"][-1] if get_pc_all_response["house"]["data"] else None
    meter_now = get_pc_all_response["meter"]["data"][-1] if get_pc_all_response["meter"]["data"] else None
    label = get_pc_all_response["pv"]["labels"][-1] if get_pc_all_response["pv"]["labels"] else None
    get_pc_now = {"date": get_pc_all_response["date"], "pv": {"labels": [label], "data": [pv_now]}, "meter": {"labels": [label], "data": [meter_now]}, "house": {"labels": [label], "data": [house_now]}}
    return get_pc_now

@app.get("/api/pc_all")
async def get_pc_all(target_date: Optional[datetime_date] = Query(
        default=datetime.now().date(),
        description="Datum im Format YYYY-MM-DD"
    )):
    """Return PCurve_Power series as kW for Chart.js.

    Response: {"date": date.strftime("%Y-%m-%d"), "pv": {"labels": [pv_labels], "data": [pv_data]}, "meter": {"labels": [meter_labels], "data": [meter_data]}, "house": {"labels": [house_labels], "data": [house_data]}}}
    """
    date=target_date
    sems_portal_api.set_region('eu')
    async with aiohttp.ClientSession() as session:
        try:
            logger.info("Handling /api/pc_all_v2 request")
            data, header_token, power_station_id = await do_login(session)
            # fetch plant power chart
            chart = await sems_portal_api.get_plant_power_chart(session, plant_id=power_station_id, token=header_token, targetDate=date)
            lines = chart.get('lines', []) if isinstance(chart, dict) else []

            pv_series = next((l for l in lines if l.get('key') == 'PCurve_Power_PV'), None)
            meter_series = next((l for l in lines if l.get('key') == 'PCurve_Power_Meter'), None)
            house_series = next((l for l in lines if l.get('key') == 'PCurve_Power_Load'), None)

            if pv_series is None or meter_series is None:
                logger.warning("One or more required PCurve_Power series not found in chart response")
                raise HTTPException(status_code=404, detail='One or more required PCurve_Power series not found')
            
            def extract_series(series):
                if series is None:
                    return [], []
                xy = series.get('xy', [])
                labels = [pt.get('x') for pt in xy]
                # convert W to kW and round to 1 decimal, treat 0 as "" for better chart display
                data_vals = ["" if (val := pt.get('y')) == 0 else (val := str(round(pt.get('y') / 1000.0, 1))) for pt in xy]
                logger.info("Returning %d data points", len(data_vals))
                return labels, data_vals

            pv_labels, pv_data = extract_series(pv_series)
            meter_labels, meter_data = extract_series(meter_series)
            house_labels, house_data = extract_series(house_series)
            if not house_labels and len(pv_labels) == 24:
                house_labels = pv_labels
                house_data = [""] * len(pv_labels)
            
            plant_statistics = ""
            
            return {"date": date.strftime("%Y-%m-%d"), "pv": {"labels": pv_labels, "data": pv_data}, "meter": {"labels": meter_labels, "data": meter_data}, "house": {"labels": house_labels, "data": house_data}, "plant_statistics": plant_statistics}

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error fetching PCurve_Power_PV")
            raise HTTPException(status_code=500, detail=str(exc))


async def _render_mobile_snapshot(request: Request, target_date: datetime_date, width: int = 960, height: int = 540):
    page_url = f"{request.base_url}?target_date={target_date.isoformat()}&snapshot=1"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
        page = await context.new_page()
        await page.goto(page_url, wait_until='networkidle', timeout=30000)
        await page.wait_for_selector('#pvChart', timeout=20000)
        await page.wait_for_function(
            "() => window.chart && window.chart.data && window.chart.data.datasets && window.chart.data.datasets.length > 0",
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

