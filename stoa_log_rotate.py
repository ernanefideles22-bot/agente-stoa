"""
stoa_log_rotate.py - Remove logs com mais de 7 dias
Chamado pelo start_stoa.bat antes de subir os servicos.
"""
import time
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
MAX_AGE_DAYS = 7


def rotate() -> None:
    if not LOG_DIR.exists():
        return
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    for f in LOG_DIR.glob("*.log"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            print(f"[log_rotate] Removido: {f.name}")


if __name__ == "__main__":
    rotate()
