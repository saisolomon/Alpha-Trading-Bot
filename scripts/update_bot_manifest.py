"""
Add an EA to the bot manifest so BotOrchestrator auto-deploys it on
next poll cycle.

Used by Claude as part of "ship a new EA" deploy steps:
    uv run python scripts/update_bot_manifest.py US500_MeanRev
    uv run python scripts/update_bot_manifest.py --remove FTMOBot

After running this, push the manifest to MT5's MQL5/Files/ dir (the
orchestrator polls every 60s).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_REPO = REPO_ROOT / "mql5" / "bot_manifest.txt"
# Default MT5 terminal dir on this Windows machine -- may need adjustment.
MT5_TERMINAL = Path(
    r"C:\Users\saisolomon\AppData\Roaming\MetaQuotes\Terminal"
    r"\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Files"
)


def read_lines(p: Path) -> list[str]:
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8").splitlines()


def write_lines(p: Path, lines: list[str]) -> None:
    p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_active_entries(lines: list[str]) -> list[str]:
    """Return the existing EA names (non-comment, non-blank)."""
    out = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Update bot_manifest.txt")
    p.add_argument("ea_name", help="EA name without extension (e.g. US500_MeanRev)")
    p.add_argument("--remove", action="store_true", help="remove EA from manifest instead of adding")
    p.add_argument("--mt5-dir", type=Path, default=MT5_TERMINAL,
                   help="MT5 MQL5/Files dir to also copy to (default = saisolomon's)")
    args = p.parse_args()

    lines = read_lines(MANIFEST_REPO)
    active = parse_active_entries(lines)

    if args.remove:
        if args.ea_name not in active:
            print(f"  '{args.ea_name}' not in manifest -- nothing to remove")
            sys.exit(0)
        new_lines = [l for l in lines if l.strip() != args.ea_name]
        write_lines(MANIFEST_REPO, new_lines)
        print(f"  removed '{args.ea_name}' from {MANIFEST_REPO.name}")
    else:
        if args.ea_name in active:
            print(f"  '{args.ea_name}' already in manifest -- no change")
            sys.exit(0)
        # Append, preserving any trailing comments/structure
        write_lines(MANIFEST_REPO, lines + [args.ea_name])
        print(f"  appended '{args.ea_name}' to {MANIFEST_REPO.name}")

    # Mirror to MT5 dir if it exists
    if args.mt5_dir.exists():
        dest = args.mt5_dir / "bot_manifest.txt"
        shutil.copy(MANIFEST_REPO, dest)
        print(f"  mirrored to {dest}")
    else:
        print(f"  WARN: {args.mt5_dir} not found; manifest not copied to MT5")
        print(f"        copy manually: cp {MANIFEST_REPO} <MT5_TERMINAL>/MQL5/Files/")


if __name__ == "__main__":
    main()
