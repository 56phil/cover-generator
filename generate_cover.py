#!/usr/bin/env python3
"""Command entrypoint for Cover Studio exports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cover_engine.commands import metadata_report, render_preview, validate_json
from cover_engine.legacy import (
    BINDING_OPTIONS,
    CoverError,
    CoverGenerator,
    DEFAULT_METADATA,
    calculate_geometry,
    interactive_metadata,
    repo_name,
    set_project_context,
)
from cover_engine.metadata import load_metadata, save_metadata
from cover_engine.validation import validate_cover

PROJECT_ROOT = Path.cwd()


def resolve_metadata(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a print-ready book cover.")
    parser.add_argument(
        "metadata",
        nargs="?",
        default=str(DEFAULT_METADATA),
        help="Markdown file with YAML frontmatter defaults.",
    )
    parser.add_argument("--non-interactive", action="store_true", help="Use existing metadata only.")
    parser.add_argument("--guides", action="store_true", help="Draw trim/spine guide lines on outputs.")
    parser.add_argument("--validate-json", action="store_true", help="Print validation and geometry JSON.")
    parser.add_argument("--export-json", action="store_true", help="Print generated output paths as JSON.")
    parser.add_argument("--preview", metavar="PNG", help="Write a quick PNG preview for app/native UI use.")
    parser.add_argument("--preview-width", type=int, default=1200, help="Preview width in pixels.")
    args = parser.parse_args(argv)

    metadata_path = resolve_metadata(args.metadata)
    set_project_context(metadata_path)

    if args.validate_json:
        print(validate_json(metadata_path))
        return 0

    if args.preview:
        output_path = Path(args.preview).expanduser()
        if not output_path.is_absolute():
            output_path = (PROJECT_ROOT / output_path).resolve()
        preview = render_preview(metadata_path, output_path, args.preview_width, args.guides)
        print(json.dumps({"preview": str(preview)}, indent=2, sort_keys=True))
        return 0

    data, body = load_metadata(metadata_path)
    if not args.non_interactive:
        data = interactive_metadata(metadata_path, data)
        save_metadata(metadata_path, data, body)
        print(f"\nSaved metadata defaults to {metadata_path}")

    issues = validate_cover(data, metadata_path)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        if args.export_json:
            print(json.dumps(metadata_report(metadata_path), indent=2, sort_keys=True))
        else:
            for issue in errors:
                print(f"Error: {issue.field}: {issue.message}", file=sys.stderr)
        return 2

    geometry = calculate_geometry(data)
    print(
        f"Generating {BINDING_OPTIONS[geometry.binding_type]} cover "
        f"({geometry.total_w_inches:.4f} x {geometry.total_h_inches:.4f} in, "
        f"spine {geometry.spine_inches:.4f} in)."
    )
    outputs = CoverGenerator(data, geometry).generate(include_guides=args.guides)
    if args.export_json:
        payload = metadata_report(metadata_path)
        payload["outputs"] = {label: str(path) for label, path in outputs.items()}
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
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
