#!/usr/bin/env python3
"""
Ueber-Nacht-Loop: fuehrt run_test.py wiederholt aus und protokolliert jedes
Ergebnis mit Zeitstempel. Bricht NICHT bei einem einzelnen Fehlschlag ab,
sondern sammelt eine Statistik (Flakiness/Stabilitaet ueber viele Laeufe).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "loop_results.log")

def log(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = f"{stamp}  {line}"
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def main():
    runs = passed = 0
    log("=== Loop-Test gestartet ===")
    while True:
        runs += 1
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, os.path.join(HERE, "run_test.py")],
                               cwd=HERE, capture_output=True, text=True, timeout=300)
            ok = r.returncode == 0
            # letzte Ergebniszeile extrahieren
            summary = ""
            for ln in r.stdout.splitlines():
                if "Tests bestanden" in ln:
                    summary = ln.strip()
            if ok:
                passed += 1
            log(f"Lauf {runs}: {'OK ' if ok else 'FAIL'}  {summary}  ({time.time()-t0:.0f}s)  "
                f"[gesamt {passed}/{runs}]")
            if not ok:
                # Fehlerdetails sichern
                fail_log = os.path.join(HERE, f"fail_{runs}.log")
                with open(fail_log, "w", encoding="utf-8") as f:
                    f.write(r.stdout + "\n---STDERR---\n" + r.stderr)
                log(f"  Details: {fail_log}")
        except subprocess.TimeoutExpired:
            log(f"Lauf {runs}: TIMEOUT (>300s)  [gesamt {passed}/{runs}]")
        except Exception as e:
            log(f"Lauf {runs}: EXCEPTION {e}  [gesamt {passed}/{runs}]")
        time.sleep(5)

if __name__ == "__main__":
    main()
