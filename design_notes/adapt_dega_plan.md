# `adapt_dega`: Celldega reads SpatialData natively

The first branches made **SpatialData produce what Celldega reads**. These branches invert
it: **Celldega reads what SpatialData already writes**, and the derived profile shrinks to
only what Zarr genuinely cannot serve — or what we deliberately choose to keep custom.

| repo | branch | base |
|---|---|---|
| celldega | `adapt_dega` | `feat/spatialdata-regular-grid-reader` |
| spatialdata-io | `adapt_dega` | `feat/xenium-celldega-regular-grid` |
| spatialdata | — | no change expected, again |

The branches start identical to their parents, so the working four-Landscape demo still runs
from either.

---

## Running tally

`🟢` built + validated against a real store, not yet wired into the viewer ·
`🔨` still to build · `➖` stays custom on purpose · `⏸` deferred

| # | component | today | native source | status |
|---|---|---|---|---|
| 1 | gene names | `meta_gene.parquet` | `tables/table/var/_index` | 🟢 |
| 2 | gene stats (mean, std, max) | `meta_gene.parquet` | computed from `X` | 🟢 |
| 3 | **gene colours** | `meta_gene.parquet` | **new** `var["color"]` | 🟢 reader (fallback palette) · 🔨 writer |
| 4 | cell names | `cell_metadata.parquet` | `tables/table/obs/_index` | 🟢 |
| 5 | cell centroids | `cell_metadata.parquet` | `tables/table/obsm/spatial` | 🟢 |
| 6 | other cell metadata | — | `obs/*`, incl. categoricals | 🟢 |
| 7 | cluster assignments | `cell_clusters/` | `obs` categorical column | 🟢 |
| 8 | **cluster palettes** | `cell_clusters/` | `uns["<col>_colors"]` (scanpy convention) | 🟢 reader · 🔨 writer |
| 9 | cell × gene | `cbg/chunk_N.parquet` | `tables/table/X` (CSR) | 🟢 |
| 10 | µm→px transform | `micron_to_image_transform.csv` | NGFF `coordinateTransformations` | 🟢 |
| — | **wire 1–10 into the viewer** | — | — | 🔨 next |
| 11 | images, 8-bit | `images/<ch>/` WebP | — | ➖ **keep as-is** |
| 12 | images, 16-bit | — | OME-Zarr + viv | ⏸ deferred |
| 13 | transcripts | `trx/chunk_NN.parquet` | — | ➖ **keep as-is** |
| 14 | cell boundaries | `cell_seg/chunk_NN.parquet` | — | ➖ **keep as-is** |
| 15 | manifest | `landscape_parameters.json` | kept, gains a `spatialdata` block | ➖ **keep** |

Rows 1–10 are implemented in celldega `js/spatialdata/` and validated against the real
pancreas store: the derived gene statistics match the Python-written `meta_gene.parquet`
exactly, and a warm gene column costs ~5 ms. What remains is wiring them into
`landscape_ist.js` behind the manifest's `spatialdata` block.

Rows 1–10 delete files from `grid_files_v1`. Rows 11–14 are the deliberate middle ground:
**8-bit WebP images and the custom display Parquets stay.** After rows 1–10 land, the
profile is just `trx/`, `cell_seg/`, `images/` and a much smaller manifest.

### What spatialdata-io has to *add* (not just delete)

- `var["color"]` — hex per gene (row 3)
- `uns["<col>_colors"]` — palette per categorical obs column (row 8)
- *(optional, later)* a CSC copy of `X` in `layers/` (see below)
- *(optional, later)* viewer-friendly image chunking, only if 16-bit is ever pursued

---

## On gene colours

There is no biologically correct gene colour, so these are invented either way. The question
is only where they live.

Writing them to `var["color"]` is the better answer, for the same reason the rest of this
project avoids viewer-only files: a `var` column round-trips through AnnData, is visible to
scanpy and any other tool, and survives a re-read. A colour table stashed in the manifest
would be invisible to everything except Celldega. It is a small mutation — `var` gains one
string column and the 7.9 MB table is rewritten via
`sdata.write_element("table", overwrite=True)`.

Worth being explicit that this is a **new convention** — AnnData has `uns["<col>_colors"]`
for *obs* categoricals but nothing for genes — so it should be proposed as such rather than
assumed. Cluster palettes (row 8) are different: `uns["<col>_colors"]` is the existing
scanpy convention and we should just follow it.

---

## Feasibility, measured

Probes in [`integration/probes/`](../integration/probes/), run against the real
`pancreas_full.zarr`. That store is **Zarr v3**, every array zstd-compressed, strings encoded
`vlen-utf8`, images declaring `ome.version = "0.5-dev-spatialdata"`.

`zarrita@0.7.5` read every piece with **no codec registration and no shims**:

```
root group                            OK
tables/table/var/_index               OK  ["ABCC11","ACE2","ACKR1","ACTA2","ACTG2"]  (vlen-utf8 + zstd)
tables/table/obs/region               OK  categorical: codes int8 + categories
tables/table/obsm/spatial             OK  140702x2 float64 -> centroids
tables/table/X/{data,indices,indptr}  OK  csr_matrix, float32/int32
images/morphology_focus/s3            OK  4x1721x4269 uint16 -> 256x256 window in 86 ms
```

