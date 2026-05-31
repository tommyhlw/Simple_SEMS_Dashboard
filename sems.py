import aiohttp
import asyncio
import dotenv
import os
import sems_portal_api
from typing import Any
from datetime import datetime
from sems_portal_api import login_to_sems, set_region

dotenv.load_dotenv()

account = os.getenv("SEMS_USER")
password = os.getenv("SEMS_PASSWORD")
inverter_id = os.getenv("SEMS_INVERTER_ID")

async def get_pv_chart(
    session: aiohttp.ClientSession,
    plant_id: str,
    token: str,
    targetDate: datetime = datetime.now(),
) -> Any:
    """Retrieve ppv chart data."""
    formatted_date = targetDate.strftime("%Y-%m-%d")
    #https://eu-gateway.semsportal.com/web/sems/sems-plant/api/portal/equipments/9080KMTU229W0066/timeSeriesData
    url = f"https://eu-gateway.semsportal.semsportal.com/web/sems/sems-i/api/portal/equipments/{inverter_id}/timeSeriesData"
    headers = {"Content-Type": "application/json", "Token": token}
    body = {"id": plant_id, "date": formatted_date, "full_script": False}

    response = await session.post(url, headers=headers, json=body, timeout=25)
    response_data = await response.json()

    return response_data["data"]

async def main():
    set_region('eu')
    async with aiohttp.ClientSession() as session:
        
        data = await login_to_sems(session, account, password)
        print(data)

        # Some API endpoints expect a transformed token (base64 of the login response)
        header_token = sems_portal_api.login_response_to_token(data)

        # Get the actual power station id(s) for the account
        power_station_id = await sems_portal_api.get_station_ids(session, token=header_token)
        print("power_station_id:", power_station_id)

        chart = await sems_portal_api.get_plant_power_chart(session, plant_id=power_station_id, token=header_token)
        print(chart)

        # Fetch inverter details directly and print a concise summary
        try:
            inverter_details = await sems_portal_api.sems_plant_details.get_inverter_details(session, power_station_id=power_station_id, token=header_token)
            print("Inverter details (raw):", inverter_details)
            # Print concise info for each inverter
            for inv in inverter_details:
                sn = inv.get('sn')
                model = None
                inner_temp = None
                print(f"Inverter SN: {sn}")
                print(f"Raw dict: {inv.get('dict')}")
                left = inv.get('dict', {}).get('left', [])
                right = inv.get('dict', {}).get('right', [])
                for d in left:
                    if d.get('key') == 'dmDeviceType':
                        model = d.get('value')
                for d in right:
                    if d.get('key') == 'innerTemp':
                        inner_temp = d.get('value')
                print(f"- SN: {sn}, model: {model}, innerTemp: {inner_temp}")
        except Exception as exc:
            print("Could not fetch inverter details:", exc)



        

if __name__ == "__main__":
    asyncio.run(main())
