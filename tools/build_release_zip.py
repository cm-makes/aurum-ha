"""Build aurum.zip, the release asset the Marketplace installs.

hacs.json sets ``zip_release`` and ``filename``, so the Marketplace (and HACS)
downloads this asset from the release and extracts it straight into
``custom_components/aurum/``. The files therefore sit at the root of the ZIP,
not in a folder. The Marketplace shows the asset's download count on the
project page.

Only files tracked by git are packed, so local caches and scratch files never
ship.

    python tools/build_release_zip.py --tag v1.16.2 --out aurum.zip
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = "custom_components/aurum"


def tracked_files(root: Path = ROOT) -> list[str]:
    """Paths of the integration's tracked files, relative to SRC."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", SRC],
        cwd=root, check=True, capture_output=True).stdout
    prefix = SRC + "/"
    return sorted(
        p[len(prefix):] for p in out.decode("utf-8").split("\0")
        if p.startswith(prefix))


def build(out: Path, tag: str | None = None, root: Path = ROOT) -> list[str]:
    """Write the ZIP to ``out`` and return the packed paths."""
    src = root / SRC
    version = json.loads(
        (src / "manifest.json").read_text(encoding="utf-8"))["version"]
    if tag is not None and tag.removeprefix("v") != version:
        raise SystemExit(
            f"Tag {tag} does not match manifest.json version {version}")
    files = tracked_files(root)
    if "manifest.json" not in files:
        raise SystemExit(f"No tracked manifest.json in {SRC}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(src / rel, rel)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("aurum.zip"))
    parser.add_argument(
        "--tag", help="release tag; must match the manifest.json version")
    args = parser.parse_args(argv)
    files = build(args.out, args.tag)
    print(f"{args.out}: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
