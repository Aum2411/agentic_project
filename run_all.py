"""Launcher script to run both FastAPI backend (uvicorn) and Flask frontend

Usage:
    python run_all.py

This script will:
- Start uvicorn programmatically on port 8000
- Start the Flask frontend (frontend/app.py) as a subprocess
- Forward Ctrl+C to gracefully shut down both
"""
import subprocess
import sys
import time
import os
import signal

ROOT = os.path.dirname(__file__)
PY = sys.executable

uvicorn_cmd = [PY, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", ROOT]
frontend_cmd = [PY, os.path.join(ROOT, "frontend", "app.py")]

procs = []

try:
    print("Starting backend: ", " ".join(uvicorn_cmd))
    p1 = subprocess.Popen(uvicorn_cmd, cwd=ROOT)
    procs.append(p1)
    time.sleep(1)
    print("Starting frontend: ", " ".join(frontend_cmd))
    p2 = subprocess.Popen(frontend_cmd, cwd=ROOT)
    procs.append(p2)

    print("Both services started. Press Ctrl+C to stop.")
    # Wait for processes to exit
    while True:
        alive = [p.poll() is None for p in procs]
        if not any(alive):
            break
        time.sleep(0.5)
except KeyboardInterrupt:
    print("Stopping services...")
finally:
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    print("All stopped.")
