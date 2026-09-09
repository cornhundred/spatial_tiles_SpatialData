# Probes

Diagnostic scripts for the local `adapt_dega` work. Run the original feasibility probes
from this directory after `npm install` (zarrita and viv dependencies):

```bash
# From integration/probes, serve built stores with byte-range support:
../../.venv/bin/python --version  # use ../../integration/.venv/bin/python instead from workspace
```

From the workspace root, the existing store server can be started with:

```bash
integration/.venv/bin/python integration/serve_store.py --help
```

Check its options before selecting a store root/port. The feasibility scripts default to
`http://127.0.0.1:8896/pancreas_full.zarr`; `viv_probe.mjs` also accepts `IMAGE_URL`.
A plain `python -m http.server` suffices for full Zarr array requests but does not implement
the Parquet byte-range behavior needed for tiling benchmarks.

```bash
cd integration/probes
node zarrita_probe.mjs   # reads the tested Zarr v3 arrays and AnnData components
node viv_probe.mjs       # succeeds with a URL string, including nested NGFF 0.5 metadata
```

The earlier assertion that viv could not read SpatialData's nested `ome` metadata was
wrong: that probe passed a zarrita Location where viv expected a URL string.
`viv_shim_probe.mjs` is a retained historical experiment, not a required compatibility shim.
These probes print diagnostics; they are not browser rendering tests.

## Review reproductions (2026-09-09)

From the workspace root:

```bash
integration/.venv/bin/python integration/probes/review_adapt_dega.py
celldega/node_modules/.bin/esbuild integration/probes/review_adapt_dega.mjs \
  --bundle --platform=node --format=esm --outfile=/tmp/review-adapt-dega.mjs
node /tmp/review-adapt-dega.mjs
```

The Python script creates only temporary synthetic stores. It reports cell-instance
mapping, canonical column additions, save behavior, a no-table manifest, failure during
table rewrite, affine grid derivation, dense-tile row-group counts, gene palette reorder
and expression statistics. The JS script exercises the real adapter with controlled
store responses to show category-palette ordering and uint16-to-uint8 conversion.

These diagnostics cover both resolved behavior and deferred limitations. Expected/actual
differences identify the remaining limitation; they are not assertions that it should be
preserved. See [the review](../../design_notes/implementation_review.md).
