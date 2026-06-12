#!/usr/bin/env python3
"""
Integrationstest fuer das DC-Lastmanagement.

Simuliert eine stromgeregelte DC-Ladestation (OCPP 1.6J Client zu evcc) plus
einen steuerbaren Netzzaehler (HTTP). Die Station meldet die DC-Spannung als
PLAIN 'Voltage'-Measurand (genau wie die reale inergia-Station), liefert
P = U_dc * min(I_befohlen, I_auto) und schliesst die Regelschleife ueber den
Netzzaehler. Geprueft wird, ob evcc den Stromsollwert spannungsrichtig
(I = Budget / U_dc) statt mit der festen AC-Annahme (Budget / 690) berechnet.

Kein Auto, kein Pi, kein realer Strom - reine Software-Simulation.
"""
import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import websockets

# Windows: SelectorEventLoop vermeidet Proactor-recv-Fehler bei Websockets
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

EVCC_OCPP = "ws://127.0.0.1:8887/SIMDC"
GRID_PORT = 8099

# ---- gemeinsamer, von beiden Threads gelesener/geschriebener Zustand --------
state = {
    "u_dc": 400.0,        # momentane Fahrzeug-/Ladespannung (V)
    "car_max_a": 250.0,   # Strombegrenzung des Autos (A)
    "i_cmd": 0.0,         # zuletzt von evcc befohlener Stromsollwert (A)
    "charge_power": 0.0,  # resultierende Ladeleistung (W)
    "building": 8000.0,   # Gebaeudegrundlast (W), nicht steuerbar
    "pv": 0.0,            # PV-Erzeugung (W)
    "tx": 1,
}

def grid_power():
    """Netzbezug am Anschlusspunkt = Gebaeude + Laden - PV (positiv = Bezug)."""
    return state["building"] + state["charge_power"] - state["pv"]

# ---- HTTP-Netzzaehler -------------------------------------------------------
class GridHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(f"{grid_power():.1f}".encode())

    def log_message(self, *a):
        pass

def run_grid_server():
    HTTPServer(("127.0.0.1", GRID_PORT), GridHandler).serve_forever()

# ---- OCPP-Station -----------------------------------------------------------
def now_iso():
    # feste Zeit reicht evcc; nutze monotone Wanduhr
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def meter_values_msg(unique_id_counter):
    """MeterValues mit PLAIN-Measurands (kein Phasensuffix) wie die echte Station."""
    p = state["charge_power"]
    i = (p / state["u_dc"]) if state["u_dc"] > 0 else 0.0
    sampled = [
        {"measurand": "Power.Active.Import", "unit": "W", "value": f"{p:.1f}"},
        {"measurand": "Current.Import", "unit": "A", "value": f"{i:.2f}"},
        {"measurand": "Voltage", "unit": "V", "value": f"{state['u_dc']:.1f}"},
        {"measurand": "SoC", "unit": "Percent", "value": "55"},
        {"measurand": "Energy.Active.Import.Register", "unit": "Wh", "value": "1000"},
    ]
    return [2, f"mv-{unique_id_counter}", "MeterValues", {
        "connectorId": 1,
        "transactionId": state["tx"],
        "meterValue": [{"timestamp": now_iso(), "sampledValue": sampled}],
    }]

def apply_command():
    """Schliesst die Physik: Ladeleistung folgt dem befohlenen Strom * Spannung."""
    eff_i = max(0.0, min(state["i_cmd"], state["car_max_a"]))
    state["charge_power"] = eff_i * state["u_dc"]

async def station():
    cnt = 0
    async with websockets.connect(EVCC_OCPP, subprotocols=["ocpp1.6"]) as ws:
        async def send(msg):
            await ws.send(json.dumps(msg))

        # Boot + verfuegbar + Transaktion starten (Autostart-Simulation)
        cnt += 1; await send([2, f"b-{cnt}", "BootNotification",
                              {"chargePointVendor": "SIM", "chargePointModel": "DC"}])
        cnt += 1; await send([2, f"s-{cnt}", "StatusNotification",
                              {"connectorId": 1, "errorCode": "NoError", "status": "Available"}])
        cnt += 1; await send([2, f"st-{cnt}", "StartTransaction",
                              {"connectorId": 1, "idTag": "SIM", "meterStart": 0, "timestamp": now_iso()}])
        cnt += 1; await send([2, f"c-{cnt}", "StatusNotification",
                              {"connectorId": 1, "errorCode": "NoError", "status": "Charging"}])

        async def pump_meter():
            nonlocal cnt
            while True:
                apply_command()
                cnt += 1
                await send(meter_values_msg(cnt))
                await asyncio.sleep(1.0)

        task = asyncio.create_task(pump_meter())

        async for raw in ws:
            msg = json.loads(raw)
            if msg[0] == 2:  # CALL von evcc
                mid, action, payload = msg[1], msg[2], msg[3]
                if action == "SetChargingProfile":
                    try:
                        periods = payload["csChargingProfiles"]["chargingSchedule"]["chargingSchedulePeriod"]
                        unit = payload["csChargingProfiles"]["chargingSchedule"].get("chargingRateUnit", "A")
                        limit = periods[0]["limit"]
                        if unit == "A":
                            state["i_cmd"] = float(limit)
                        else:  # W
                            state["i_cmd"] = float(limit) / state["u_dc"] if state["u_dc"] > 0 else 0
                    except Exception as e:
                        print("WARN parse SetChargingProfile:", e)
                    await send([3, mid, {"status": "Accepted"}])
                elif action == "GetCompositeSchedule":
                    await send([3, mid, {"status": "Rejected"}])
                elif action in ("ChangeConfiguration",):
                    await send([3, mid, {"status": "Accepted"}])
                elif action == "RemoteStartTransaction":
                    await send([3, mid, {"status": "Accepted"}])
                elif action == "TriggerMessage":
                    await send([3, mid, {"status": "Accepted"}])
                else:
                    await send([3, mid, {}])
            # Ergebnisse von der Station-Seite ignorieren wir

async def station_supervisor():
    """Reconnect-Schleife, falls evcc beim Start die Verbindung noch zuruecksetzt."""
    while True:
        try:
            await station()
        except Exception as e:
            print("station reconnect:", e)
            await asyncio.sleep(2)

def start_background():
    threading.Thread(target=run_grid_server, daemon=True).start()
    def runner():
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(station_supervisor())
    threading.Thread(target=runner, daemon=True).start()

if __name__ == "__main__":
    start_background()
    print("sim station + grid server laufen")
    while True:
        time.sleep(1)
        print(f"u_dc={state['u_dc']:.0f}V i_cmd={state['i_cmd']:.1f}A "
              f"P={state['charge_power']/1000:.1f}kW grid={grid_power()/1000:.1f}kW")
