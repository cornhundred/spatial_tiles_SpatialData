#!/usr/bin/env python
"""Serve a directory with Celldega's own local server, for range-read testing.

Uses `celldega.viz.local_server.get_local_server`, so byte-range behaviour under test is
the one Celldega actually ships rather than a stand-in. Note that `python -m http.server`
would not do: it ignores Range and answers with the whole file, which silently turns a
range benchmark into a full download.

    python integration/serve_celldega.py data 8897
"""

from __future__ import annotations

import os
import sys
import time
from http.server import ThreadingHTTPServer

from celldega.viz.local_server import CORSHTTPRequestHandler


def main(argv: list[str]) -> int:
    directory = argv[0] if argv else "."
    port = int(argv[1]) if len(argv) > 1 else 0
    os.chdir(directory)
    server = ThreadingHTTPServer(("127.0.0.1", port), CORSHTTPRequestHandler)
    print(f"serving {directory} on http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
