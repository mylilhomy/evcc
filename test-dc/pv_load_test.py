#!/usr/bin/env python3
"""
PV-abhaengiges Lasttestverfahren mit mehreren Netzlimits.

Da das Lastmanagement-Limit am NETZzaehler sitzt (grid = Gebaeude + Laden - PV),
schafft PV automatisch Headroom: die erlaubte Ladeleistung steigt um die
PV-Leistung, ohne dass der Netzbezug das Limit ueberschreitet. Die Ladeleistung
kann dadurch das Netzlimit sogar deutlich UEBERSTEIGEN.

Dieses Verfahren faehrt mehrere Netzlimits durch (Neustart je Limit, da Circuits
in der Config definiert sind) und prueft pro Limit mehrere PV-Stufen:
  - Netzbezug bleibt <= Limit (egal wie viel PV)
  - mehr PV => mehr erlaubte Ladeleistung (~ +PV)
  - bei genug PV uebersteigt die Ladeleistung das Netzlimit

Aufruf:  python pv_load_test.py            (einmal)
         python pv_load_test.py --loop     (Dauerschleife)
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

# Netzlimits, die durchgetestet werden (W) - "gegebene" Anschlussszenarien
# 800-V-Fahrzeug: Connector-Max = 250 A * 800 V = 200 kW > alle Limits,
# damit ueber alle Stufen das NETZlimit die bindende Grenze ist (nicht die
# Connector-Hardware). Die spannungsrichtige A<->W-Umrechnung ist separat in
# run_test.py geprueft; hier geht es nur um PV-Headroom am Netzlimit.
LIMITS = [30000, 60000, 118000]
U_DC = 800.0
TOL = 1.05  # 5% Toleranz fuer Netzbezug

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}", flush=True)


def config_for(limit):
    return f"""network:
  schema: http
  host: 127.0.0.1
  port: 7080
log: error
levels:
  lp-1: debug
interval: 2s
meters:
  - name: grid
    type: custom
    power:
      source: http
      uri: http://127.0.0.1:8099/grid
      method: GET
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
circuits:
  - name: main
    meter: grid
    maxPower: {limit}
site:
  title: DC Test
  meters:
    grid: grid
"""


def api_state():
    import json
    with urllib.request.urlopen(API + "/api/state", timeout=5) as r:
        return json.load(r)


def api_post(path):
    try:
        urllib.request.urlopen(urllib.request.Request(API + path, method="POST"), timeout=5).read()
    except Exception as e:
        print("WARN api_post", path, e, flush=True)


def wait_api(timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            api_state()
            return True
        except Exception:
            time.sleep(2)
    return False


def measure():
    s = api_state()
    lp = s["loadpoints"][0]
    return lp.get("offeredCurrent") or 0, s["grid"]["power"], lp.get("chargePower", 0)


def run_limit(limit):
    """startet evcc mit gegebenem Netzlimit und prueft PV-Stufen."""
    cfgpath = os.path.join(HERE, "_pv_limit.yaml")
    open(cfgpath, "w", encoding="utf-8").write(config_for(limit))

    proc = subprocess.Popen(
        [EVCC, "--config", cfgpath],
        stdout=open(os.path.join(HERE, "pvtest_evcc.log"), "w"),
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_api(90):
            check(f"{limit//1000}kW: evcc startet", False, "API timeout")
            return
        time.sleep(10)  # Station verbindet + Transaktion
        api_post("/api/loadpoints/1/maxcurrent/250")
        api_post("/api/loadpoints/1/mincurrent/6")
        time.sleep(4)

        building = 5000
        kw = limit // 1000
        print(f"\n# Netzlimit {kw} kW (Gebaeude 5 kW, U_dc 800 V)")

        # PV = 0
        sim.state.update(u_dc=U_DC, car_max_a=250, building=building, pv=0)
        time.sleep(16)
        i0, grid0, p0 = measure()
        check(f"{kw}kW PV=0: Netz <= Limit", grid0 <= limit * TOL,
              f"grid={grid0/1000:.1f}kW charge={p0/1000:.1f}kW")

        # PV = 30 kW
        sim.state.update(pv=30000)
        time.sleep(16)
        i1, grid1, p1 = measure()
        check(f"{kw}kW PV=30: Netz <= Limit", grid1 <= limit * TOL,
              f"grid={grid1/1000:.1f}kW charge={p1/1000:.1f}kW")
        check(f"{kw}kW PV=30: mehr Ladeleistung (~+PV)", p1 > p0 + 20000,
              f"charge {p0/1000:.1f} -> {p1/1000:.1f} kW (+{(p1-p0)/1000:.1f})")

        # PV hoch genug, dass Ladeleistung das Netzlimit uebersteigt
        sim.state.update(pv=60000)
        time.sleep(16)
        i2, grid2, p2 = measure()
        check(f"{kw}kW PV=60: Netz <= Limit", grid2 <= limit * TOL,
              f"grid={grid2/1000:.1f}kW")
        check(f"{kw}kW PV=60: Ladeleistung > Netzlimit (PV traegt)", p2 > limit,
              f"charge={p2/1000:.1f}kW > limit {kw}kW")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        time.sleep(2)


def one_run():
    sim.start_background()
    time.sleep(1)
    for limit in LIMITS:
        run_limit(limit)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n=== {passed}/{total} Tests bestanden ===", flush=True)
    return 0 if passed == total else 1


def loop():
    log = os.path.join(HERE, "pvtest_results.log")
    runs = passed = 0

    def w(line):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{stamp}  {line}", flush=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{stamp}  {line}\n")

    w("=== PV-Lasttest-Loop gestartet ===")
    while True:
        runs += 1
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "pv_load_test.py")],
                               cwd=HERE, capture_output=True, text=True, timeout=600)
            ok = r.returncode == 0
            summary = next((ln.strip() for ln in r.stdout.splitlines() if "bestanden" in ln), "")
            if ok:
                passed += 1
            else:
                with open(os.path.join(HERE, f"pvtest_fail_{runs}.log"), "w", encoding="utf-8") as f:
                    f.write(r.stdout + "\n---STDERR---\n" + r.stderr)
            w(f"Lauf {runs}: {'OK ' if ok else 'FAIL'}  {summary}  ({time.time()-t0:.0f}s)  [gesamt {passed}/{runs}]")
        except subprocess.TimeoutExpired:
            w(f"Lauf {runs}: TIMEOUT  [gesamt {passed}/{runs}]")
        time.sleep(5)


if __name__ == "__main__":
    if "--loop" in sys.argv:
        loop()
    else:
        sys.exit(one_run())
