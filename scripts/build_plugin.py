# -*- coding: utf-8 -*-

from pathlib import Path
import configparser
import sys
import zipfile


ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "geofasu"
DIST_DIR = ROOT / "dist"

# IMPORTANT:
# QGIS determines the repository plugin ID from the portion of
# <file_name> before the FIRST period.
#
# Therefore:
#
#     geofasu-2.0.6.zip -> plugin ID "geofasu-2"   WRONG
#     geofasu.zip       -> plugin ID "geofasu"     CORRECT
#
PLUGIN_ZIP_NAME = "geofasu.zip"


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
    metadata_path = PLUGIN_DIR / "metadata.txt"

    if not metadata_path.is_file():
        raise FileNotFoundError(
            f"metadata.txt not found:\n{metadata_path}"
        )

    config = configparser.ConfigParser()
    config.read(
        metadata_path,
        encoding="utf-8",
    )

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
    required_files = [
        PLUGIN_DIR / "__init__.py",
        PLUGIN_DIR / "metadata.txt",
        PLUGIN_DIR / "geofasu.py",
    ]

    missing = [
        path
        for path in required_files
        if not path.is_file()
    ]

    if missing:
        raise RuntimeError(
            "Required plugin files are missing:\n\n"
            + "\n".join(str(path) for path in missing)
        )


def validate_metadata_version(version: str):
    if not version:
        raise RuntimeError(
            "Plugin version cannot be blank."
        )

    print(f"Plugin version : {version}")
    print(f"Plugin ID      : geofasu")
    print(f"Release ZIP    : {PLUGIN_ZIP_NAME}")


def build_zip() -> Path:
    validate_plugin()

    version = read_version()
    validate_metadata_version(version)

    DIST_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = DIST_DIR / PLUGIN_ZIP_NAME

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

            # CRITICAL:
            # The ZIP must contain one top-level folder named exactly:
            #
            #     geofasu/
            #
            archive_name = (
                Path("geofasu")
                / file_path.relative_to(PLUGIN_DIR)
            )

            archive.write(
                file_path,
                archive_name.as_posix(),
            )

    # ---------------------------------------------------------
    # Validate ZIP
    # ---------------------------------------------------------

    with zipfile.ZipFile(
        output,
        "r",
    ) as archive:

        bad_file = archive.testzip()

        if bad_file is not None:
            raise RuntimeError(
                "ZIP integrity check failed:\n"
                f"{bad_file}"
            )

        members = set(
            archive.namelist()
        )

        required_members = {
            "geofasu/__init__.py",
            "geofasu/metadata.txt",
            "geofasu/geofasu.py",
        }

        missing_members = (
            required_members - members
        )

        if missing_members:
            raise RuntimeError(
                "ZIP is missing required plugin files:\n\n"
                + "\n".join(
                    sorted(missing_members)
                )
            )

        # Make sure metadata isn't accidentally at ZIP root.
        if "metadata.txt" in members:
            raise RuntimeError(
                "Invalid ZIP structure.\n\n"
                "metadata.txt must be inside:\n"
                "geofasu/metadata.txt"
            )

    print()
    print("=" * 70)
    print("GEOFASU PLUGIN BUILD COMPLETE")
    print("=" * 70)
    print(f"Version : {version}")
    print(f"ZIP     : {output}")
    print()
    print("Expected ZIP structure:")
    print()
    print("geofasu.zip")
    print("└── geofasu/")
    print("    ├── __init__.py")
    print("    ├── metadata.txt")
    print("    ├── geofasu.py")
    print("    └── ...")
    print()

    return output


if __name__ == "__main__":
    try:
        build_zip()

    except Exception as exc:
        print(
            f"\nBUILD FAILED:\n{exc}",
            file=sys.stderr,
        )
        raise