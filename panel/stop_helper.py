"""Stop services managed by the portable stack only."""
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    raise SystemExit(subprocess.call([sys.executable, str(root / "tools" / "stack.py"), "stop"]))