### The one real design decision: CSR vs CSC

`X` is **CSR** (cell-major). Gene colouring needs a *column*. Fetching a column from CSR
touches every chunk, i.e. the whole matrix:

| | cells | genes | nnz | `X` on disk (zstd) | current gene-major CBG |
|---|---|---|---|---|---|
| pancreas | 140,702 | 377 | 2.6 M | **4.5 MB** | 11.9 MB |
| skin | 112,551 | 5,006 | 33.3 M | **54.8 MB** | 150.3 MB |

The CSR is *smaller* than the CBG Parquet it replaces — that Parquet pays for per-row gene
strings and row-group fragmentation.

**Recommendation: load the whole `X` first.** Pure reader work, no writer change, ships a
working demo, and gives a real measurement of whether skin feels slow. If it does, add a
**CSC copy in `layers/`** — AnnData supports `csc_matrix` natively, and one gene becomes
`indptr[g]..indptr[g+1]`, a slice of one or two chunks (~6,600 nnz for skin). That is the
zarr-native equivalent of "one row group per gene" and is strictly additive.

---

## Deferred: 16-bit images via viv (row 12)

Not a goal in itself — the reason to do it at all is to avoid a WebP pyramid inflating the
store. Three obstacles, all measured, so the cost is known before anyone starts:

**viv 0.22.1 cannot open these images.** A layout mismatch, not a version string. Viv does
`if ("multiscales" in rootAttrs)` (`@vivjs/loaders/dist/index.mjs:1084`) — the NGFF **0.4**
top-level layout. SpatialData writes the **0.5** layout:

```
attrs keys        : ["ome", "spatialdata_attrs"]
attrs.ome keys    : ["version", "multiscales", "omero"]
attrs.multiscales : absent
```

`loadOmeZarr` falls through and throws
`TypeError: Cannot read properties of undefined (reading 'endsWith')`.

**Chunks are far too coarse.** `s0` is `1 × 4096 × 4096` uint16 = **33.5 MB per chunk per
channel** uncompressed. A 256×256 window at `s3` already costs 86 ms because it pulls a
whole 1×1721×4096 chunk. WebP tiles are ~512 px, which is why they feel fast.

**And a dependency bump.** `@vivjs/layers` peer-requires `~9.3.3` of `@deck.gl/core`,
`@luma.gl/*` and `@deck.gl/geo-layers`; celldega is on `^9.0.12`. Satisfiable, but
cross-cutting.

---

## Also not free: `obs` is not a viewer schema

Beyond colours, `celldega.pre` computes gene stats today. `obs`/`var` give names and values
but no derived statistics, so that logic moves into the Celldega reader. Small, but it is
the `df_sig.parquet` gap resurfacing in a new place.

---

## What this removes from the spatialdata-io PR

Only once Celldega ships the reader — until then the PR has to keep working against
released Celldega, so this is a follow-up, not an edit to the open PR.

| removed | lines |
|---|---|
| `cbg_parquet.py` (whole module) | 181 |
| `write_cell_metadata` in `shapes_parquet.py` | 57 |
| `to_frame` + `_expression_stats` in `feature_catalog.py` | 92 |
| `_write_cell_clusters`, `_write_micron_to_image_transform` + call sites | ~50 |
| `test_cbg_parquet.py` + the corresponding assertions elsewhere | ~300 |
| **added back**: `var["color"]` and `uns["<col>_colors"]` writers | +50 |
| **net** | **≈ −630 of 4,264 (~15%)** |

Fifteen percent, not fifty: the bulk of the PR is the display Parquets and the tile
machinery (`points_parquet.py` 559, `shapes_parquet.py` 269, `regular_grid.py` 247), all of
which stay, plus the WebP path (322 + 213 tests) which is deliberately kept.

The bigger effect is on what the PR *is*. Today it reads as "SpatialData learns Celldega's
file formats", which invites the obvious objection. After this it reads as "SpatialData
gains a spatial index over points and shapes, plus an image pyramid", with the viewer
reading canonical AnnData for everything else. That is a much easier conversation, and it
is worth more than the line count.

---

## Order of work

1. **`obs` / `var` / `obsm` reader** (rows 1, 2, 4, 5, 6, 7) — no blockers.
2. **CBG from `X`** (row 9) — whole-matrix CSR load; measure skin before considering CSC.
3. **Colours** (rows 3, 8) — writer side in spatialdata-io, reader side in Celldega.
4. **Transform** (row 10), then slim the manifest (row 15).
5. *(later)* optional 16-bit viv path (row 12), WebP retained as default.

---

## What stays true regardless

The canonical row-grouping in `points.parquet` / `shapes.parquet` is untouched by any of
this. It is not a viewer feature — it makes spatial subsetting cheap from Python — and it
remains the part of the proposal that stands on its own.
