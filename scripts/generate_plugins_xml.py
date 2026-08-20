# -*- coding: utf-8 -*-

from pathlib import Path
import configparser
import html
import sys


ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = ROOT / "geofasu"
DIST_DIR = ROOT / "dist"

OWNER = "Mackeeemacks"
REPOSITORY = "GEOFASU-ROMBLON-GMU"


def metadata_value(config, key, default=""):
    return config.get(
        "general",
        key,
        fallback=default,
    ).strip()


def xml_escape(value: str) -> str:
    return html.escape(
        str(value or ""),
        quote=True,
    )


def generate_plugins_xml() -> Path:
    metadata_path = PLUGIN_DIR / "metadata.txt"

    if not metadata_path.is_file():
        raise FileNotFoundError(
            f"metadata.txt not found: {metadata_path}"
        )

    config = configparser.ConfigParser()
    config.read(
        metadata_path,
        encoding="utf-8",
    )

    version = metadata_value(
        config,
        "version",
    )

    if not version:
        raise RuntimeError(
            "metadata.txt has no version."
        )

    name = metadata_value(
        config,
        "name",
        "GEOFASU",
    )

    description = metadata_value(
        config,
        "description",
    )

    about = metadata_value(
        config,
        "about",
    )

    author = metadata_value(
        config,
        "author",
    )

    email = metadata_value(
        config,
        "email",
    )

    homepage = metadata_value(
        config,
        "homepage",
    )

    tracker = metadata_value(
        config,
        "tracker",
    )

    repository = metadata_value(
        config,
        "repository",
    )

    qgis_min = metadata_value(
        config,
        "qgisMinimumVersion",
        "3.40",
    )

    qgis_max = metadata_value(
        config,
        "qgisMaximumVersion",
        "3.40.99",
    )

    tags = metadata_value(
        config,
        "tags",
    )

    category = metadata_value(
        config,
        "category",
        "Vector",
    )

    zip_name = f"geofasu.zip"

    download_url = (
        f"https://github.com/"
        f"{OWNER}/{REPOSITORY}"
        f"/releases/download/"
        f"v{version}/"
        f"{zip_name}"
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<plugins>
  <pyqgis_plugin
      name="{xml_escape(name)}"
      version="{xml_escape(version)}">

    <description><![CDATA[
{description}
    ]]></description>

    <about><![CDATA[
{about}
    ]]></about>

    <version>{xml_escape(version)}</version>

    <qgis_minimum_version>{xml_escape(qgis_min)}</qgis_minimum_version>
    <qgis_maximum_version>{xml_escape(qgis_max)}</qgis_maximum_version>

    <homepage>{xml_escape(homepage)}</homepage>
    <tracker>{xml_escape(tracker)}</tracker>
    <repository>{xml_escape(repository)}</repository>

    <author_name>{xml_escape(author)}</author_name>
    <email>{xml_escape(email)}</email>

    <category>{xml_escape(category)}</category>
    <tags>{xml_escape(tags)}</tags>

    <file_name>{xml_escape(zip_name)}</file_name>
    <download_url>{xml_escape(download_url)}</download_url>

    <experimental>False</experimental>
    <deprecated>False</deprecated>

  </pyqgis_plugin>
</plugins>
"""

    DIST_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = DIST_DIR / "plugins.xml"

    output.write_text(
        xml,
        encoding="utf-8",
    )

    print(f"Created: {output}")

    return output


if __name__ == "__main__":
    try:
        generate_plugins_xml()

    except Exception as exc:
        print(
            f"XML GENERATION FAILED: {exc}",
            file=sys.stderr,
        )
        raise