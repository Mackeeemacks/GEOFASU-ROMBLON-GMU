# -*- coding: utf-8 -*-

from pathlib import Path
import configparser
import sys
import zipfile


ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "geofasu"
DIST_DIR = ROOT / "dist"

EXCLUDED_DIRS = {
    "__pycache__",
    ".git",
    ".github",
    "build",
    "dist",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".log",
}


def read_version() -> str:
    metadata = PLUGIN_DIR / "metadata.txt"

    if not metadata.is_file():
        raise FileNotFoundError(
            f"metadata.txt not found: {metadata}"
        )

    config = configparser.ConfigParser()
    config.read(metadata, encoding="utf-8")

    version = config.get(
        "general",
        "version",
        fallback="",
    ).strip()

    if not version:
        raise RuntimeError(
            "Plugin version is missing from metadata.txt."
        )

    return version


def should_include(path: Path) -> bool:
    relative = path.relative_to(PLUGIN_DIR)

    if any(
        part in EXCLUDED_DIRS
        for part in relative.parts
    ):
        return False

    if path.suffix.casefold() in EXCLUDED_SUFFIXES:
        return False

    return True


def validate_plugin():
    required = [
        PLUGIN_DIR / "__init__.py",
        PLUGIN_DIR / "metadata.txt",
        PLUGIN_DIR / "geofasu.py",
    ]

    missing = [
        str(path)
        for path in required
        if not path.is_file()
    ]

    if missing:
        raise RuntimeError(
            "Required plugin files are missing:\n"
            + "\n".join(missing)
        )


def build_zip() -> Path:
    validate_plugin()

    version = read_version()

    DIST_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = DIST_DIR / f"geofasu-{version}.zip"

    if output.exists():
        output.unlink()

    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:

        for file_path in sorted(
            PLUGIN_DIR.rglob("*")
        ):
            if not file_path.is_file():
                continue

            if not should_include(file_path):
                continue

            archive_name = (
                Path("geofasu")
                / file_path.relative_to(PLUGIN_DIR)
            )

            archive.write(
                file_path,
                archive_name.as_posix(),
            )

    with zipfile.ZipFile(output, "r") as archive:
        bad_file = archive.testzip()

        if bad_file is not None:
            raise RuntimeError(
                f"ZIP integrity check failed: {bad_file}"
            )

        names = set(archive.namelist())

        required_members = {
            "geofasu/__init__.py",
            "geofasu/metadata.txt",
            "geofasu/geofasu.py",
        }

        missing_members = required_members - names

        if missing_members:
            raise RuntimeError(
                "ZIP is missing required members:\n"
                + "\n".join(sorted(missing_members))
            )

    print(f"Created: {output}")

    return output


if __name__ == "__main__":
    try:
        build_zip()

    except Exception as exc:
        print(
            f"BUILD FAILED: {exc}",
            file=sys.stderr,
        )
        raise