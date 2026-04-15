"""
stoa_watchdog.py - Monitora e reinicia processos STOA automaticamente
Roda em background, verifica a cada 60s se backend e agente estao vivos.
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DIR = Path(__file__).parent.resolve()
BACKEND_CHECK_URL = "http://localhost:8000/api/health"
CHECK_INTERVAL = 60

BACKEND_CMD = [sys.executable, str(DIR / "main.py")]
AGENT_CMD = [sys.executable, str(DIR / "stoa_device_agent_windows.py"), "--server", "http://localhost:8000"]
LOG_DIR = DIR / "logs"

_procs: dict[str, subprocess.Popen] = {}


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [watchdog] {msg}", flush=True)


def backend_alive() -> bool:
    try:
        with urllib.request.urlopen(BACKEND_CHECK_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def proc_alive(key: str) -> bool:
    p = _procs.get(key)
    return p is not None and p.poll() is None


def start_backend() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    log("Iniciando backend...")
    _procs["backend"] = subprocess.Popen(
        BACKEND_CMD,
        stdout=open(LOG_DIR / "backend.log", "a"),
        stderr=subprocess.STDOUT,
        cwd=DIR,
    )
    for _ in range(20):
        time.sleep(2)
        if backend_alive():
            log("Backend online.")
            return
    log("AVISO: backend demorou para responder.")


def start_agent() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    log("Iniciando agente Windows...")
    _procs["agent"] = subprocess.Popen(
        AGENT_CMD,
        stdout=open(LOG_DIR / "agent.log", "a"),
        stderr=subprocess.STDOUT,
        cwd=DIR,
    )
    log("Agente iniciado.")


def main() -> None:
    log("Watchdog iniciado.")

    if not backend_alive():
        start_backend()
    else:
        log("Backend ja estava rodando.")

    time.sleep(5)
    start_agent()

    while True:
        time.sleep(CHECK_INTERVAL)

        if not backend_alive():
            log("Backend nao respondeu. Reiniciando...")
            if proc_alive("backend"):
                _procs["backend"].kill()
            start_backend()

        if not proc_alive("agent"):
            log("Agente encerrado. Reiniciando...")
            start_agent()


if __name__ == "__main__":
    main()
