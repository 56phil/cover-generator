from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from .legacy import BINDING_OPTIONS, CoverGenerator, calculate_geometry, repo_name, set_project_context
from .metadata import load_metadata
from .validation import validate_cover


def issue_summary(issues: list[Any]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def metadata_report(metadata_path: Path) -> dict[str, Any]:
    set_project_context(metadata_path)
    data, _ = load_metadata(metadata_path)
    issues = validate_cover(data, metadata_path)
    geometry = None
    if not any(issue.severity == "error" for issue in issues):
        geometry = calculate_geometry(data)
    return {
        "project": repo_name(),
        "binding": data.get("binding_type"),
        "binding_label": BINDING_OPTIONS.get(data.get("binding_type"), data.get("binding_type")),
        "geometry": None
        if geometry is None
        else {
            "total_width_inches": geometry.total_w_inches,
            "total_height_inches": geometry.total_h_inches,
            "front_width_inches": geometry.front_w_inches,
            "front_height_inches": geometry.front_h_inches,
            "spine_width_inches": geometry.spine_inches,
            "dpi": geometry.dpi,
            "total_width_px": geometry.total_w,
            "total_height_px": geometry.total_h,
        },
        "issues": [issue.as_dict() for issue in issues],
        "issue_summary": issue_summary(issues),
    }


def validate_json(metadata_path: Path) -> str:
    return json.dumps(metadata_report(metadata_path), indent=2, sort_keys=True)


def render_preview(metadata_path: Path, output_path: Path, width_px: int = 1200, guides: bool = False) -> Path:
    set_project_context(metadata_path)
    data, _ = load_metadata(metadata_path)
    geometry = calculate_geometry(data)
    outputs = CoverGenerator(data, geometry).generate(include_guides=guides)
    source = outputs["png"]
    image = Image.open(source).convert("RGB")
    ratio = width_px / image.width
    preview = image.resize((width_px, round(image.height * ratio)), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path, "PNG", optimize=True)
    return output_path
