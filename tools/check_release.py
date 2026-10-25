"""Offline source/config checks; does not import or start bot services."""
from pathlib import Path
import ast
import json
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors = []
    counts = {"python": 0, "examples": 0, "powershell": 0}
    skip = {".git", ".venv", "__pycache__", "node_modules", "data", "logs"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in skip for part in path.relative_to(ROOT).parts):
            continue
        try:
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
                counts["python"] += 1
            elif path.suffix == ".ps1":
                if not path.read_bytes().startswith(b"\xef\xbb\xbf"):
                    raise ValueError("PowerShell 5.1 requires UTF-8 BOM")
                counts["powershell"] += 1
            elif ".example." in path.name or path.parent == ROOT / "examples/monitor":
                if path.suffix == ".json":
                    json.loads(path.read_text(encoding="utf-8-sig"))
                elif path.suffix == ".toml":
                    tomllib.loads(path.read_text(encoding="utf-8-sig"))
                else:
                    continue
                counts["examples"] += 1
        except (ValueError, SyntaxError, OSError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    if (ROOT / ".git").exists():
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        for name in result.stdout.decode("utf-8").split("\0"):
            if not name:
                continue
            parts = Path(name).parts
            if (any(p in {"data", "logs", "runtime", "backups", "__pycache__", ".venv"} for p in parts)
                    or name.endswith((".db", ".sqlite3", ".jsonl", ".env", "/config.toml"))
                    or "config/old/" in name.replace("\\", "/")):
                errors.append(f"Runtime/private file tracked: {name}")
    print(json.dumps({"checked": counts, "errors": errors}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
