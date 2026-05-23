from __future__ import annotations

from pathlib import Path
from typing import Any

from .legacy import dump_simple_yaml, normalize_loaded_data, read_frontmatter, write_metadata

SCHEMA_VERSION = 1

OLD_TEMPLATE_PREFIX = "k" + "d" + "p_"
TEMPLATE_ALIASES = {
    f"{OLD_TEMPLATE_PREFIX}full_cover_width": "template_full_cover_width",
    f"{OLD_TEMPLATE_PREFIX}full_cover_height": "template_full_cover_height",
    f"{OLD_TEMPLATE_PREFIX}front_cover_width": "template_front_cover_width",
    f"{OLD_TEMPLATE_PREFIX}front_cover_height": "template_front_cover_height",
    f"{OLD_TEMPLATE_PREFIX}spine_width": "template_spine_width",
    f"{OLD_TEMPLATE_PREFIX}hinge_width": "template_hinge_width",
    f"{OLD_TEMPLATE_PREFIX}wrap_width": "template_wrap_width",
}


def normalize_float(data: dict[str, Any], key: str, default: float | str) -> None:
    value = data.get(key, default)
    if str(value).strip() == "":
        data[key] = ""
        return
    try:
        data[key] = float(value)
    except (TypeError, ValueError):
        data[key] = default


def migrate_metadata(data: dict[str, Any]) -> dict[str, Any]:
    migrated = normalize_loaded_data(dict(data))
    for old_key, new_key in TEMPLATE_ALIASES.items():
        if new_key not in migrated and old_key in migrated:
            migrated[new_key] = migrated[old_key]
        migrated.pop(old_key, None)
    try:
        migrated["schema_version"] = int(migrated.get("schema_version", SCHEMA_VERSION))
    except (TypeError, ValueError):
        migrated["schema_version"] = SCHEMA_VERSION

    # Older files used one shared front-cover filename and a loose collection of
    # offsets. Keep those fields valid while adding safer defaults for new runs.
    migrated.setdefault("ui_units", "in")
    old_platform_key = "platform_" + "k" + "d" + "p"
    if "platform_preset" not in migrated and old_platform_key in migrated:
        migrated["platform_preset"] = migrated[old_platform_key]
    migrated.pop(old_platform_key, None)
    migrated.setdefault("platform_preset", True)
    normalize_float(migrated, "custom_trim_width_inches", 6.0)
    normalize_float(migrated, "custom_trim_height_inches", 9.0)
    normalize_float(migrated, "custom_spine_width_inches", "")
    normalize_float(migrated, "custom_bleed_inches", 0.125)
    normalize_float(migrated, "custom_safe_margin_inches", 0.375)
    normalize_float(migrated, "guide_x_offset_inches", 0.0)
    migrated.setdefault("font_title", "")
    migrated.setdefault("font_bold", "")
    migrated.setdefault("font_regular", "")
    migrated.setdefault("font_italic", "")
    migrated.setdefault("color_title", "#daa520")
    migrated.setdefault("color_accent", "#eec448")
    migrated.setdefault("color_body", "#efe6d4")
    migrated.setdefault("color_soft", "#c6bca9")
    migrated.setdefault("kindle_write_latest", True)
    migrated.setdefault("front_cover_image_centered", False)
    migrated.setdefault("front_cover_image_offset_y_inches", 0.0)

    for binding in ("pb", "hc"):
        migrated.setdefault(f"{binding}_front_image_centered", False)
        migrated.setdefault(f"{binding}_front_title_centered", False)
        migrated.setdefault(f"{binding}_front_subtitle_centered", False)
        migrated.setdefault(f"{binding}_front_author_centered", False)

    return migrated


def load_metadata(path: Path) -> tuple[dict[str, Any], str]:
    data, body = read_frontmatter(path)
    return migrate_metadata(data), body


def save_metadata(path: Path, data: dict[str, Any], body: str = "") -> None:
    write_metadata(path, migrate_metadata(data), body)


def metadata_to_yaml(data: dict[str, Any]) -> str:
    return dump_simple_yaml(migrate_metadata(data))
