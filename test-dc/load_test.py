#!/usr/bin/env python3
"""
Vollautomatisches Lasttestverfahren fuer das DC-Lastmanagement.

Treibt das gepatchte evcc-Binary mit einer simulierten DC-Station (OCPP, plain
Voltage wie die reale inergia) und einem steuerbaren Netzzaehler durch
definierte Szenarien und prueft AUTOMATISCHES und MANUELLES Verhalten:

  AUTO     (maxCurrent = 250 A): Lastmanagement regelt dynamisch auf das
           Netzlimit (118 kW). Volllast bei Headroom, Drosselung bei Ueberlast,
           Wiederhochregeln wenn die Ueberlast verschwindet.

  MANUELL  (maxCurrent = Slider-Wert): die manuelle Obergrenze wird eingehalten,
           ABER das Lastmanagement greift trotzdem ein und drosselt unter den
           manuellen Wert, sobald die Netzleistung das Limit ueberschreitet.

  Zusaetzlich: die DC-Station pausiert nie (haelt min 6 A statt 0 A).

Aufruf:  python load_test.py            (einmal, Exit 0 = alles bestanden)
         python load_test.py --loop     (Dauerschleife mit Statistik)
"""
import os
import subprocess
import sys
import time
import urllib.request

import sim_station as sim

HERE = os.path.dirname(os.path.abspath(__file__))
EVCC = os.path.join(HERE, "..", "evcc-dc-sim.exe")
CONFIG = os.path.join(HERE, "evcc-dc-test.yaml")
API = "http://127.0.0.1:7080"
GRID_LIMIT = 118000  # main circuit maxPower (W), siehe evcc-dc-test.yaml

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}", flush=True)


def api_state():
    import json
    with urllib.request.urlopen(API + "/api/state", timeout=5) as r:
        return json.load(r)


def api_post(path):
    try:
        req = urllib.request.Request(API + path, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
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


def lp():
    return api_state()["loadpoints"][0]


def offered():
    s = api_state()
    return s["loadpoints"][0].get("offeredCurrent") or 0, s["grid"]["power"], s["loadpoints"][0].get("chargePower", 0)


def set_mode(manual, cap=250):
    """Auto = Obergrenze 250 A (LM nutzt vollen Bereich); Manuell = Slider-Wert."""
    api_post("/api/loadpoints/1/maxcurrent/" + str(cap if manual else 250))


def settle(sec=16):
    time.sleep(sec)


def run_procedure():
    # -- AUTO -------------------------------------------------------------
    print("\n# AUTO-Modus (maxCurrent 250, Lastmanagement regelt)")

    print("A1: Headroom satt -> Volllast")
    set_mode(False)
    sim.state.update(u_dc=400, car_max_a=250, building=8000, pv=0)
    settle()
    i, grid, p = offered()
    check("A1 Volllast (>=240 A)", i >= 240, f"offered={i:.0f}A grid={grid/1000:.1f}kW")

    print("A2: Ueberlast -> LM drosselt auf <=118 kW")
    sim.state.update(building=70000)
    settle()
    i, grid, p = offered()
    check("A2 Netz <=118 kW (+3%)", grid <= GRID_LIMIT * 1.03, f"grid={grid/1000:.1f}kW")
    check("A2 gedrosselt (<250 A)", i < 250, f"offered={i:.0f}A")

    print("A3: Ueberlast weg -> LM regelt wieder hoch")
    sim.state.update(building=8000)
    settle()
    i, grid, p = offered()
    check("A3 wieder Volllast (>=240 A)", i >= 240, f"offered={i:.0f}A")

    # -- MANUELL ----------------------------------------------------------
    print("\n# MANUELL-Modus (Slider-Obergrenze, LM greift trotzdem ein)")

    print("M1: Cap 120 A, Headroom -> haelt manuellen Wert")
    set_mode(True, 120)
    sim.state.update(u_dc=400, car_max_a=250, building=8000, pv=0)
    settle()
    i, grid, p = offered()
    check("M1 haelt ~120 A (manuelle Obergrenze)", 112 <= i <= 120, f"offered={i:.0f}A P={p/1000:.1f}kW")

    print("M2: Cap 200 A, aber Ueberlast -> LM drosselt UNTER manuellen Wert")
    set_mode(True, 200)
    sim.state.update(building=70000)
    settle()
    i, grid, p = offered()
    check("M2 LM greift ein (<200 A trotz Cap)", i < 200, f"offered={i:.0f}A")
    check("M2 Netz <=118 kW (+3%)", grid <= GRID_LIMIT * 1.03, f"grid={grid/1000:.1f}kW")

    print("M3: Cap 50 A, viel Headroom -> LM hebt NICHT ueber manuellen Wert")
    set_mode(True, 50)
    sim.state.update(building=0, pv=0)
    settle()
    i, grid, p = offered()
    check("M3 bleibt <=50 A (Cap ist Obergrenze)", i <= 52, f"offered={i:.0f}A")

    # -- NIE PAUSIEREN ----------------------------------------------------
    print("\n# DC kann nicht pausieren (min 6 A statt 0 A)")
    print("N1: unmoegliches Budget -> haelt 6 A, laedt weiter")
    set_mode(True, 100)
    sim.state.update(u_dc=400, car_max_a=250, building=200000, pv=0)
    settle(18)
    i, grid, p = offered()
    check("N1 haelt min 6 A (kein 0 A/Pause)", i >= 6, f"offered={i:.0f}A")
    check("N1 laedt weiter", lp().get("charging", False), f"P={p/1000:.1f}kW")

    # zuruecksetzen auf Auto
    set_mode(False)
    sim.state.update(building=8000)


def one_run():
    sim.start_background()
    time.sleep(1)
    proc = subprocess.Popen(
        [EVCC, "--config", CONFIG],
        stdout=open(os.path.join(HERE, "loadtest_evcc.log"), "w"),
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_api(90):
            print("FATAL: evcc API nicht erreichbar")
            return 1
        settle(10)  # Station verbindet, Transaktion laeuft an
        api_post("/api/loadpoints/1/maxcurrent/250")
        api_post("/api/loadpoints/1/mincurrent/6")
        settle(4)
        run_procedure()
        passed = sum(1 for _, ok in results if ok)
        total = len(results)
        print(f"\n=== {passed}/{total} Tests bestanden ===", flush=True)
        return 0 if passed == total else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def loop():
    log = os.path.join(HERE, "loadtest_results.log")
    runs = passed = 0

    def w(line):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{stamp}  {line}", flush=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{stamp}  {line}\n")

    w("=== Lasttest-Loop gestartet ===")
    while True:
        runs += 1
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "load_test.py")],
                               cwd=HERE, capture_output=True, text=True, timeout=400)
            ok = r.returncode == 0
            summary = next((ln.strip() for ln in r.stdout.splitlines() if "bestanden" in ln), "")
            if ok:
                passed += 1
            else:
                with open(os.path.join(HERE, f"loadtest_fail_{runs}.log"), "w", encoding="utf-8") as f:
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
