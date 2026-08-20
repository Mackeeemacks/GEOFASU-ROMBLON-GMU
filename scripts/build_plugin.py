# -*- coding: utf-8 -*-

from pathlib import Path
import configparser
import sys
import zipfile


ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "geofasu"
DIST_DIR = ROOT / "dist"

PLUGIN_ZIP_NAME = "geofasu.zip"

# These are the compiled sensitive modules after they have been renamed
# from .pyd to .bin for packaging.
REQUIRED_NATIVE_PAYLOADS = {
    "csdbe_merge.cp312-win_amd64.bin",
    "csdbe_export.cp312-win_amd64.bin",
}

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
        PLUGIN_DIR / "scripts" / "sensitive_loader.py",
    ]

    missing = [
        path
        for path in required_files
        if not path.is_file()
    ]

    if missing:
        raise RuntimeError(
            "Required plugin files are missing:\n\n"
            + "\n".join(
                str(path)
                for path in missing
            )
        )


def validate_metadata_version(version: str):
    if not version:
        raise RuntimeError(
            "Plugin version cannot be blank."
        )

    print(f"Plugin version : {version}")
    print("Plugin ID      : geofasu")
    print(f"Release ZIP    : {PLUGIN_ZIP_NAME}")


def validate_no_runtime_pyd():
    """
    Production plugin packages must never directly contain .pyd files.

    Loaded .pyd files can remain locked by Windows while QGIS is running,
    which prevents Plugin Manager from replacing the plugin folder during
    an upgrade.

    Native modules are instead distributed as native/*.bin and copied to
    %LOCALAPPDATA% at runtime by sensitive_loader.py.
    """
    pyd_files = sorted(
        PLUGIN_DIR.rglob("*.pyd")
    )

    if pyd_files:
        raise RuntimeError(
            "Production plugin contains directly loadable .pyd files.\n\n"
            "These files can block QGIS in-place upgrades on Windows:\n\n"
            + "\n".join(
                str(path)
                for path in pyd_files
            )
            + "\n\n"
            "Rename/copy the compiled sensitive modules to:\n"
            "geofasu\\native\\*.bin\n\n"
            "Then remove the .pyd files from the plugin tree before building."
        )


def validate_native_payloads():
    native_dir = PLUGIN_DIR / "native"

    if not native_dir.is_dir():
        raise RuntimeError(
            "Native payload directory is missing:\n\n"
            f"{native_dir}"
        )

    missing = []

    for filename in sorted(
        REQUIRED_NATIVE_PAYLOADS
    ):
        path = native_dir / filename

        if not path.is_file():
            missing.append(path)

    if missing:
        raise RuntimeError(
            "Required protected native payloads are missing:\n\n"
            + "\n".join(
                str(path)
                for path in missing
            )
        )

    for filename in sorted(
        REQUIRED_NATIVE_PAYLOADS
    ):
        path = native_dir / filename

        if path.stat().st_size <= 0:
            raise RuntimeError(
                "Native payload is empty:\n\n"
                f"{path}"
            )


def validate_native_payload_names():
    """
    Reject unexpected directly loadable binaries in native/.
    """
    native_dir = PLUGIN_DIR / "native"

    if not native_dir.is_dir():
        return

    bad_extensions = {
        ".pyd",
        ".dll",
    }

    bad_files = [
        path
        for path in native_dir.rglob("*")
        if (
            path.is_file()
            and path.suffix.casefold()
            in bad_extensions
        )
    ]

    if bad_files:
        raise RuntimeError(
            "Native directory contains directly loadable binaries:\n\n"
            + "\n".join(
                str(path)
                for path in bad_files
            )
            + "\n\n"
            "Production native payloads must be stored as .bin files."
        )


def validate_sensitive_sources():
    """
    Optional protection check.

    Prevent accidental shipping of sensitive Python source versions if the
    protected implementation is supposed to exist only as compiled payloads.
    """
    forbidden_sources = [
        PLUGIN_DIR / "scripts" / "csdbe_merge.py",
        PLUGIN_DIR / "scripts" / "csdbe_export.py",
    ]

    present = [
        path
        for path in forbidden_sources
        if path.is_file()
    ]

    if present:
        raise RuntimeError(
            "Sensitive Python source files are still present in the "
            "production plugin tree:\n\n"
            + "\n".join(
                str(path)
                for path in present
            )
            + "\n\n"
            "Remove them before building the production package."
        )


def validate_source_tree():
    validate_plugin()
    validate_no_runtime_pyd()
    validate_native_payloads()
    validate_native_payload_names()
    validate_sensitive_sources()


def build_zip() -> Path:
    validate_source_tree()

    version = read_version()

    validate_metadata_version(
        version
    )

    DIST_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = (
        DIST_DIR
        / PLUGIN_ZIP_NAME
    )

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

            if not should_include(
                file_path
            ):
                continue

            archive_name = (
                Path("geofasu")
                / file_path.relative_to(
                    PLUGIN_DIR
                )
            )

            archive.write(
                file_path,
                archive_name.as_posix(),
            )

    validate_zip(
        output
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
    print("    ├── native/")
    print("    │   ├── csdbe_merge.cp312-win_amd64.bin")
    print("    │   └── csdbe_export.cp312-win_amd64.bin")
    print("    └── scripts/")
    print("        └── sensitive_loader.py")
    print()

    return output


def validate_zip(output: Path):
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
            "geofasu/scripts/sensitive_loader.py",
        }

        for payload_name in (
            REQUIRED_NATIVE_PAYLOADS
        ):
            required_members.add(
                f"geofasu/native/{payload_name}"
            )

        missing_members = (
            required_members
            - members
        )

        if missing_members:
            raise RuntimeError(
                "ZIP is missing required plugin files:\n\n"
                + "\n".join(
                    sorted(
                        missing_members
                    )
                )
            )

        if "metadata.txt" in members:
            raise RuntimeError(
                "Invalid ZIP structure.\n\n"
                "metadata.txt must be inside:\n"
                "geofasu/metadata.txt"
            )

        pyd_members = [
            name
            for name in members
            if name.casefold().endswith(
                ".pyd"
            )
        ]

        if pyd_members:
            raise RuntimeError(
                "ZIP contains .pyd files that may block upgrades:\n\n"
                + "\n".join(
                    sorted(
                        pyd_members
                    )
                )
            )

        sensitive_sources = {
            "geofasu/scripts/csdbe_merge.py",
            "geofasu/scripts/csdbe_export.py",
        }

        leaked_sources = (
            sensitive_sources
            & members
        )

        if leaked_sources:
            raise RuntimeError(
                "ZIP contains sensitive Python source files:\n\n"
                + "\n".join(
                    sorted(
                        leaked_sources
                    )
                )
            )

        top_level = {
            name.split("/", 1)[0]
            for name in members
            if name
        }

        if top_level != {"geofasu"}:
            raise RuntimeError(
                "ZIP contains invalid top-level folders:\n\n"
                + "\n".join(
                    sorted(
                        top_level
                    )
                )
            )


if __name__ == "__main__":
    try:
        build_zip()

    except Exception as exc:
        print(
            f"\nBUILD FAILED:\n{exc}",
            file=sys.stderr,
        )
        raise