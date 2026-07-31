# -*- coding: utf-8 -*-
"""Build a source release from Git-tracked files after privacy checks."""

import argparse
import re
import subprocess
import zipfile
from pathlib import Path


SECRET_PATTERNS = (
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(rb"BEGIN [A-Z ]*PRIVATE KEY"),
)
DENIED_NAMES = {
    ".env",
    "mcp_config.json",
    "p13_last_settings.json",
    "p13_supersheet_config.json",
    "profiles.json",
    "Google_profiles_backup.json",
    "OHM2.json",
    "OHM COCO.xml",
}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def validate_file(path: Path) -> None:
    if path.name in DENIED_NAMES:
        raise RuntimeError("Private runtime file is tracked: {}".format(path))
    data = path.read_bytes()
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            raise RuntimeError("Secret-shaped value found in: {}".format(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized P13 release archive.")
    parser.add_argument("output", type=Path, help="Destination .zip path")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    files = tracked_files(root)
    for path in files:
        validate_file(path)

    output = arguments.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("P13.extension") / path.relative_to(root))
    print("Safe release archive created: {}".format(output))
    print("Included tracked files: {}".format(len(files)))
    print("Git history is not included. Run security_audit.py --release before publishing the repository itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
