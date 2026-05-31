from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sems_portal_api
from sems_portal_api import login_to_sems, set_region
import aiohttp
import os
import logging
import json
from pathlib import Path
from typing import Optional
import time
import asyncio

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
    set_region('eu')
    account = os.getenv('SEMS_USER')
    password = os.getenv('SEMS_PASSWORD')
    if not account or not password:
        logger.error("Missing SEMS_USER or SEMS_PASSWORD environment variables")
        raise HTTPException(status_code=500, detail="Missing SEMS_USER or SEMS_PASSWORD")

    data = await login_to_sems(session, account, password)
    header_token = sems_portal_api.login_response_to_token(data)
    logger.info("Logged in; uid=%s", data.get('uid'))
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

        result = None
        for attempt in range(3):
            try:
                result = await sems_portal_api.get_station_ids(session, token=header_token)
                if result:
                    break
            except Exception:
                logger.warning("get_station_ids attempt %d failed", attempt + 1)
            await asyncio.sleep(0.2)

        _cached_power_station_id = result
        _cache_ts = time.time()
        logger.info("Retrieved power_station_id: %s", _cached_power_station_id)
        return data, header_token, _cached_power_station_id


@app.get("/api/pc_pv")
async def get_pc_pv():
    """Return PCurve_Power_PV series as kW for Chart.js.

    Response: { labels: [...], data: [...] }
    """
    sems_portal_api.set_region('eu')
    async with aiohttp.ClientSession() as session:
        try:
            logger.info("Handling /api/pc_pv request")
            data, header_token, power_station_id = await do_login(session)

            # fetch plant power chart
            chart = await sems_portal_api.get_plant_power_chart(session, plant_id=power_station_id, token=header_token)

            # find the PCurve_Power_PV series
            lines = chart.get('lines', []) if isinstance(chart, dict) else []
            pv_series = next((l for l in lines if l.get('key') == 'PCurve_Power_PV'), None)

            if pv_series is None:
                logger.warning("PCurve_Power_PV not found in chart response")
                raise HTTPException(status_code=404, detail='PCurve_Power_PV not found')

            xy = pv_series.get('xy', [])
            labels = [pt.get('x') for pt in xy]
            # convert W to kW
            data_vals = [round((pt.get('y') or 0) / 1000.0, 3) for pt in xy]
            logger.info("Returning %d data points", len(data_vals))
            
            return {"labels": labels, "data": data_vals}

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error fetching PCurve_Power_PV")
            raise HTTPException(status_code=500, detail=str(exc))


        
@app.get("/api/pc_meter")
async def get_pc_meter():
    """Return PCurve_Power_Meter series as kW.

    If `plant_mock.json` exists in the project root it will be used.
    """
    sems_portal_api.set_region('eu')
    sleep_time = 1  # simulate some latency
    async with aiohttp.ClientSession() as session:
        try:
            logger.info("Handling /api/pc_meter request (live)")
            data, header_token, power_station_id = await do_login(session)
            chart = await sems_portal_api.get_plant_power_chart(session, plant_id=power_station_id, token=header_token)
            lines = chart.get('lines', []) if isinstance(chart, dict) else []
            pv_series = next((l for l in lines if l.get('key') == 'PCurve_Power_Meter'), None)
            if pv_series is None:
                # Return empty/null data with labels derived from any available series (prefer PV)
                logger.warning("PCurve_Power_Meter not found in live chart response - returning empty series")
                # try to build labels from PCurve_Power_PV or first available line
                fallback = next((l for l in lines if l.get('key') == 'PCurve_Power_PV'), None)
                if fallback is None and lines:
                    fallback = lines[0]
                if fallback:
                    xy = fallback.get('xy', [])
                    labels = [pt.get('x') for pt in xy]
                    data_vals = [None for _ in labels]
                else:
                    labels = []
                    data_vals = []
                return {"labels": labels, "data": data_vals}
            xy = pv_series.get('xy', [])
            labels = [pt.get('x') for pt in xy]
            data_vals = [round((pt.get('y') or 0) / 1000.0, 3) for pt in xy]
            return {"labels": labels, "data": data_vals}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error fetching PCurve_Power_Meter")
            raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/pc_house")
async def get_pc_house():
    """Return PCurve_Power_House series as kW.

    PCurve_Power_House = PCurve_Power_PV - PCurve_Power_Meter

    If `plant_mock.json` exists in the project root it will be used.
    """
    try:
        # reuse existing endpoints to get PV and Meter series (they return kW)
        pv_resp = await get_pc_pv()
        meter_resp = await get_pc_meter()

        pv_labels = pv_resp.get('labels', [])
        pv_data = pv_resp.get('data', [])

        meter_labels = (meter_resp or {}).get('labels') if isinstance(meter_resp, dict) else None
        meter_data = (meter_resp or {}).get('data') if isinstance(meter_resp, dict) else None

        # map meter values by label for robust alignment
        meter_map = {}
        if meter_labels and meter_data:
            for lbl, val in zip(meter_labels, meter_data):
                meter_map[lbl] = val

        house = []
        for i, lbl in enumerate(pv_labels):
            pvv = pv_data[i] if i < len(pv_data) else None
            mv = meter_map.get(lbl) if meter_map else (meter_data[i] if meter_data and i < len(meter_data) else None)
            if pvv is None or mv is None:
                house.append(None)
            else:
                if mv > 0 and pvv == 0:
                    # if meter shows production but PV is zero, treat house as 0
                    house.append(0)
                else:
                    house.append(round(pvv - mv, 3))

        return {"labels": pv_labels, "data": house}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error computing PCurve_Power_House")
        raise HTTPException(status_code=500, detail=str(exc))
    

@app.get("/api/pc_now")
async def get_pc_now():
    """Return the latest (most recent) values for PV, Meter and House as kW.

    Response: { Uhrzeit: <x-value>, PV-Strom: <kW or null>, Netzeinspeisung/-Bezug: <kW or null>, Haus-Strom: <kW or null> }
    """
    try:
        pv = await get_pc_pv()
        meter = await get_pc_meter()
        house = await get_pc_house()

        pv_labels = pv.get('labels', []) if isinstance(pv, dict) else []
        pv_data = pv.get('data', []) if isinstance(pv, dict) else []

        if not pv_labels:
            return {"Uhrzeit": None, "PV-Strom": None, "Netzeinspeisung/-Bezug": None, "Haus-Strom": None}

        last_label = pv_labels[-1]
        pv_val = pv_data[-1] if pv_data and len(pv_data) >= 1 else None

        # align meter by label when possible
        meter_val = None
        if isinstance(meter, dict):
            m_labels = meter.get('labels', [])
            m_data = meter.get('data', [])
            if m_labels and last_label in m_labels:
                idx = m_labels.index(last_label)
                if idx < len(m_data):
                    meter_val = m_data[idx]
            else:
                meter_val = m_data[-1] if m_data else None

        # align house by label when possible
        house_val = None
        if isinstance(house, dict):
            h_labels = house.get('labels', [])
            h_data = house.get('data', [])
            if h_labels and last_label in h_labels:
                idx = h_labels.index(last_label)
                if idx < len(h_data):
                    house_val = h_data[idx]
            else:
                house_val = h_data[-1] if h_data else None

        return {"Uhrzeit": last_label, "PV-Strom": pv_val, "Netzeinspeisung/-Bezug": meter_val, "Haus-Strom": house_val}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error fetching current pc values")
        raise HTTPException(status_code=500, detail=str(exc))



