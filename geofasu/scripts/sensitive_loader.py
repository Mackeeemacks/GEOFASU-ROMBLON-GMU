# -*- coding: utf-8 -*-

from pathlib import Path
import configparser
import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
NATIVE_PAYLOAD_DIR = PLUGIN_ROOT / "native"

CACHE_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    / "GEOFASU"
    / "native"
)


def _plugin_version():
    metadata = PLUGIN_ROOT / "metadata.txt"

    config = configparser.ConfigParser()
    config.read(metadata, encoding="utf-8")

    return config.get(
        "general",
        "version",
        fallback="unknown",
    ).strip()


def _runtime_tag():
    return (
        f"cp{sys.version_info.major}"
        f"{sys.version_info.minor}-win_amd64"
    )


def _sha256(path):
    digest = hashlib.sha256()

    with open(path, "rb") as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _copy_if_changed(source, destination):
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destination.is_file():
        try:
            if _sha256(source) == _sha256(destination):
                return
        except OSError:
            pass

    temporary = destination.with_suffix(
        destination.suffix + ".tmp"
    )

    shutil.copy2(
        source,
        temporary,
    )

    os.replace(
        temporary,
        destination,
    )


def _cleanup_old_versions(current_version):
    """
    Delete cached versions which are not currently in use.

    A DLL from the previous running QGIS session is unlocked after restart,
    so stale versions can normally be removed on the next launch.
    """
    if not CACHE_ROOT.exists():
        return

    for item in CACHE_ROOT.iterdir():
        if not item.is_dir():
            continue

        if item.name == current_version:
            continue

        try:
            shutil.rmtree(item)
        except OSError:
            # It may still be locked by another running QGIS instance.
            # Leave it for a later startup.
            pass


def _prepare_native_module(module_name):
    version = _plugin_version()
    runtime_tag = _runtime_tag()

    _cleanup_old_versions(version)

    payload_name = (
        f"{module_name}.{runtime_tag}.bin"
    )

    runtime_name = (
        f"{module_name}.{runtime_tag}.pyd"
    )

    payload = (
        NATIVE_PAYLOAD_DIR
        / payload_name
    )

    if not payload.is_file():
        raise FileNotFoundError(
            "GEOFASU protected native module is missing.\n\n"
            f"Expected:\n{payload}"
        )

    runtime_folder = (
        CACHE_ROOT
        / version
        / runtime_tag
    )

    runtime_file = (
        runtime_folder
        / runtime_name
    )

    _copy_if_changed(
        payload,
        runtime_file,
    )

    return runtime_file


def _load_extension(module_name):
    """
    Load a compiled Python extension from the runtime cache.

    The extension's final component must remain the original module name
    because the binary exports PyInit_<module_name>.
    """
    runtime_file = _prepare_native_module(
        module_name
    )

    private_package = (
        f"_geofasu_native_{module_name}"
    )

    spec = importlib.util.spec_from_file_location(
        module_name,
        str(runtime_file),
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Could not create loader for {runtime_file}"
        )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return module


_merge_module = None
_export_module = None


def get_csdbe_merge_module():
    global _merge_module

    if _merge_module is None:
        _merge_module = _load_extension(
            "csdbe_merge"
        )

    return _merge_module


def get_csdbe_export_module():
    global _export_module

    if _export_module is None:
        _export_module = _load_extension(
            "csdbe_export"
        )

    return _export_module