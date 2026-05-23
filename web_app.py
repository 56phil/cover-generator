#!/usr/bin/env python3
"""Local browser app for Cover Studio."""

from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import secrets
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from cover_engine.commands import metadata_report, render_preview
from cover_engine.legacy import CoverError, CoverGenerator, calculate_geometry, set_project_context
from cover_engine.metadata import load_metadata, metadata_to_yaml, save_metadata
from cover_engine.validation import validate_cover

APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "web_static"


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def coerce_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if value is None:
        return ""
    text = str(value)
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    for parser in (int, float):
        try:
            if parser is int and "." in text:
                continue
            return parser(text)
        except ValueError:
            pass
    return text


class CoverStudioServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], project_root: Path, metadata_path: Path) -> None:
        super().__init__(address, CoverStudioHandler)
        self.project_root = project_root.resolve()
        self.metadata_path = metadata_path.resolve()


class CoverStudioHandler(BaseHTTPRequestHandler):
    server: CoverStudioServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_file(STATIC_ROOT / "index.html")
            elif parsed.path.startswith("/static/"):
                self.send_file(STATIC_ROOT / parsed.path.removeprefix("/static/"))
            elif parsed.path == "/api/project":
                self.send_json(
                    {
                        "project_root": str(self.server.project_root),
                        "metadata_path": str(self.server.metadata_path),
                    }
                )
            elif parsed.path == "/api/load":
                self.send_json(self.load_payload())
            elif parsed.path == "/api/preview":
                self.handle_preview(parsed.query)
            elif parsed.path == "/api/file":
                self.handle_file(parsed.query)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/save":
                self.handle_save()
            elif parsed.path == "/api/export":
                self.handle_export()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def request_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_file(self, path: Path) -> None:
        resolved = path.resolve()
        if not str(resolved).startswith(str(STATIC_ROOT.resolve())) and resolved != STATIC_ROOT / "index.html":
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        data = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def load_payload(self) -> dict[str, Any]:
        set_project_context(self.server.metadata_path)
        data, body = load_metadata(self.server.metadata_path)
        report = metadata_report(self.server.metadata_path)
        return {
            "data": data,
            "yaml": metadata_to_yaml(data),
            "body": body,
            "report": report,
        }

    def handle_save(self) -> None:
        payload = self.request_json()
        set_project_context(self.server.metadata_path)
        current, body = load_metadata(self.server.metadata_path)
        updates = payload.get("data", {})
        if not isinstance(updates, dict):
            raise CoverError("Save payload must include a data object.")
        for key, value in updates.items():
            current[key] = coerce_value(value)
        save_metadata(self.server.metadata_path, current, body)
        self.send_json(self.load_payload())

    def handle_preview(self, query: str) -> None:
        params = parse_qs(query)
        width = int(params.get("width", ["1100"])[0])
        guides = params.get("guides", ["false"])[0].lower() == "true"
        preview_name = f"preview-{secrets.token_hex(4)}.png"
        preview_path = self.server.project_root / "cover" / ".preview" / preview_name
        render_preview(self.server.metadata_path, preview_path, width_px=width, guides=guides)
        self.send_json({"url": f"/api/file?path={preview_path}", "path": str(preview_path)})

    def handle_export(self) -> None:
        set_project_context(self.server.metadata_path)
        data, _ = load_metadata(self.server.metadata_path)
        issues = validate_cover(data, self.server.metadata_path)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            self.send_json(
                {"issues": [issue.as_dict() for issue in issues]},
                HTTPStatus.BAD_REQUEST,
            )
            return
        geometry = calculate_geometry(data)
        outputs = CoverGenerator(data, geometry).generate()
        payload = metadata_report(self.server.metadata_path)
        payload["outputs"] = {label: str(path) for label, path in outputs.items()}
        self.send_json(payload)

    def handle_file(self, query: str) -> None:
        params = parse_qs(query)
        raw_path = params.get("path", [""])[0]
        path = Path(raw_path).expanduser().resolve()
        cover_root = (self.server.project_root / "cover").resolve()
        if not str(path).startswith(str(cover_root)):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local browser cover studio.")
    parser.add_argument("metadata", nargs="?", default="cover/cover.md")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail instead of trying the next port when the requested port is already in use.",
    )
    parser.add_argument("--open-browser", action="store_true", help="Open the studio in the default browser.")
    args = parser.parse_args(argv)

    project_root = Path.cwd().resolve()
    metadata_path = resolve_path(args.metadata, project_root)
    set_project_context(metadata_path)
    port = args.port
    while True:
        try:
            server = CoverStudioServer((args.host, port), project_root, metadata_path)
            break
        except OSError as exc:
            if args.strict_port or exc.errno != errno.EADDRINUSE:
                raise
            print(f"Port {port} is already in use; trying {port + 1}.")
            port += 1

    url = f"http://{args.host}:{port}"
    print(f"Cover Studio running at {url}")
    print(f"Project: {project_root}")
    print(f"Metadata: {metadata_path}")
    if args.open_browser:
        webbrowser.open(url)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
