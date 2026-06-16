#!/usr/bin/env python3
"""
Integrationstest fuer die harte Leistungsobergrenze (maxPower) pro Ladepunkt.

Verifiziert end-to-end, dass die gelieferte Ladeleistung NIE ueber den gesetzten
kW-Wert geht — spannungsunabhaengig (gleicher Deckel bei 400 V und 800 V).
"""
import os
import subprocess
import sys
import time
import urllib.request

import sim_station as sim

HERE = os.path.dirname(os.path.abspath(__file__))
EVCC = os.path.join(HERE, "..", "evcc-dc-sim.exe")
API = "http://127.0.0.1:7080"
MAXP = 40000  # harte Obergrenze 40 kW

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}", flush=True)


def config():
    # viel Headroom (Circuit gross), damit nur die harte maxPower-Grenze bindet
    return f"""network: {{schema: http, host: 127.0.0.1, port: 7080}}
log: error
levels: {{lp-1: debug}}
interval: 2s
meters:
  - name: grid
    type: custom
    power: {{source: http, uri: http://127.0.0.1:8099/grid, method: GET}}
chargers:
  - name: dcstation
    type: template
    template: ocpp
    stationid: SIMDC
    connector: 1
    chargingrateunit: A
loadpoints:
  - title: DC Sim
    charger: dcstation
    circuit: main
    mode: now
    chargingType: dc
    dcMaxVoltage: 1000
    minCurrent: 6
    maxCurrent: 250
    maxPower: {MAXP}
circuits:
  - name: main
    meter: grid
    maxPower: 240000
site: {{title: DC Test, meters: {{grid: grid}}}}
"""


def api_state():
    import json
    with urllib.request.urlopen(API + "/api/state", timeout=5) as r:
        return json.load(r)


def api_post(p):
    try:
        urllib.request.urlopen(urllib.request.Request(API + p, method="POST"), timeout=5).read()
    except Exception as e:
        print("WARN", p, e, flush=True)


def wait_api(t=90):
    t0 = time.time()
    while time.time() - t0 < t:
        try:
            api_state(); return True
        except Exception:
            time.sleep(2)
    return False


def measure():
    s = api_state(); lp = s["loadpoints"][0]
    return lp.get("offeredCurrent") or 0, lp.get("chargePower", 0)


def main():
    sim.start_background()
    time.sleep(1)
    cfg = os.path.join(HERE, "_maxpower.yaml")
    open(cfg, "w", encoding="utf-8").write(config())
    proc = subprocess.Popen([EVCC, "--config", cfg],
                            stdout=open(os.path.join(HERE, "maxpower_evcc.log"), "w"),
                            stderr=subprocess.STDOUT)
    try:
        if not wait_api(90):
            print("FATAL: API timeout"); return 1
        time.sleep(10)
        api_post("/api/loadpoints/1/maxcurrent/250")
        time.sleep(4)

        # 400 V: 250 A waeren 100 kW, aber 40 kW Deckel -> ~100 A / 40 kW
        sim.state.update(u_dc=400, car_max_a=250, building=2000, pv=200000)
        time.sleep(16)
        i, p = measure()
        check("400V: Leistung <= 40 kW (+5%)", p <= MAXP * 1.05, f"P={p/1000:.1f}kW offered={i:.0f}A")
        check("400V: nicht voll 250 A (Deckel greift)", i < 130, f"offered={i:.0f}A (~100A erwartet)")

        # 800 V: gleicher Deckel -> ~50 A / 40 kW (halber Strom, gleiche Leistung)
        sim.state.update(u_dc=800)
        time.sleep(16)
        i2, p2 = measure()
        check("800V: Leistung <= 40 kW (+5%)", p2 <= MAXP * 1.05, f"P={p2/1000:.1f}kW offered={i2:.0f}A")
        check("800V: Strom ~halb von 400V (spannungsunabh. Leistung)", i2 < i * 0.65,
              f"i400={i:.0f}A i800={i2:.0f}A")

        passed = sum(1 for _, ok in results if ok)
        print(f"\n=== {passed}/{len(results)} Tests bestanden ===", flush=True)
        return 0 if passed == len(results) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
