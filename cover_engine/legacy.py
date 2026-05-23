#!/usr/bin/env python3
"""
Interactive print-cover generator.

The script stores its answers in YAML frontmatter in a Markdown file, then
generates:

  * <repo>-[hc|pb]-cover.pdf   Print-ready wraparound cover
  * <repo>-[hc|pb]-cover.png   300 DPI wraparound cover image
  * <repo>-kindle.jpg          cropped front cover image

Paperback preset dimensions are computed from published print-on-demand
formulas. Hardcover dimensions can be read from exact printer template values.
"""

from __future__ import annotations

import argparse
import curses
import io
import re
import sys
import textwrap
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


PROJECT_ROOT = Path.cwd()
HERE = PROJECT_ROOT / "cover"
DEFAULT_METADATA = HERE / "cover.md"
TEMPLATE_HOST = "k" + "d" + "p.amazon.com"
TEMPLATE_CALCULATOR_URL = f"https://{TEMPLATE_HOST}/cover-templates?language=en_US"
PAPERBACK_HELP_URL = f"https://{TEMPLATE_HOST}/en_US/help/topic/G201953020"
HARDCOVER_HELP_URL = f"https://{TEMPLATE_HOST}/en_US/help/topic/GDTKFJPNQCBTMRV6"


BINDING_OPTIONS = {
    "pb": "Paperback",
    "hc": "Hardcover",
}

INTERIOR_OPTIONS = {
    "black_white": "Black & white",
    "standard_color": "Standard color",
    "premium_color": "Premium color",
}

PAPER_OPTIONS = {
    "black_white": {
        "white": "White paper",
        "cream": "Cream paper",
    },
    "standard_color": {
        "white": "White paper",
    },
    "premium_color": {
        "white": "White paper",
    },
}

PAPERBACK_TRIMS = {
    "custom": (0.0, 0.0),
    "5x7.4": (5.0, 7.4),
    "5x8": (5.0, 8.0),
    "5.06x7.81": (5.06, 7.81),
    "5.25x8": (5.25, 8.0),
    "5.5x8.5": (5.5, 8.5),
    "6x9": (6.0, 9.0),
    "6.14x9.21": (6.14, 9.21),
    "6.69x9.61": (6.69, 9.61),
    "7x10": (7.0, 10.0),
    "7.44x9.69": (7.44, 9.69),
    "7.5x9.25": (7.5, 9.25),
    "8x10": (8.0, 10.0),
    "8.25x6": (8.25, 6.0),
    "8.25x8.25": (8.25, 8.25),
    "8.27x11.69": (8.27, 11.69),
    "8.5x8.5": (8.5, 8.5),
    "8.5x11": (8.5, 11.0),
}

HARDCOVER_TRIMS = {
    "custom": (0.0, 0.0),
    "5.5x8.5": (5.5, 8.5),
    "6x9": (6.0, 9.0),
    "6.14x9.21": (6.14, 9.21),
    "7x10": (7.0, 10.0),
    "8.25x11": (8.25, 11.0),
}

SPINE_MULTIPLIERS = {
    ("black_white", "white"): 0.002252,
    ("black_white", "cream"): 0.0025,
    ("standard_color", "white"): 0.002252,
    ("premium_color", "white"): 0.002347,
}

TEXT_COLOR_DEFAULTS = {
    "color_title": "#daa520",
    "color_accent": "#eec448",
    "color_body": "#efe6d4",
    "color_soft": "#c6bca9",
}


class CoverError(RuntimeError):
    pass


@dataclass
class KdpDocsStatus:
    calculator_reachable: bool
    paperback_help_reachable: bool
    hardcover_help_reachable: bool
    notes: list[str]


@dataclass
class FormField:
    key: str
    label: str
    kind: str = "text"
    options: dict[str, str] | None = None
    required: bool = False
    minimum: int | None = None
    maximum: int | None = None


@dataclass
class Geometry:
    binding_type: str
    reading_direction: str
    total_w_inches: float
    total_h_inches: float
    trim_w_inches: float
    trim_h_inches: float
    front_w_inches: float
    front_h_inches: float
    spine_inches: float
    bleed_inches: float
    hinge_inches: float
    wrap_inches: float
    safe_inches: float
    dpi: int = 300

    def __post_init__(self) -> None:
        self.total_w = px(self.total_w_inches, self.dpi)
        self.total_h = px(self.total_h_inches, self.dpi)
        self.front_w = px(self.front_w_inches, self.dpi)
        self.front_h = px(self.front_h_inches, self.dpi)
        self.spine_w = px(self.spine_inches, self.dpi)
        self.bleed = px(self.bleed_inches, self.dpi)
        self.hinge = px(self.hinge_inches, self.dpi)
        self.wrap = px(self.wrap_inches, self.dpi)
        self.safe = px(self.safe_inches, self.dpi)

        if self.binding_type == "pb":
            self.trim_top = self.bleed
            self.trim_bottom = self.trim_top + self.front_h
            self.back_left = self.bleed
            self.back_right = self.back_left + self.front_w
            self.spine_left = self.back_right
            self.spine_right = self.spine_left + self.spine_w
            self.front_left = self.spine_right
            self.front_right = self.front_left + self.front_w
        else:
            vertical_wrap = max(0, round((self.total_h - self.front_h) / 2))
            self.trim_top = vertical_wrap
            self.trim_bottom = self.trim_top + self.front_h
            self.back_left = self.wrap
            self.back_right = self.back_left + self.front_w
            self.spine_left = self.back_right + self.hinge
            self.spine_right = self.spine_left + self.spine_w
            self.front_left = self.spine_right + self.hinge
            self.front_right = self.front_left + self.front_w

        if self.reading_direction == "rtl":
            left_front = self.back_left
            right_front = self.back_right
            self.back_left = self.front_left
            self.back_right = self.front_right
            self.front_left = left_front
            self.front_right = right_front


def px(inches: float, dpi: int = 300) -> int:
    return round(inches * dpi)


def clean_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def parse_trim(value: str) -> tuple[float, float]:
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(?:in)?\s*$", value)
    if not match:
        raise CoverError(f"Trim size must look like 6x9, got {value!r}")
    return float(match.group(1)), float(match.group(2))


def trim_dimensions(data: dict[str, Any]) -> tuple[float, float]:
    if clean_key(str(data.get("trim_size", ""))) == "custom":
        try:
            width = float(data.get("custom_trim_width_inches", 0))
            height = float(data.get("custom_trim_height_inches", 0))
        except (TypeError, ValueError) as exc:
            raise CoverError("Custom trim width and height must be numbers.") from exc
        if width <= 0 or height <= 0:
            raise CoverError("Custom trim width and height must be greater than zero.")
        return width, height
    return parse_trim(str(data["trim_size"]))


def first_existing(paths: list[str]) -> str | None:
    for path in paths:
        if not path:
            continue
        if Path(path).expanduser().exists():
            return path
    return None


def set_project_context(metadata_path: Path) -> None:
    global HERE, PROJECT_ROOT, DEFAULT_METADATA
    DEFAULT_METADATA = metadata_path.resolve()
    HERE = DEFAULT_METADATA.parent
    PROJECT_ROOT = HERE.parent


def repo_name() -> str:
    return PROJECT_ROOT.name


def read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    yaml_text = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    return parse_simple_yaml(yaml_text), body


def parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {"|", ">"}:
            block: list[str] = []
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                block.append(lines[i][2:] if lines[i].startswith("  ") else "")
                i += 1
            data[key] = "\n".join(block).rstrip()
        elif value == "":
            data[key] = ""
        elif value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
        else:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            data[key] = value
    return data


def yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    text = "" if value is None else str(value)
    if not text:
        return '""'
    if re.match(r"^[A-Za-z0-9_./~:+ -]+$", text) and not text.startswith(("-", "{", "[")):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_simple_yaml(data: dict[str, Any]) -> str:
    ordered = [
        "schema_version",
        "ui_units",
        "platform_preset",
        "binding_type",
        "interior_type",
        "paper_type",
        "reading_direction",
        "trim_size",
        "custom_trim_width_inches",
        "custom_trim_height_inches",
        "custom_spine_width_inches",
        "custom_bleed_inches",
        "custom_safe_margin_inches",
        "guide_x_offset_inches",
        "page_count",
        "front_cover_image",
        "front_cover_image_offset_x_inches",
        "front_cover_image_offset_y_inches",
        "front_cover_image_centered",
        "pb_front_image_offset_x_inches",
        "pb_front_image_offset_y_inches",
        "pb_front_image_centered",
        "hc_front_image_offset_x_inches",
        "hc_front_image_offset_y_inches",
        "hc_front_image_centered",
        "title",
        "subtitle",
        "author_name",
        "author_photo",
        "font_title",
        "font_bold",
        "font_regular",
        "font_italic",
        "color_title",
        "color_accent",
        "color_body",
        "color_soft",
        "front_title_offset_x_inches",
        "front_title_offset_y_inches",
        "front_title_centered",
        "front_subtitle_offset_x_inches",
        "front_subtitle_offset_y_inches",
        "front_subtitle_centered",
        "front_author_offset_x_inches",
        "front_author_offset_y_inches",
        "front_author_centered",
        "pb_front_title_offset_x_inches",
        "pb_front_title_offset_y_inches",
        "pb_front_title_centered",
        "pb_front_subtitle_offset_x_inches",
        "pb_front_subtitle_offset_y_inches",
        "pb_front_subtitle_centered",
        "pb_front_author_offset_x_inches",
        "pb_front_author_offset_y_inches",
        "pb_front_author_centered",
        "hc_front_title_offset_x_inches",
        "hc_front_title_offset_y_inches",
        "hc_front_title_centered",
        "hc_front_subtitle_offset_x_inches",
        "hc_front_subtitle_offset_y_inches",
        "hc_front_subtitle_centered",
        "hc_front_author_offset_x_inches",
        "hc_front_author_offset_y_inches",
        "hc_front_author_centered",
        "spine_text",
        "spine_color",
        "spine_text_offset_inches",
        "spine_title_offset_x_inches",
        "spine_title_offset_y_inches",
        "spine_author_offset_x_inches",
        "spine_author_offset_y_inches",
        "pb_spine_title_offset_x_inches",
        "pb_spine_title_offset_y_inches",
        "pb_spine_author_offset_x_inches",
        "pb_spine_author_offset_y_inches",
        "hc_spine_title_offset_x_inches",
        "hc_spine_title_offset_y_inches",
        "hc_spine_author_offset_x_inches",
        "hc_spine_author_offset_y_inches",
        "spine_color_extension_inches",
        "quote",
        "quote_attribution",
        "blurb",
        "back_blurb_offset_x_inches",
        "back_blurb_offset_y_inches",
        "pb_back_blurb_offset_x_inches",
        "pb_back_blurb_offset_y_inches",
        "hc_back_blurb_offset_x_inches",
        "hc_back_blurb_offset_y_inches",
        "author_bio",
        "back_author_bio_offset_x_inches",
        "back_author_bio_offset_y_inches",
        "back_author_bio_paragraph_gap_points",
        "back_author_image_offset_x_inches",
        "back_author_image_offset_y_inches",
        "back_quote_offset_x_inches",
        "back_quote_offset_y_inches",
        "back_quote_attribution_offset_x_inches",
        "back_quote_attribution_offset_y_inches",
        "pb_back_author_bio_offset_x_inches",
        "pb_back_author_bio_offset_y_inches",
        "pb_back_author_bio_paragraph_gap_points",
        "pb_back_author_image_offset_x_inches",
        "pb_back_author_image_offset_y_inches",
        "pb_back_quote_offset_x_inches",
        "pb_back_quote_offset_y_inches",
        "pb_back_quote_attribution_offset_x_inches",
        "pb_back_quote_attribution_offset_y_inches",
        "hc_back_author_bio_offset_x_inches",
        "hc_back_author_bio_offset_y_inches",
        "hc_back_author_bio_paragraph_gap_points",
        "hc_back_author_image_offset_x_inches",
        "hc_back_author_image_offset_y_inches",
        "hc_back_quote_offset_x_inches",
        "hc_back_quote_offset_y_inches",
        "hc_back_quote_attribution_offset_x_inches",
        "hc_back_quote_attribution_offset_y_inches",
        "template_full_cover_width",
        "template_full_cover_height",
        "template_front_cover_width",
        "template_front_cover_height",
        "template_spine_width",
        "template_hinge_width",
        "template_wrap_width",
        "kindle_write_latest",
    ]
    lines: list[str] = []
    seen: set[str] = set()
    for key in ordered + sorted(data):
        if key in seen or key not in data:
            continue
        seen.add(key)
        value = data[key]
        if isinstance(value, str) and "\n" in value:
            lines.append(f"{key}: |")
            lines.extend(f"  {line}" for line in value.splitlines())
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def write_metadata(path: Path, data: dict[str, Any], body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not body.strip():
        body = (
            "# Cover Metadata\n\n"
            "Edit the YAML frontmatter directly, or run the script again to update it interactively.\n"
        )
    path.write_text(f"---\n{dump_simple_yaml(data)}---\n\n{body.lstrip()}", encoding="utf-8")


def fetch_url(url: str, timeout: float = 8.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) CoverStudio/1.0"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def query_template_docs() -> KdpDocsStatus:
    notes: list[str] = []
    states: dict[str, bool] = {}
    for label, url, expected in [
        ("calculator", TEMPLATE_CALCULATOR_URL, "Print Cover Calculator"),
        ("paperback_help", PAPERBACK_HELP_URL, "Create a Paperback Cover"),
        ("hardcover_help", HARDCOVER_HELP_URL, "Create a Hardcover Cover"),
    ]:
        try:
            text = fetch_url(url)
            states[label] = expected in text
        except (OSError, urllib.error.URLError) as exc:
            states[label] = False
            notes.append(f"Could not reach printer preset {label.replace('_', ' ')}: {exc}")
    if states.get("calculator"):
        notes.append("Reached print cover calculator page.")
    if states.get("paperback_help"):
        notes.append("Reached paperback cover requirements page.")
    if states.get("hardcover_help"):
        notes.append("Reached hardcover cover requirements page.")
    return KdpDocsStatus(
        calculator_reachable=states.get("calculator", False),
        paperback_help_reachable=states.get("paperback_help", False),
        hardcover_help_reachable=states.get("hardcover_help", False),
        notes=notes,
    )


def parse_hex_color(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
    if not match:
        raise CoverError(f"Color must be #RRGGBB, got {value!r}")
    hex_value = match.group(1)
    return (
        int(hex_value[0:2], 16),
        int(hex_value[2:4], 16),
        int(hex_value[4:6], 16),
    )


def metadata_color(data: dict[str, Any], key: str) -> tuple[int, int, int]:
    fallback = TEXT_COLOR_DEFAULTS[key]
    try:
        return parse_hex_color(str(data.get(key, fallback) or fallback))
    except CoverError:
        return parse_hex_color(fallback)


def rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def derive_spine_color(image_path: Path) -> tuple[int, int, int]:
    image = Image.open(image_path).convert("RGB")
    sample = image.resize((80, 80), Image.Resampling.LANCZOS)
    palette = sample.quantize(colors=8, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = palette.getcolors(maxcolors=80 * 80) or []
    if not colors:
        return (18, 43, 34)

    def score(item: tuple[int, tuple[int, int, int]]) -> float:
        count, (r, g, b) = item
        brightness = (r + g + b) / 3
        saturation = max(r, g, b) - min(r, g, b)
        return count * (1 + saturation / 255) * (1.35 - abs(brightness - 95) / 255)

    _, color = max(colors, key=score)
    r, g, b = color
    # A spine should usually read as a quieter extension of the art, not the
    # loudest sampled color, so bias the chosen dominant color darker.
    return (
        max(8, min(90, round(r * 0.45))),
        max(8, min(90, round(g * 0.45))),
        max(8, min(90, round(b * 0.45))),
    )


def resolve_spine_color(value: Any, image_path: Path) -> tuple[int, int, int]:
    text = str(value or "auto").strip()
    if not text or text.lower() == "auto":
        return derive_spine_color(image_path)
    return parse_hex_color(text)


class MetadataTui:
    def __init__(self, stdscr: Any, data: dict[str, Any], docs: KdpDocsStatus) -> None:
        self.stdscr = stdscr
        self.data = self.with_defaults(data)
        self.docs = docs
        self.index = 0
        self.top = 0
        self.message = "Enter edits a field. Space cycles options. S saves and generates. Q cancels."

    def with_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        merged = dict(data)
        merged.setdefault("binding_type", "hc")
        merged.setdefault("interior_type", "black_white")
        merged.setdefault("paper_type", "white")
        merged.setdefault("reading_direction", "ltr")
        merged.setdefault("trim_size", "6x9")
        merged.setdefault("custom_trim_width_inches", 6.0)
        merged.setdefault("custom_trim_height_inches", 9.0)
        merged.setdefault("custom_spine_width_inches", "")
        merged.setdefault("custom_bleed_inches", 0.125)
        merged.setdefault("custom_safe_margin_inches", 0.375)
        merged.setdefault("guide_x_offset_inches", 0.0)
        merged.setdefault("page_count", 79)
        merged.setdefault("front_cover_image", "cover/assets/Marcus.png")
        merged.setdefault("front_cover_image_offset_x_inches", 0.0)
        merged.setdefault("front_cover_image_offset_y_inches", 0.0)
        merged.setdefault("front_cover_image_centered", False)
        merged.setdefault("title", repo_name().replace("-", " ").title())
        merged.setdefault("subtitle", "")
        merged.setdefault("author_name", "Philip Huffman")
        merged.setdefault("author_photo", "")
        merged.setdefault("font_title", "")
        merged.setdefault("font_bold", "")
        merged.setdefault("font_regular", "")
        merged.setdefault("font_italic", "")
        for key, value in TEXT_COLOR_DEFAULTS.items():
            merged.setdefault(key, value)
        merged.setdefault("spine_text", int(merged.get("page_count", 79)) > 79)
        merged.setdefault("spine_color", "auto")
        merged.setdefault("spine_text_offset_inches", 0.0)
        merged.setdefault("spine_color_extension_inches", 0.25)
        merged.setdefault("quote", "")
        merged.setdefault("quote_attribution", merged.get("author_name", ""))
        merged.setdefault("blurb", "")
        merged.setdefault("author_bio", "")
        return merged

    def fields(self) -> list[FormField]:
        binding = clean_key(str(self.data.get("binding_type", "hc")))
        interior = clean_key(str(self.data.get("interior_type", "black_white")))
        trim_options = PAPERBACK_TRIMS if binding == "pb" else HARDCOVER_TRIMS
        paper_options = PAPER_OPTIONS.get(interior, PAPER_OPTIONS["black_white"])
        binding_label = BINDING_OPTIONS.get(binding, binding.upper())

        def binding_key(key: str) -> str:
            return f"{binding}_{key}"

        fields = [
            FormField("binding_type", "Binding", "option", BINDING_OPTIONS, True),
            FormField("interior_type", "Interior", "option", INTERIOR_OPTIONS, True),
            FormField("paper_type", "Paper", "option", paper_options, True),
            FormField(
                "reading_direction",
                "Reading Direction",
                "option",
                {"ltr": "Left to Right", "rtl": "Right to Left"},
                True,
            ),
            FormField(
                "trim_size",
                "Trim Size",
                "option",
                {k: "Custom size" if k == "custom" else f"{v[0]:g} x {v[1]:g} in" for k, v in trim_options.items()},
                True,
            ),
            FormField("custom_trim_width_inches", "Custom Trim Width", "float", minimum=0),
            FormField("custom_trim_height_inches", "Custom Trim Height", "float", minimum=0),
            FormField("custom_spine_width_inches", "Custom Spine Width", "float", minimum=0),
            FormField("custom_bleed_inches", "Custom Bleed", "float", minimum=0),
            FormField("custom_safe_margin_inches", "Custom Safe Margin", "float", minimum=0),
            FormField("guide_x_offset_inches", "Guide X Shift", "float"),
            FormField("page_count", "Page Count", "int", required=True, minimum=24, maximum=830 if binding == "pb" else 550),
            FormField("front_cover_image", "Front Background Image", "text", required=True),
            FormField(binding_key("front_image_centered"), f"{binding_label} Center Front Image", "bool"),
            FormField(binding_key("front_image_offset_x_inches"), f"{binding_label} Front Image X Offset", "float"),
            FormField(binding_key("front_image_offset_y_inches"), f"{binding_label} Front Image Y Offset", "float"),
            FormField("title", "Title", "text", required=True),
            FormField("subtitle", "Subtitle", "text"),
            FormField("author_name", "Author Name", "text", required=True),
            FormField("author_photo", "Author Photo", "text"),
            FormField("font_title", "Title Font", "text"),
            FormField("font_bold", "Bold Font", "text"),
            FormField("font_regular", "Body Font", "text"),
            FormField("font_italic", "Italic Font", "text"),
            FormField("color_title", "Title Color", "color"),
            FormField("color_accent", "Accent Color", "color"),
            FormField("color_body", "Body Color", "color"),
            FormField("color_soft", "Soft Text Color", "color"),
            FormField(binding_key("front_title_centered"), f"{binding_label} Center Front Title", "bool"),
            FormField(binding_key("front_title_offset_x_inches"), f"{binding_label} Front Title X Offset", "float"),
            FormField(binding_key("front_title_offset_y_inches"), f"{binding_label} Front Title Y Offset", "float"),
            FormField(binding_key("front_subtitle_centered"), f"{binding_label} Center Front Subtitle", "bool"),
            FormField(binding_key("front_subtitle_offset_x_inches"), f"{binding_label} Front Subtitle X Offset", "float"),
            FormField(binding_key("front_subtitle_offset_y_inches"), f"{binding_label} Front Subtitle Y Offset", "float"),
            FormField(binding_key("front_author_centered"), f"{binding_label} Center Front Author", "bool"),
            FormField(binding_key("front_author_offset_x_inches"), f"{binding_label} Front Author X Offset", "float"),
            FormField(binding_key("front_author_offset_y_inches"), f"{binding_label} Front Author Y Offset", "float"),
            FormField("spine_text", "Spine Text", "bool"),
            FormField("spine_color", "Spine Color", "color"),
            FormField("spine_text_offset_inches", "Spine Text Offset", "float"),
            FormField(binding_key("spine_title_offset_x_inches"), f"{binding_label} Spine Title X Offset", "float"),
            FormField(binding_key("spine_title_offset_y_inches"), f"{binding_label} Spine Title Y Offset", "float"),
            FormField(binding_key("spine_author_offset_x_inches"), f"{binding_label} Spine Author X Offset", "float"),
            FormField(binding_key("spine_author_offset_y_inches"), f"{binding_label} Spine Author Y Offset", "float"),
            FormField("spine_color_extension_inches", "Spine Color Extension", "float", minimum=0),
            FormField("quote", "Quote", "multiline"),
            FormField("quote_attribution", "Quote Attribution", "text"),
            FormField("blurb", "Back-Cover Blurb", "multiline"),
            FormField(binding_key("back_blurb_offset_x_inches"), f"{binding_label} Back Blurb X Offset", "float"),
            FormField(binding_key("back_blurb_offset_y_inches"), f"{binding_label} Back Blurb Y Offset", "float"),
            FormField("author_bio", "Author Biography", "multiline"),
            FormField(binding_key("back_author_bio_offset_x_inches"), f"{binding_label} Back Bio X Offset", "float"),
            FormField(binding_key("back_author_bio_offset_y_inches"), f"{binding_label} Back Bio Y Offset", "float"),
            FormField(binding_key("back_author_bio_paragraph_gap_points"), f"{binding_label} Back Bio Paragraph Gap", "float", minimum=0),
            FormField(binding_key("back_author_image_offset_x_inches"), f"{binding_label} Back Author Image X Offset", "float"),
            FormField(binding_key("back_author_image_offset_y_inches"), f"{binding_label} Back Author Image Y Offset", "float"),
            FormField(binding_key("back_quote_offset_x_inches"), f"{binding_label} Back Quote X Offset", "float"),
            FormField(binding_key("back_quote_offset_y_inches"), f"{binding_label} Back Quote Y Offset", "float"),
            FormField(binding_key("back_quote_attribution_offset_x_inches"), f"{binding_label} Back Quote Attribution X Offset", "float"),
            FormField(binding_key("back_quote_attribution_offset_y_inches"), f"{binding_label} Back Quote Attribution Y Offset", "float"),
        ]
        if binding == "hc":
            fields.extend(
                [
                    FormField("template_full_cover_width", "Template Full Cover Width", "float", required=True),
                    FormField("template_full_cover_height", "Template Full Cover Height", "float", required=True),
                    FormField("template_front_cover_width", "Template Front Cover Width", "float", required=True),
                    FormField("template_front_cover_height", "Template Front Cover Height", "float", required=True),
                    FormField("template_spine_width", "Template Spine Width", "float", required=True),
                    FormField("template_hinge_width", "Template Hinge Width", "float", required=True),
                    FormField("template_wrap_width", "Template Wrap Width", "float", required=True),
                ]
            )
        return fields

    def run(self) -> dict[str, Any] | None:
        self.set_cursor(False)
        self.stdscr.keypad(True)
        while True:
            fields = self.fields()
            self.index = min(self.index, len(fields) - 1)
            self.render(fields)
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None
            if key in (ord("o"), ord("O")):
                webbrowser.open(TEMPLATE_CALCULATOR_URL)
                self.message = "Opened the template calculator page in your default browser."
                continue
            if key in (ord("s"), ord("S")):
                errors = self.validate(fields)
                if errors:
                    self.message = errors[0]
                    continue
                return self.data
            if key in (curses.KEY_UP, ord("k")):
                self.index = max(0, self.index - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.index = min(len(fields) - 1, self.index + 1)
            elif key in (curses.KEY_NPAGE,):
                self.index = min(len(fields) - 1, self.index + 8)
            elif key in (curses.KEY_PPAGE,):
                self.index = max(0, self.index - 8)
            elif key in (curses.KEY_RIGHT, ord(" "), ord("\t")):
                self.cycle(fields[self.index], 1)
            elif key in (curses.KEY_LEFT,):
                self.cycle(fields[self.index], -1)
            elif key in (10, 13, curses.KEY_ENTER):
                self.edit(fields[self.index])

    def render(self, fields: list[FormField]) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        visible_rows = max(1, height - 8)
        if self.index < self.top:
            self.top = self.index
        if self.index >= self.top + visible_rows:
            self.top = self.index - visible_rows + 1

        title = f"Cover Studio - {repo_name()}"
        self.add(0, 0, title[: width - 1], curses.A_BOLD)
        status = "Printer presets: "
        status += "calculator ok" if self.docs.calculator_reachable else "calculator unavailable"
        status += ", paperback ok" if self.docs.paperback_help_reachable else ", paperback unavailable"
        status += ", hardcover ok" if self.docs.hardcover_help_reachable else ", hardcover unavailable"
        self.add(1, 0, status[: width - 1], curses.A_DIM)

        if clean_key(str(self.data.get("binding_type", "hc"))) == "hc":
            self.add(
                2,
                0,
                "Hardcover uses exact inch dimensions copied from a printer calculator/template.",
                curses.A_DIM,
            )
            self.add(3, 0, f"Press O to open: {TEMPLATE_CALCULATOR_URL}", curses.A_DIM)

        form_top = 5 if clean_key(str(self.data.get("binding_type", "hc"))) == "hc" else 4
        for row, field in enumerate(fields[self.top : self.top + visible_rows], start=form_top):
            absolute = self.top + row - form_top
            selected = absolute == self.index
            attr = curses.A_REVERSE if selected else curses.A_NORMAL
            value = self.display_value(field)
            label_w = min(26, max(12, width // 3))
            line = f"{field.label:<{label_w}} {value}"
            self.add(row, 0, line[: width - 1], attr)

        help_line = "Up/Down move | Enter edit | Space cycle | O open template page | S save+generate | Q cancel"
        self.add(height - 3, 0, help_line[: width - 1], curses.A_BOLD)
        self.add(height - 2, 0, self.message[: width - 1], curses.A_DIM)
        self.stdscr.refresh()

    def add(self, y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> None:
        height, width = self.stdscr.getmaxyx()
        if 0 <= y < height and x < width:
            self.stdscr.addstr(y, x, text[: max(0, width - x - 1)], attr)

    def display_value(self, field: FormField) -> str:
        value = self.data.get(field.key, "")
        if field.kind == "option" and field.options:
            key = clean_key(str(value))
            for option_key, label in field.options.items():
                if clean_key(option_key) == key:
                    return f"{label} ({option_key})"
            return f"{value} ({key})"
        if field.kind == "bool":
            return "Yes" if bool(value) else "No"
        if field.kind == "color":
            text = str(value or "auto").strip()
            if text.lower() == "auto":
                derived = self.preview_spine_color()
                return f"auto -> {derived}" if derived else "auto"
            return text
        if field.kind == "multiline":
            text = " ".join(str(value).split())
            return textwrap.shorten(text, width=72, placeholder="...") if text else ""
        return str(value)

    def cycle(self, field: FormField, step: int) -> None:
        if field.kind == "bool":
            self.data[field.key] = not bool(self.data.get(field.key, False))
            return
        if field.kind != "option" or not field.options:
            return
        keys = list(field.options)
        current = clean_key(str(self.data.get(field.key, keys[0])))
        normalized_keys = [clean_key(key) for key in keys]
        try:
            index = normalized_keys.index(current)
        except ValueError:
            index = -1 if step > 0 else 0
        self.data[field.key] = keys[(index + step) % len(keys)]
        if field.key == "binding_type":
            trim_options = PAPERBACK_TRIMS if self.data[field.key] == "pb" else HARDCOVER_TRIMS
            if self.data.get("trim_size") not in trim_options:
                self.data["trim_size"] = "6x9"
        if field.key == "interior_type":
            paper_options = PAPER_OPTIONS.get(clean_key(str(self.data[field.key])), {})
            if self.data.get("paper_type") not in paper_options:
                self.data["paper_type"] = next(iter(paper_options))

    def edit(self, field: FormField) -> None:
        if field.kind in {"option", "bool"}:
            self.cycle(field, 1)
            return
        if field.kind == "multiline":
            self.edit_multiline(field)
            return
        self.set_cursor(True)
        height, width = self.stdscr.getmaxyx()
        prompt = f"{field.label}: "
        self.stdscr.move(height - 1, 0)
        self.stdscr.clrtoeol()
        self.add(height - 1, 0, prompt)
        curses.echo()
        try:
            raw = self.stdscr.getstr(height - 1, len(prompt), max(1, width - len(prompt) - 1))
        finally:
            curses.noecho()
            self.set_cursor(False)
        value = raw.decode("utf-8", errors="replace").strip()
        if not value:
            self.message = f"Kept {field.label}."
            return
        if field.kind == "int":
            try:
                parsed = int(value)
            except ValueError:
                self.message = f"{field.label} must be a whole number."
                return
            self.data[field.key] = parsed
        elif field.kind == "float":
            try:
                self.data[field.key] = float(value)
            except ValueError:
                self.message = f"{field.label} must be a decimal inch value."
                return
        elif field.kind == "color":
            if value.lower() == "auto":
                self.data[field.key] = "auto"
            else:
                try:
                    self.data[field.key] = rgb_to_hex(parse_hex_color(value))
                except CoverError as exc:
                    self.message = str(exc)
                    return
        else:
            self.data[field.key] = value
        self.message = f"Updated {field.label}."

    def edit_multiline(self, field: FormField) -> None:
        self.set_cursor(True)
        value = str(self.data.get(field.key, ""))
        lines = value.splitlines() or [""]
        cursor_y = len(lines) - 1
        cursor_x = len(lines[-1])
        while True:
            self.stdscr.erase()
            height, width = self.stdscr.getmaxyx()
            self.add(0, 0, f"Editing {field.label}", curses.A_BOLD)
            self.add(1, 0, "Ctrl-G saves. Esc cancels. Enter inserts a new line.", curses.A_DIM)
            top = max(0, cursor_y - (height - 5))
            for row, line in enumerate(lines[top : top + height - 4], start=3):
                self.add(row, 0, line)
            self.stdscr.move(3 + cursor_y - top, min(cursor_x, width - 2))
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key == 7:
                self.data[field.key] = "\n".join(lines).strip()
                self.message = f"Updated {field.label}."
                self.set_cursor(False)
                return
            if key == 27:
                self.message = f"Canceled {field.label} edit."
                self.set_cursor(False)
                return
            if key in (10, 13):
                line = lines[cursor_y]
                lines[cursor_y] = line[:cursor_x]
                lines.insert(cursor_y + 1, line[cursor_x:])
                cursor_y += 1
                cursor_x = 0
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if cursor_x > 0:
                    line = lines[cursor_y]
                    lines[cursor_y] = line[: cursor_x - 1] + line[cursor_x:]
                    cursor_x -= 1
                elif cursor_y > 0:
                    cursor_x = len(lines[cursor_y - 1])
                    lines[cursor_y - 1] += lines.pop(cursor_y)
                    cursor_y -= 1
            elif key == curses.KEY_LEFT:
                cursor_x = max(0, cursor_x - 1)
            elif key == curses.KEY_RIGHT:
                cursor_x = min(len(lines[cursor_y]), cursor_x + 1)
            elif key == curses.KEY_UP:
                cursor_y = max(0, cursor_y - 1)
                cursor_x = min(cursor_x, len(lines[cursor_y]))
            elif key == curses.KEY_DOWN:
                cursor_y = min(len(lines) - 1, cursor_y + 1)
                cursor_x = min(cursor_x, len(lines[cursor_y]))
            elif 32 <= key <= 126:
                ch = chr(key)
                line = lines[cursor_y]
                lines[cursor_y] = line[:cursor_x] + ch + line[cursor_x:]
                cursor_x += 1

    def validate(self, fields: list[FormField]) -> list[str]:
        errors: list[str] = []
        for field in fields:
            value = self.data.get(field.key, "")
            if field.required and str(value).strip() == "":
                errors.append(f"{field.label} is required.")
            if field.kind == "int":
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    errors.append(f"{field.label} must be a whole number.")
                    continue
                if field.minimum is not None and parsed < field.minimum:
                    errors.append(f"{field.label} must be at least {field.minimum}.")
                if field.maximum is not None and parsed > field.maximum:
                    errors.append(f"{field.label} must be no more than {field.maximum}.")
            if field.kind == "float" and str(value).strip():
                try:
                    parsed = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{field.label} must be a decimal inch value.")
                    continue
                if field.minimum is not None and parsed < field.minimum:
                    errors.append(f"{field.label} must be at least {field.minimum}.")
            if field.kind == "color":
                text = str(value or "auto").strip()
                if text.lower() != "auto":
                    try:
                        parse_hex_color(text)
                    except CoverError:
                        errors.append(f"{field.label} must be auto or #RRGGBB.")
        return errors

    def set_cursor(self, visible: bool) -> None:
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def preview_spine_color(self) -> str:
        try:
            image_path = resolve_path(str(self.data.get("front_cover_image", "")))
            if not image_path.exists():
                return ""
            return rgb_to_hex(derive_spine_color(image_path))
        except (OSError, CoverError):
            return ""


def resolve_path(value: str, base: Path | None = None) -> Path:
    if base is None:
        base = PROJECT_ROOT
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def interactive_metadata(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    docs = query_template_docs()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CoverError("The interactive interface is a TUI and requires a terminal. Use --non-interactive for scripted runs.")
    result = curses.wrapper(lambda stdscr: MetadataTui(stdscr, data, docs).run())
    if result is None:
        raise KeyboardInterrupt
    return result


def calculate_geometry(data: dict[str, Any]) -> Geometry:
    binding = clean_key(str(data["binding_type"]))
    interior = clean_key(str(data["interior_type"]))
    paper = clean_key(str(data["paper_type"]))
    direction = clean_key(str(data.get("reading_direction", "ltr")))
    trim_w, trim_h = trim_dimensions(data)
    page_count = int(data["page_count"])

    if binding == "pb":
        multiplier = SPINE_MULTIPLIERS.get((interior, paper))
        if multiplier is None:
            raise CoverError(f"No paperback spine multiplier for {interior}/{paper}")
        custom_spine = str(data.get("custom_spine_width_inches", "")).strip()
        spine = float(custom_spine) if custom_spine else page_count * multiplier
        bleed = float(data.get("custom_bleed_inches", 0.125) or 0.125)
        safe = float(data.get("custom_safe_margin_inches", 0.375) or 0.375)
        total_w = bleed + trim_w + spine + trim_w + bleed
        total_h = bleed + trim_h + bleed
        return Geometry(
            binding_type=binding,
            reading_direction=direction,
            total_w_inches=total_w,
            total_h_inches=total_h,
            trim_w_inches=trim_w,
            trim_h_inches=trim_h,
            front_w_inches=trim_w,
            front_h_inches=trim_h,
            spine_inches=spine,
            bleed_inches=bleed,
            hinge_inches=0.0,
            wrap_inches=bleed,
            safe_inches=safe,
        )

    required = [
        "template_full_cover_width",
        "template_full_cover_height",
        "template_front_cover_width",
        "template_front_cover_height",
        "template_spine_width",
        "template_hinge_width",
        "template_wrap_width",
    ]
    missing = [key for key in required if key not in data or str(data[key]).strip() == ""]
    if missing:
        raise CoverError(
            "Hardcover requires exact printer calculator/template dimensions: "
            + ", ".join(missing)
        )
    return Geometry(
        binding_type=binding,
        reading_direction=direction,
        total_w_inches=float(data["template_full_cover_width"]),
        total_h_inches=float(data["template_full_cover_height"]),
        trim_w_inches=trim_w,
        trim_h_inches=trim_h,
        front_w_inches=float(data["template_front_cover_width"]),
        front_h_inches=float(data["template_front_cover_height"]),
        spine_inches=float(data["template_spine_width"]),
        bleed_inches=0.0,
        hinge_inches=float(data["template_hinge_width"]),
        wrap_inches=float(data["template_wrap_width"]),
        safe_inches=0.635,
    )


class CoverGenerator:
    def __init__(self, data: dict[str, Any], geometry: Geometry) -> None:
        self.data = data
        self.g = geometry
        self.colors = {
            "background": (24, 31, 29),
            "background_deep": (15, 22, 21),
            "spine": (18, 43, 34),
            "gold": metadata_color(data, "color_title"),
            "gold_light": metadata_color(data, "color_accent"),
            "text": metadata_color(data, "color_body"),
            "muted": metadata_color(data, "color_soft"),
            "black": (0, 0, 0),
        }
        self.fonts = {
            "title": first_existing(
                [
                    self.configured_font_path("font_title"),
                    str(PROJECT_ROOT / "cover" / "fonts" / "Title.ttf"),
                    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
                    "/Library/Fonts/Arial Black.ttf",
                    "C:/Windows/Fonts/ariblk.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                ]
            ),
            "bold": first_existing(
                [
                    self.configured_font_path("font_bold"),
                    str(PROJECT_ROOT / "cover" / "fonts" / "Bold.ttf"),
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/Library/Fonts/Arial Bold.ttf",
                    "C:/Windows/Fonts/arialbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                ]
            ),
            "regular": first_existing(
                [
                    self.configured_font_path("font_regular"),
                    str(PROJECT_ROOT / "cover" / "fonts" / "Regular.ttf"),
                    "/System/Library/Fonts/Supplemental/Arial.ttf",
                    "/Library/Fonts/Arial.ttf",
                    "C:/Windows/Fonts/arial.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                ]
            ),
            "italic": first_existing(
                [
                    self.configured_font_path("font_italic"),
                    str(PROJECT_ROOT / "cover" / "fonts" / "Italic.ttf"),
                    "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
                    "/Library/Fonts/Arial Italic.ttf",
                    "C:/Windows/Fonts/ariali.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
                    "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
                ]
            ),
        }

    def configured_font_path(self, key: str) -> str:
        value = str(self.data.get(key, "")).strip()
        if not value:
            return ""
        return str(resolve_path(value))

    def binding_value(self, key: str, default: Any = 0.0) -> Any:
        return self.data.get(f"{self.g.binding_type}_{key}", self.data.get(key, default))

    def font(self, key: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        font_path = self.fonts.get(key)
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                pass
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()

    def fit_font(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        key: str,
        max_size: int,
        max_width: int,
        min_size: int = 14,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for size in range(max_size, min_size - 1, -2):
            font = self.font(key, size)
            if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
                return font
        return self.font(key, min_size)

    def cover_crop(
        self,
        image: Image.Image,
        size: tuple[int, int],
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> Image.Image:
        target_w, target_h = size
        src_w, src_h = image.size
        scale = max(target_w / src_w, target_h / src_h)
        resized = image.resize((round(src_w * scale), round(src_h * scale)), Image.LANCZOS)
        max_left = max(0, resized.width - target_w)
        max_top = max(0, resized.height - target_h)
        left = min(max((resized.width - target_w) // 2 + offset_x, 0), max_left)
        top = min(max((resized.height - target_h) // 2 + offset_y, 0), max_top)
        return resized.crop((left, top, left + target_w, top + target_h))

    def overlay_vertical_gradient(
        self,
        base: Image.Image,
        box: tuple[int, int, int, int],
        top_alpha: int,
        bottom_alpha: int,
    ) -> None:
        x0, y0, x1, y1 = box
        height = y1 - y0
        mask = Image.new("L", (1, height))
        mask_px = mask.load()
        for y in range(height):
            ratio = y / max(1, height - 1)
            alpha = round(top_alpha * max(1 - ratio * 2, 0) + bottom_alpha * max(ratio * 2 - 1, 0))
            mask_px[0, y] = alpha
        mask = mask.resize((x1 - x0, height))
        overlay = Image.new("RGB", (x1 - x0, height), self.colors["black"])
        base.paste(overlay, (x0, y0), mask)

    def draw_wrapped(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        xy: tuple[int, int],
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        fill: tuple[int, int, int],
        max_width: int,
        leading: int,
        paragraph_gap: int = 22,
        max_y: int | None = None,
    ) -> int:
        x, y = xy
        for paragraph in text.split("\n\n"):
            words = paragraph.split()
            line = ""
            for word in words:
                trial = f"{line} {word}".strip()
                if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
                    line = trial
                    continue
                if line:
                    if max_y is not None and y + leading > max_y:
                        return y
                    draw.text((x, y), line, font=font, fill=fill)
                    y += leading
                line = word
            if line:
                if max_y is not None and y + leading > max_y:
                    return y
                draw.text((x, y), line, font=font, fill=fill)
                y += leading
            y += paragraph_gap
        return y

    def draw_centered(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        center_x: int,
        y: int,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        fill: tuple[int, int, int],
        shadow: bool = False,
    ) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        x = round(center_x - (bbox[0] + bbox[2]) / 2)
        if shadow:
            draw.text((x + 5, y + 5), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=fill)
        return y + (bbox[3] - bbox[1])

    def add_front(self, img: Image.Image, draw: ImageDraw.ImageDraw, art_path: Path) -> None:
        g = self.g
        image_offset = self.binding_value(
            "front_image_offset_x_inches",
            self.data.get("front_cover_image_offset_x_inches", 0.0),
        )
        image_offset_y = self.binding_value(
            "front_image_offset_y_inches",
            self.data.get("front_cover_image_offset_y_inches", 0.0),
        )
        image_centered = bool(self.binding_value("front_image_centered", self.data.get("front_cover_image_centered", False)))
        shift_x = 0 if image_centered else px(float(image_offset or 0.0), g.dpi)
        shift_y = 0 if image_centered else px(float(image_offset_y or 0.0), g.dpi)
        panel_left = g.front_left - g.hinge if g.binding_type == "hc" else g.front_left
        panel = (panel_left, 0, g.front_right + max(g.bleed, g.wrap), g.total_h)
        art_w = panel[2] - panel[0]
        art_h = panel[3] - panel[1]
        art = Image.open(art_path).convert("RGB")
        art = ImageEnhance.Color(art).enhance(0.88)
        art = ImageEnhance.Contrast(art).enhance(1.08)
        art = self.cover_crop(art, (art_w, art_h), offset_x=shift_x, offset_y=shift_y)
        img.paste(art, (panel[0], panel[1]))
        self.overlay_vertical_gradient(img, panel, top_alpha=175, bottom_alpha=205)

        title_offset_x = px(float(self.binding_value("front_title_offset_x_inches", 0.0) or 0.0), g.dpi)
        title_offset_y = px(float(self.binding_value("front_title_offset_y_inches", 0.0) or 0.0), g.dpi)
        subtitle_offset_x = px(float(self.binding_value("front_subtitle_offset_x_inches", 0.0) or 0.0), g.dpi)
        subtitle_offset_y = px(float(self.binding_value("front_subtitle_offset_y_inches", 0.0) or 0.0), g.dpi)
        author_offset_x = px(float(self.binding_value("front_author_offset_x_inches", 0.0) or 0.0), g.dpi)
        author_offset_y = px(float(self.binding_value("front_author_offset_y_inches", 0.0) or 0.0), g.dpi)
        if bool(self.binding_value("front_title_centered", self.data.get("front_title_centered", False))):
            title_offset_x = 0
            title_offset_y = 0
        if bool(self.binding_value("front_subtitle_centered", self.data.get("front_subtitle_centered", False))):
            subtitle_offset_x = 0
            subtitle_offset_y = 0
        if bool(self.binding_value("front_author_centered", self.data.get("front_author_centered", False))):
            author_offset_x = 0
            author_offset_y = 0
        title_scale = float(self.binding_value("front_title_scale", 1.0) or 1.0)
        author_scale = float(self.binding_value("front_author_scale", 1.0) or 1.0)
        center_x = g.front_left + g.front_w // 2
        title_center_x = center_x + title_offset_x
        subtitle_center_x = center_x + subtitle_offset_x
        max_text_w = g.front_w - (g.safe * 2)
        title = str(self.data.get("title", repo_name())).upper()
        subtitle = str(self.data.get("subtitle", ""))
        author = str(self.data.get("author_name", "")).upper()

        title_font = self.fit_font(draw, title, "title", round(178 * title_scale), max_text_w)
        subtitle_font = self.fit_font(draw, subtitle, "regular", 42, max_text_w) if subtitle else None
        author_font = self.fit_font(draw, author, "bold", round(48 * author_scale), max_text_w)

        y = g.trim_top + px(0.72, g.dpi) + title_offset_y
        y = self.draw_centered(draw, title, title_center_x, y, title_font, self.colors["gold"], shadow=True)
        if subtitle and subtitle_font:
            y += px(0.42, g.dpi)
            self.draw_centered(
                draw,
                subtitle,
                subtitle_center_x,
                y + subtitle_offset_y,
                subtitle_font,
                self.colors["gold_light"],
            )

        author_y = g.trim_bottom - px(0.57, g.dpi) + author_offset_y
        bbox = draw.textbbox((0, 0), author, font=author_font)
        author_x = round(center_x + author_offset_x - (bbox[0] + bbox[2]) / 2)
        draw.text((author_x, author_y), author, font=author_font, fill=self.colors["gold"])

    def add_spine(self, img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        g = self.g
        extension_inches = float(self.data.get("spine_color_extension_inches", 0.25) or 0)
        extension = px(extension_inches, g.dpi)
        band_left = max(0, g.spine_left - extension)
        band_right = min(g.total_w, g.spine_right + extension)
        draw.rectangle([(band_left, 0), (band_right, g.total_h)], fill=self.colors["spine"])
        if not self.data.get("spine_text", False):
            return
        spine_offset = px(float(self.data.get("spine_text_offset_inches", 0.0) or 0.0), g.dpi)
        spine_center = g.spine_left + g.spine_w // 2 + spine_offset
        items = [
            (
                str(self.data.get("title", repo_name())).upper(),
                "bold",
                42,
                g.trim_top + px(0.9, g.dpi),
                "spine_title",
            ),
            (
                str(self.data.get("author_name", "")).upper(),
                "regular",
                28,
                g.trim_bottom - px(0.85, g.dpi),
                "spine_author",
            ),
        ]
        for text, key, size, y, offset_prefix in items:
            font = self.font(key, size)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_img = Image.new("RGBA", (bbox[2] - bbox[0] + 34, bbox[3] - bbox[1] + 34), (0, 0, 0, 0))
            ImageDraw.Draw(text_img).text((17, 17), text, font=font, fill=self.colors["gold"])
            text_img = text_img.rotate(270, expand=True)
            offset_x = px(float(self.binding_value(f"{offset_prefix}_offset_x_inches", 0.0) or 0.0), g.dpi)
            offset_y = px(float(self.binding_value(f"{offset_prefix}_offset_y_inches", 0.0) or 0.0), g.dpi)
            x = spine_center - text_img.width // 2 + offset_x
            y += offset_y
            if key == "regular":
                y -= text_img.height
            img.paste(text_img, (x, y), text_img)

    def add_back(
        self,
        img: Image.Image,
        draw: ImageDraw.ImageDraw,
        art_path: Path,
        headshot_path: Path | None,
    ) -> None:
        g = self.g
        if g.back_left < g.spine_left:
            back_box = (0, 0, g.spine_left, g.total_h)
        else:
            back_box = (g.spine_right, 0, g.total_w, g.total_h)
        draw.rectangle(back_box, fill=self.colors["spine"])

        x = g.back_left + g.safe
        y = g.trim_top + px(0.5, g.dpi)
        max_w = g.front_w - g.safe * 2
        barcode_top = g.trim_bottom - px(1.7, g.dpi)

        blurb = str(self.data.get("blurb", "")).strip()
        if blurb:
            blurb_offset_x = px(float(self.binding_value("back_blurb_offset_x_inches", 0.0) or 0.0), g.dpi)
            blurb_offset_y = px(float(self.binding_value("back_blurb_offset_y_inches", 0.0) or 0.0), g.dpi)
            blurb_font = self.font("regular", 43)
            y = self.draw_wrapped(
                draw,
                blurb,
                (x + blurb_offset_x, y + blurb_offset_y),
                blurb_font,
                self.colors["text"],
                max_w,
                55,
                34,
                max_y=barcode_top - px(0.15, g.dpi),
            )

        quote = str(self.data.get("quote", "")).strip()
        if quote:
            quote_offset_x = px(float(self.binding_value("back_quote_offset_x_inches", 0.0) or 0.0), g.dpi)
            quote_offset_y = px(float(self.binding_value("back_quote_offset_y_inches", 0.0) or 0.0), g.dpi)
            quote_center_x = g.back_left + g.front_w // 2 + quote_offset_x
            quote_font = self.fit_font(draw, quote, "italic", 38, max_w)
            y += px(0.14, g.dpi)
            y = self.draw_centered(
                draw,
                quote,
                quote_center_x,
                y + quote_offset_y,
                quote_font,
                self.colors["gold_light"],
            )
            attribution = str(self.data.get("quote_attribution", "")).strip()
            if attribution:
                attribution_offset_x = px(
                    float(self.binding_value("back_quote_attribution_offset_x_inches", 0.0) or 0.0),
                    g.dpi,
                )
                attribution_offset_y = px(
                    float(self.binding_value("back_quote_attribution_offset_y_inches", 0.0) or 0.0),
                    g.dpi,
                )
                y += px(0.09, g.dpi)
                y = self.draw_centered(
                    draw,
                    attribution if attribution.startswith("-") else f"- {attribution}",
                    quote_center_x + attribution_offset_x,
                    y + attribution_offset_y,
                    self.font("regular", 30),
                    self.colors["muted"],
                )

        photo_size = px(1.18, g.dpi)
        photo_gap = px(0.24, g.dpi)
        photo = None
        if headshot_path and headshot_path.exists():
            photo = Image.open(headshot_path).convert("RGB")
            min_dim = min(photo.size)
            left = (photo.width - min_dim) // 2
            top = (photo.height - min_dim) // 2
            photo = photo.crop((left, top, left + min_dim, top + min_dim))
            photo = photo.resize((photo_size, photo_size), Image.LANCZOS)

        photo_offset_x = px(float(self.binding_value("back_author_image_offset_x_inches", 0.0) or 0.0), g.dpi)
        photo_offset_y = px(float(self.binding_value("back_author_image_offset_y_inches", 0.0) or 0.0), g.dpi)
        photo_x = x + photo_offset_x
        photo_y = g.trim_bottom - g.safe - photo_size + photo_offset_y
        if photo:
            img.paste(photo, (photo_x, photo_y))

        bio = str(self.data.get("author_bio", "")).strip()
        if not bio:
            return
        bio_font = self.font("regular", 32)
        bio_offset_x = px(float(self.binding_value("back_author_bio_offset_x_inches", 0.0) or 0.0), g.dpi)
        bio_offset_y = px(float(self.binding_value("back_author_bio_offset_y_inches", 0.0) or 0.0), g.dpi)
        bio_paragraph_gap = px(float(self.binding_value("back_author_bio_paragraph_gap_points", 8.0) or 0.0) / 72, g.dpi)
        bio_y = max(y + px(0.35, g.dpi), g.trim_bottom - px(2.5, g.dpi)) + bio_offset_y
        bio_max_y = min(g.trim_bottom - g.safe, photo_y - photo_gap if photo else g.trim_bottom - g.safe)

        self.draw_wrapped(
            draw,
            bio,
            (x + bio_offset_x, bio_y),
            bio_font,
            self.colors["muted"],
            max_w,
            43,
            bio_paragraph_gap,
            max_y=bio_max_y,
        )

    def add_guides(self, draw: ImageDraw.ImageDraw) -> None:
        g = self.g
        guide = (255, 255, 255)
        x_offset = px(float(self.data.get("guide_x_offset_inches", 0.0) or 0.0), g.dpi)
        for x in [g.back_left, g.back_right, g.spine_left, g.spine_right, g.front_left, g.front_right]:
            x += x_offset
            if 0 <= x < g.total_w:
                draw.line([(x, 0), (x, g.total_h)], fill=guide, width=2)
        for y in [g.trim_top, g.trim_bottom]:
            draw.line([(0, y), (g.total_w, y)], fill=guide, width=2)

    def generate(self, include_guides: bool = False) -> dict[str, Path]:
        art_path = resolve_path(str(self.data["front_cover_image"]))
        if not art_path.exists():
            raise FileNotFoundError(f"Missing front cover background image: {art_path}")
        self.colors["spine"] = resolve_spine_color(self.data.get("spine_color", "auto"), art_path)
        headshot_value = str(self.data.get("author_photo", "")).strip()
        headshot_path = resolve_path(headshot_value) if headshot_value else None

        g = self.g
        img = Image.new("RGB", (g.total_w, g.total_h), self.colors["background"])
        draw = ImageDraw.Draw(img)
        self.add_back(img, draw, art_path, headshot_path)
        self.add_front(img, draw, art_path)
        self.add_spine(img, draw)
        if include_guides:
            self.add_guides(draw)

        suffix = "hc" if str(self.data["binding_type"]) == "hc" else "pb"
        wrap_png = HERE / f"{repo_name()}-{suffix}-cover.png"
        wrap_pdf = HERE / f"{repo_name()}-{suffix}-cover.pdf"
        front_jpg = HERE / f"{repo_name()}-{suffix}-kindle.jpg"
        latest_front_jpg = HERE / f"{repo_name()}-kindle.jpg"

        img.save(wrap_png, "PNG", dpi=(g.dpi, g.dpi))

        front_crop = img.crop((g.front_left, g.trim_top, g.front_right, g.trim_bottom))
        front_crop.save(front_jpg, "JPEG", quality=95, dpi=(g.dpi, g.dpi), optimize=True)
        if self.data.get("kindle_write_latest", True):
            front_crop.save(latest_front_jpg, "JPEG", quality=95, dpi=(g.dpi, g.dpi), optimize=True)

        pdf_w = g.total_w_inches * 72
        pdf_h = g.total_h_inches * 72
        buf = io.BytesIO()
        img.save(buf, format="PNG", dpi=(g.dpi, g.dpi))
        buf.seek(0)
        pdf = canvas.Canvas(str(wrap_pdf), pagesize=(pdf_w, pdf_h))
        pdf.drawImage(ImageReader(buf), 0, 0, width=pdf_w, height=pdf_h)
        pdf.save()
        outputs = {"pdf": wrap_pdf, "png": wrap_png, "jpg": front_jpg}
        if self.data.get("kindle_write_latest", True):
            outputs["latest_jpg"] = latest_front_jpg
        return outputs


def normalize_loaded_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    aliases = {
        "hardcover": "hc",
        "paperback": "pb",
        "left_to_right": "ltr",
        "right_to_left": "rtl",
    }
    for key in ["binding_type", "reading_direction", "interior_type", "paper_type"]:
        if key in normalized:
            value = clean_key(str(normalized[key]))
            normalized[key] = aliases.get(value, value)
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an interactive print-ready cover.")
    parser.add_argument(
        "metadata",
        nargs="?",
        default=str(DEFAULT_METADATA),
        help="Markdown file with YAML frontmatter defaults.",
    )
    parser.add_argument("--non-interactive", action="store_true", help="Use existing metadata only.")
    parser.add_argument("--guides", action="store_true", help="Draw trim/spine guide lines on outputs.")
    args = parser.parse_args(argv)

    metadata_path = Path(args.metadata).expanduser()
    if not metadata_path.is_absolute():
        metadata_path = (PROJECT_ROOT / metadata_path).resolve()

    data, body = read_frontmatter(metadata_path)
    data = normalize_loaded_data(data)
    if not args.non_interactive:
        data = interactive_metadata(metadata_path, data)
        write_metadata(metadata_path, data, body)
        print(f"\nSaved metadata defaults to {metadata_path}")

    geometry = calculate_geometry(data)
    print(
        f"Generating {BINDING_OPTIONS[geometry.binding_type]} cover "
        f"({geometry.total_w_inches:.4f} x {geometry.total_h_inches:.4f} in, "
        f"spine {geometry.spine_inches:.4f} in)."
    )
    outputs = CoverGenerator(data, geometry).generate(include_guides=args.guides)
    for label, path in outputs.items():
        print(f"Wrote {label.upper()}: {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCanceled.", file=sys.stderr)
        raise SystemExit(130)
    except CoverError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
