"""Initialize example configs without overwriting user settings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
JOBS = [
    ("qq-monitor/config/config.win.example.json", "qq-monitor/config/config.win.json"),
    *[(f"examples/monitor/{name}.json", f"qq-monitor/config/{name}.json")
      for name in ("keyword_reply", "diary", "memory_keeper", "sing_groups")],
]


def validate(path: Path) -> None:
    if path.suffix == ".json":
        json.loads(path.read_text(encoding="utf-8-sig"))
    elif path.suffix == ".toml":
        import tomllib
        tomllib.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate existing configs and examples without writing files")
    parser.add_argument("--with-bot", action="store_true", help="Also initialize MaiBot example configs where provided")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required; Python 3.12 is recommended.")
    jobs = list(JOBS)
    if args.with_bot:
        bot = ROOT / "bot/MaiBotOneKey/modules/MaiBot"
        for example in (bot / "config").glob("*.example.toml"):
            jobs.append((str(example.relative_to(ROOT)), str(example.with_name(example.name.replace(".example", "")).relative_to(ROOT))))
        for example in (bot / "plugins").glob("*/config.example.toml"):
            jobs.append((str(example.relative_to(ROOT)), str(example.with_name("config.toml").relative_to(ROOT))))
    errors = []
    for source_rel, target_rel in jobs:
        source, target = ROOT / source_rel, ROOT / target_rel
        try:
            if not source.is_file():
                raise FileNotFoundError(f"Missing example: {source_rel}")
            validate(source)
            if target.exists():
                validate(target)
                print(f"KEEP {target_rel}")
            elif args.check:
                print(f"READY {source_rel} -> {target_rel}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation also prevents an accidental overwrite in a race.
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                print(f"CREATE {target_rel}")
        except (OSError, ValueError) as exc:
            errors.append(f"{source_rel}: {exc}")
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print("Examples checked." if args.check else "Configs initialized. Fill in your own QQ/OneBot/model settings before starting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
