#!/usr/bin/env python3
"""
GTA6 AI Studio — Unified Single-Command Launcher
Starts FastAPI (localhost:8000) and React Vite (localhost:5173) together,
monitors startup health, and launches the Studio UI in the default browser.
"""

import os
import sys
import time
import signal
import shutil
import urllib.request
import webbrowser
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

def print_banner():
    banner = r"""
  ╔═══════════════════════════════════════════════════════════════════════╗
  ║                                                                       ║
  ║      ⚡ GTA6 AI STUDIO — NEXT-GEN SHORT-FORM CREATOR ENGINE ⚡       ║
  ║                                                                       ║
  ║   Director: gemini-3.8-flash  │ Voice: gemini-3.8-flash-tts           ║
  ║   Engine:   VideoToolbox (M4) / NVENC (RTX 3050)                      ║
  ║                                                                       ║
  ╚═══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)

def get_python_executable():
    """Detect virtual environment python if present"""
    if sys.platform == "win32":
        venv_py = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = BASE_DIR / ".venv" / "bin" / "python"

    if venv_py.exists():
        return str(venv_py)
    return sys.executable

def get_node_package_manager():
    """Detect pnpm or npm"""
    # Check custom nvm path first if on mac
    nvm_pnpm = Path("/Users/laheri/.nvm/versions/node/v20.20.1/bin/pnpm")
    if nvm_pnpm.exists():
        return str(nvm_pnpm)

    for cmd in ["pnpm", "npm", "yarn"]:
        resolved = shutil.which(cmd)
        if resolved:
            return resolved
    return "npm"

def wait_for_port(url, max_retries=30, delay=0.5):
    """Wait until an HTTP endpoint responds with 200 OK"""
    for _ in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(delay)
    return False

def main():
    print_banner()

    python_bin = get_python_executable()
    pkg_mgr = get_node_package_manager()

    print(f"[*] Python Runtime: {python_bin}")
    print(f"[*] Package Manager: {pkg_mgr}")
    print(f"[*] Workspace Root:  {BASE_DIR}")

    # Ensure dependencies exist
    if not (FRONTEND_DIR / "node_modules").exists():
        print("[*] Installing frontend dependencies...")
        subprocess.run([pkg_mgr, "install"], cwd=str(FRONTEND_DIR), check=True)

    processes = []

    def shutdown(signum=None, frame=None):
        print("\n[*] Shutting down GTA6 AI Studio services...")
        for proc in processes:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                else:
                    proc.send_signal(signal.SIGINT)
            except Exception:
                pass
        time.sleep(1)
        for proc in processes:
            try:
                proc.kill()
            except Exception:
                pass
        print("[✓] Clean shutdown complete. Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        # 1. Start FastAPI Backend
        print("\n[1/2] Launching FastAPI Backend on http://127.0.0.1:8000 ...")
        backend_cmd = [
            python_bin, "-m", "uvicorn",
            "backend.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--reload"
        ]
        backend_proc = subprocess.Popen(
            backend_cmd,
            cwd=str(BASE_DIR),
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        processes.append(backend_proc)

        # 2. Start Vite Frontend
        print("[2/2] Launching React Vite Frontend on http://localhost:5173 ...")
        frontend_cmd = [pkg_mgr, "run", "dev"]
        frontend_proc = subprocess.Popen(
            frontend_cmd,
            cwd=str(FRONTEND_DIR),
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        processes.append(frontend_proc)

        # 3. Wait for services to become healthy
        print("\n[*] Waiting for servers to initialize...")
        backend_online = wait_for_port("http://127.0.0.1:8000/api/health", max_retries=50)
        frontend_online = wait_for_port("http://localhost:5173", max_retries=50)

        if backend_online and frontend_online:
            print("\n" + "=" * 70)
            print("  🟢 GTA6 AI STUDIO IS LIVE!")
            print("  Studio UI: http://localhost:5173")
            print("  API Docs:  http://127.0.0.1:8000/docs")
            print("  Press Ctrl+C at any time to safely stop the servers.")
            print("=" * 70 + "\n")

            # Auto-open browser
            try:
                webbrowser.open("http://localhost:5173")
            except Exception:
                pass

        # Keep main thread alive
        while True:
            time.sleep(1)
            # Check if any subprocess died unexpectedly
            if backend_proc.poll() is not None:
                print("[!] FastAPI backend exited unexpectedly.")
                break
            if frontend_proc.poll() is not None:
                print("[!] React frontend exited unexpectedly.")
                break

    except KeyboardInterrupt:
        shutdown()
    except Exception as e:
        print(f"[!] Error: {e}")
        shutdown()

if __name__ == "__main__":
    main()
