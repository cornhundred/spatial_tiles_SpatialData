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
| 11 | images, 8-bit | `images/<ch>/` WebP | — | ➖ **default**, via `celldega.pre` |
| 12 | images, 16-bit | — | OME-Zarr via viv's loader | 🟢 opt-in, WebP still default |
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

## 16-bit images via viv (row 12) — done, opt-in

**Correction.** An earlier version of this note claimed viv could not open SpatialData's
images because it only understood the NGFF 0.4 layout. That was wrong. `loadOmeZarr`
unwraps 0.5 explicitly:

```js
const ngff_v0_5_or_later = "ome" in unknownAttrs;
const rootAttrs = ngff_v0_5_or_later ? unknownAttrs.ome : unknownAttrs;
```

The probe that "proved" the incompatibility was passing a zarrita `Location` where
`loadOmeZarr` expects a **URL string**, which produces a broken store and an unrelated
`TypeError`. Corrected, it reads the store fine:

```
resolutions : 5        base shape : 4,13770,34155 Uint16
channels    : DAPI, ATP1A1/CD45/E-Cadherin, 18S, AlphaSMA/Vimentin   (from `omero`)
getTile L4  : 2134x860 in 46 ms
getTile L0  : 4096x4096 in 64 ms
```

Channel names come free from `omero` — exactly the `image_info` the profile writes by hand.

Only `@vivjs/loaders` is used, never `@vivjs/layers`: the layers peer-require deck.gl
`~9.3.3` against celldega's 9.0.35, while the loader has **no deck.gl dependency**. Tiles
become ImageBitmaps, so the existing `TileLayer`, channel colours and intensity slider are
untouched.

### Why WebP stays the default

| | canonical OME-Zarr | WebP pyramid |
|---|---|---|
| all 4 channels | **2.9 GB** | **25 MB** |
| one full-res chunk | 16.2 MB | — |
| one channel, whole pyramid | — | 5.4–7.5 MB |
| tile size | 4096 px (set by chunking) | ~512 px |

A single full-resolution chunk costs more than an entire channel's WebP pyramid, and the
uint16 store is **116×** larger overall. This path buys true 16-bit windowing, not speed.
For 8-bit speed against a SpatialData store, generate the WebP pyramid — which is what
`celldega.pre` already does.

The coarse chunking is a *writer* setting, so a viewer-friendly `1 × 1024 × 1024` option
would narrow the gap if 16-bit ever becomes the common path. It does not change the 116×.

---

## Also not free: `obs` is not a viewer schema

Beyond colours, `celldega.pre` computes gene stats today. `obs`/`var` give names and values
but no derived statistics, so that logic moves into the Celldega reader. Small, but it is
the `df_sig.parquet` gap resurfacing in a new place.

---

## What this removes from the spatialdata-io PR

There is **no two-step here**, and no need to ship code we plan to delete. The profile has
never worked against released Celldega: `main` hardcodes `table.getChild('geometry')`, so
reading `display_xy` needs `89c0ef3` at minimum, plus the List-vertex fix and the removal
of the parquet-wasm projection. The spatialdata-io PR already depends on an unreleased
Celldega.

So the only ordering constraint is *within Celldega* — the adapt work has to land in the
same release as the reader work, which is how the branches are already stacked. Given that,
the spatialdata-io PR can be **born** in its simplified form, and these writers need never
be proposed at all:

| removed | lines |
|---|---|
| `cbg_parquet.py` (whole module) | 181 |
| `webp_parquet.py` (whole module) — images now read natively | 322 |
| `write_cell_metadata` in `shapes_parquet.py` | 57 |
| `to_frame` + `_expression_stats` in `feature_catalog.py` | 92 |
| `_write_cell_clusters`, `_write_micron_to_image_transform` + call sites | ~50 |
| `test_cbg_parquet.py`, `test_webp_parquet.py`, assertions elsewhere | ~550 |
| **added back**: `var["color"]` and `uns["<col>_colors"]` writers | +50 |
| **net** | **≈ −1,200 of 4,264 (~28%)** |

None of it is written-then-deleted: it simply never enters the PR.

What is left is exactly the surgical addition worth proposing:

```
regular_grid.py     247   tile math
points_parquet.py   559   display points + row grouping
shapes_parquet.py   269   display geometry + row grouping
feature_catalog.py  177   stable feature ordering
manifest.py         192   what was written, and how
tiled_access.py    ~350   the two entry points
tests             ~1,270
```

That is **row groups over the canonical data, plus the display Parquets** — a general
mechanism for spatial tiling that happens to make Celldega fast, rather than SpatialData
learning a viewer's file formats. The change in what the PR *is* matters more than the 28%.

Dropping the WebP writer is possible only because images now read natively. Anyone wanting
8-bit speed against a SpatialData store generates the pyramid with `celldega.pre`, which
already does exactly that — it does not need to live in spatialdata-io.

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
