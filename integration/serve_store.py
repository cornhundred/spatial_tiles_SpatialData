#!/usr/bin/env python
"""Serve a SpatialData store over HTTP with byte-range and CORS support.

Parquet-WASM reads a file's footer and then individual row groups via HTTP range
requests, so a plain static server that ignores ``Range`` will make the viewer download
whole files (or fail outright). Python's ``http.server`` does not implement ranges, hence
this.

Usage::

    python serve_store.py --root ../data --port 8765

Then point Celldega at, for example::

    http://localhost:8765/pancreas_tiled.zarr/visualization/celldega_regular_grid_v1
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import re
import socketserver
import sys
from pathlib import Path

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

_CONTENT_TYPES = {
    ".parquet": "application/octet-stream",
    ".json": "application/json",
    ".zarray": "application/json",
    ".zattrs": "application/json",
    ".zgroup": "application/json",
    ".webp": "image/webp",
}


class RangeRequestHandler(http.server.SimpleHTTPRequestHandler):
    """A static handler that honours single-range ``Range`` requests and sets CORS."""

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802 - required name
        self.send_response(204)
        self.end_headers()

    def guess_type(self, path: str) -> str:
        suffix = Path(path).suffix
        if suffix in _CONTENT_TYPES:
            return _CONTENT_TYPES[suffix]
        # zarr v3 chunk files are extensionless; octet-stream is safer than text/html.
        return super().guess_type(path) or "application/octet-stream"

    def do_GET(self) -> None:  # noqa: N802 - required name
        header = self.headers.get("Range")
        if not header:
            super().do_GET()
            return

        match = _RANGE_RE.match(header.strip())
        path = self.translate_path(self.path)
        if not match or not os.path.isfile(path):
            super().do_GET()
            return

        size = os.path.getsize(path)
        start_s, end_s = match.groups()
        if start_s == "":
            # suffix form: 'bytes=-N' means the final N bytes, which is how a parquet
            # reader grabs the footer length.
            length = int(end_s or 0)
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)

        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return

        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()

        remaining = end - start + 1
        with open(path, "rb") as f:
            f.seek(start)
            while remaining > 0:
                chunk = f.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="directory to serve")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1

    handler = functools.partial(RangeRequestHandler, directory=str(root))
    with _Server((args.host, args.port), handler) as httpd:
        print(f"serving {root} at http://{args.host}:{args.port} (Range + CORS enabled)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
