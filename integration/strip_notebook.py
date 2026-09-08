#!/usr/bin/env python
"""Strip saved widget state and outputs from notebooks before committing.

`jupyter nbconvert --clear-output` is not enough here. With CELLDEGA_LOCAL_ESM set,
anywidget inlines the front-end bundle into each widget's state, and ipywidgets persists
that under the notebook's top-level `metadata.widgets` -- which --clear-output leaves
untouched. A four-widget notebook reached 226 MB, of which 225.9 MB was `metadata.widgets`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat


def strip(path: Path) -> tuple[int, int]:
    before = path.stat().st_size
    nb = nbformat.read(path, as_version=4)
    nb.metadata.pop("widgets", None)
    for cell in nb.cells:
        if cell.cell_type == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    nbformat.write(nb, path)
    return before, path.stat().st_size


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv]
    if not paths:
        print(__doc__)
        print("usage: strip_notebook.py NOTEBOOK [NOTEBOOK ...]")
        return 2
    for p in paths:
        before, after = strip(p)
        print(f"{p}: {before / 1e6:.1f} MB -> {after / 1e6:.3f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
