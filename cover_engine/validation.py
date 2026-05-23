from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .legacy import CoverError, TEXT_COLOR_DEFAULTS, calculate_geometry, clean_key, parse_hex_color, resolve_path


@dataclass
class ValidationIssue:
    severity: str
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "field": self.field, "message": self.message}


def _float_value(data: dict[str, Any], key: str, issues: list[ValidationIssue]) -> float | None:
    value = data.get(key, "")
    if str(value).strip() == "":
        issues.append(ValidationIssue("error", key, "Required value is missing."))
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        issues.append(ValidationIssue("error", key, "Value must be a number."))
        return None


def validate_cover(data: dict[str, Any], metadata_path: Path | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for key in ("binding_type", "interior_type", "paper_type", "trim_size", "page_count"):
        if str(data.get(key, "")).strip() == "":
            issues.append(ValidationIssue("error", key, "Required value is missing."))

    if clean_key(str(data.get("trim_size", ""))) == "custom":
        for key in ("custom_trim_width_inches", "custom_trim_height_inches"):
            value = _float_value(data, key, issues)
            if value is not None and value <= 0:
                issues.append(ValidationIssue("error", key, "Custom trim size must be greater than zero."))
        for key in ("custom_spine_width_inches", "custom_bleed_inches", "custom_safe_margin_inches"):
            raw = str(data.get(key, "")).strip()
            if raw:
                value = _float_value(data, key, issues)
                if value is not None and value < 0:
                    issues.append(ValidationIssue("error", key, "Value cannot be negative."))

    try:
        page_count = int(data.get("page_count", 0))
        if page_count < 24:
            issues.append(ValidationIssue("error", "page_count", "Print books usually require at least 24 pages."))
    except (TypeError, ValueError):
        issues.append(ValidationIssue("error", "page_count", "Page count must be a whole number."))

    image_value = str(data.get("front_cover_image", "")).strip()
    if not image_value:
        issues.append(ValidationIssue("error", "front_cover_image", "Front cover image is required."))
    else:
        image_path = resolve_path(image_value)
        if not image_path.exists():
            issues.append(ValidationIssue("error", "front_cover_image", f"Image does not exist: {image_path}"))

    photo_value = str(data.get("author_photo", "")).strip()
    if photo_value and not resolve_path(photo_value).exists():
        issues.append(ValidationIssue("warning", "author_photo", "Author photo path does not exist."))

    color = str(data.get("spine_color", "auto")).strip()
    if color and color.lower() != "auto":
        try:
            parse_hex_color(color)
        except CoverError:
            issues.append(ValidationIssue("error", "spine_color", "Spine color must be auto or #RRGGBB."))

    for key, label in (
        ("color_title", "Title color"),
        ("color_accent", "Accent color"),
        ("color_body", "Body color"),
        ("color_soft", "Soft text color"),
    ):
        try:
            parse_hex_color(str(data.get(key, TEXT_COLOR_DEFAULTS[key])).strip())
        except CoverError:
            issues.append(ValidationIssue("error", key, f"{label} must be a HEX color such as #daa520."))

    binding = str(data.get("binding_type", "")).strip()
    if binding == "hc":
        for key in (
            "template_full_cover_width",
            "template_full_cover_height",
            "template_front_cover_width",
            "template_front_cover_height",
            "template_spine_width",
            "template_hinge_width",
            "template_wrap_width",
        ):
            _float_value(data, key, issues)

    if clean_key(str(data.get("trim_size", ""))) == "custom":
        issues.append(
            ValidationIssue(
                "info",
                "trim_size",
                "Using a custom size. Check your printer's bleed, spine, and safe-area requirements.",
            )
        )

    try:
        geometry = calculate_geometry(data)
    except Exception as exc:
        issues.append(ValidationIssue("error", "geometry", str(exc)))
        return issues

    if data.get("spine_text") and geometry.spine_inches < 0.25:
        issues.append(
            ValidationIssue(
                "warning",
                "spine_text",
                "Spine is narrow; your printer may reject it or the text may be hard to read.",
            )
        )

    if str(data.get("blurb", "")).strip() == "":
        issues.append(ValidationIssue("warning", "blurb", "Back-cover blurb is empty."))

    if metadata_path and metadata_path.exists() and metadata_path.name != "cover.md":
        issues.append(ValidationIssue("info", "metadata", f"Using metadata file {metadata_path.name}."))

    return issues
