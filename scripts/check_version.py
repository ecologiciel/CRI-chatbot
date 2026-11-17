"""Fail CI when release identifiers drift from the repository VERSION file."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CHECKED_FILES = {
    ROOT / "backend" / "pyproject.toml": f'version = "{VERSION}"',
    ROOT / "backend" / "app" / "main.py": f'version="{VERSION}"',
    ROOT / "backend" / "app" / "api" / "v1" / "health.py": f'version: str = "{VERSION}"',
    ROOT / "frontend" / "package.json": f'"version": "{VERSION}"',
    ROOT / ".env.prod.example": f"VERSION={VERSION}",
    ROOT / "README.md": f"{VERSION}",
}


def main() -> None:
    mismatches = [
        str(path.relative_to(ROOT))
        for path, expected in CHECKED_FILES.items()
        if expected not in path.read_text(encoding="utf-8")
    ]
    if mismatches:
        raise SystemExit(f"Release version mismatch in: {', '.join(mismatches)}")
    print(f"Version {VERSION} is consistent.")


if __name__ == "__main__":
    main()
