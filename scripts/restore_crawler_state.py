"""Restore only dated operational state from the existing reports checkout.

HTML is deliberately not restored: stale pages must never masquerade as this run's
output. No network access, credentials, or publication is performed here.
"""

import argparse
import os
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

STATE_DIRS = {
    "news": ".db",
    "rss": ".db",
    "search": ".db",
    "economic_analysis": ".json",
    "economic_snapshots": ".json",
}


def restore_state(
    source: Path, target: Path, today: date, retention_days: int = 30,
    directories: dict[str, str] | None = None,
) -> int:
    """Copy today's databases and recent dated state, ignoring links and other files."""
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    restored = 0
    for directory, suffix in (directories if directories is not None else STATE_DIRS).items():
        source_dir = source / directory
        if source_dir.is_symlink() or not source_dir.is_dir():
            continue
        for item in sorted(source_dir.glob(f"*{suffix}")):
            if item.is_symlink() or not item.is_file():
                continue
            try:
                day = date.fromisoformat(item.stem)
            except ValueError:
                continue
            if not 0 <= (today - day).days <= retention_days:
                continue
            destination_dir = target / directory
            destination_dir.mkdir(parents=True, exist_ok=True)
            # Replace atomically; no partially copied DB if the job is interrupted.
            fd, temporary = tempfile.mkstemp(dir=destination_dir, prefix=".restore-")
            os.close(fd)
            try:
                shutil.copyfile(item, temporary)
                os.replace(temporary, destination_dir / item.name)
                restored += 1
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return restored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    timezone = config.get("app", {}).get("timezone", "Asia/Shanghai")
    today = datetime.now(ZoneInfo(timezone)).date()
    output = Path(config.get("storage", {}).get("local", {}).get("data_dir", "output"))
    retention = max(30, int(config.get("economic_analysis", {}).get("snapshot_retention_days", 30)))
    count = restore_state(args.source, output, today, retention,
                          {name: suffix for name, suffix in STATE_DIRS.items() if suffix == ".db"})
    # Economic stores currently use output/ independently of storage.local.data_dir.
    count += restore_state(args.source, Path("output"), today, retention,
                           {name: suffix for name, suffix in STATE_DIRS.items() if suffix == ".json"})
    message = f"State restored: {count} dated files (through {today}, timezone {timezone}); HTML not restored"
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"- {message}\n")


if __name__ == "__main__":
    main()
