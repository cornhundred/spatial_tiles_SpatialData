# What we are proposing

Two separable things, in two repos. **The SpatialData library itself needs no change** —
what follows are store conventions written by spatialdata-io, plus reader code in Celldega.

---

## 1. Store conventions (written by spatialdata-io, read by anyone)

These are additions to what a store *contains*. Each is plain Zarr/Parquet/AnnData that
round-trips, and each is independently useful.

| # | addition | where | why it is not viewer-specific |
|---|---|---|---|
| 1 | **row groups aligned to a tile grid** | `points/*/points.parquet`, `shapes/*/shapes.parquet` | a spatial index. A 20-tile read is ~8 ms on 8 M transcripts and ~10 ms on 74 M, from Python, with no viewer involved |
| 2 | **display Parquets** | `visualization/grid_files_v1/{trx,cell_seg}/` | render-ready encoding: float32 interleaved coordinates and integer feature codes, same row grouping |
| 3 | **gene-major `X`** | `tables/table/layers/X_csc` | reading one gene from CSR touches every chunk. Also what any per-gene analysis wants |
| 4 | **per-gene statistics** | `var["mean"|"std"|"max"|"non_zero"]` | a gene list without reading the matrix. Ordinary `var` columns |
| 5 | **gene colours** | `uns["gene_colors"]` | AnnData's existing `<name>_colors` convention, in `var_names` order |
| 6 | **cluster palettes** | `uns["<column>_colors"]` | the existing scanpy convention, followed exactly |
| 7 | **a manifest** | `visualization/grid_files_v1/landscape_parameters.json` | records the grid, the display files, and the feature ordering |

Only the **row grouping (1)** touches canonical data, and only by reordering rows — which is
meaningless for a point cloud. Everything else is additive. Delete `visualization/` and the
store is unchanged.

### No new conventions

An earlier draft put gene colours in a `var["color"]` column, which would have been a new
convention. They now go to `uns["gene_colors"]`, matching the `<name>_colors` lists AnnData
already uses — the same shape scanpy writes for obs categoricals, just ordered by
`var_names` instead of by category. Nothing here asks a reader to learn a new idea.

### Why the tile grid lives in two places

The grid is recorded in the canonical Parquet's own schema metadata (`tile_grid`,
`storage_mode`, `max_row_groups_per_file`) *and* in the manifest. The first makes the
canonical file self-describing to a Python reader; the second is what a browser reads before
fetching anything. Longer term the manifest could go entirely and a client could discover
everything from the elements themselves.

---

## 2. New code in spatialdata-io

3,434 lines on `adapt_dega`, of which 1,981 is source and 1,471 tests.

| module | lines | what |
|---|---|---|
| `points_parquet.py` | 559 | display points + tile row grouping, with a spill-to-disk path above ~20 M rows |
| `tiled_access.py` | 303 | the two entry points: `add_spatial_tiling`, `xenium_spatially_tiled` |
| `shapes_parquet.py` | 266 | display geometry + the same row grouping |
| `regular_grid.py` | 247 | the tile math everything else builds on |
| `manifest.py` | 206 | assemble and validate the manifest |
| `expression_index.py` | 197 | `var` statistics + the gene-major layer, chunked per gene |
| `feature_catalog.py` | 185 | stable feature ordering — genes in `var` order, controls after |
| `display_colors.py` | 80 | the palette for (5) and (6) |

**Not in spatialdata-io, deliberately:**

- the WebP pyramid (moved to `celldega.pre.spatialdata_images`) — an 8-bit lossy pyramid is
  a viewer artefact, ~100× smaller than the canonical image it derives from
- the CBG Parquet, `meta_gene.parquet`, `cell_metadata.parquet`, `cell_clusters/`,
  `micron_to_image_transform.csv` — all now read from the store itself

---

## 3. New code in Celldega

`js/spatialdata/` reads the store directly with zarrita, and
`celldega.pre.spatialdata_images` makes the 8-bit pyramid from a store. The reader builds
Arrow tables with the schemas Celldega already consumed, so the rendering path is unchanged.

Opt-in per component through the manifest's `spatialdata` block; a manifest without one
behaves exactly as before, which is what keeps DegaFiles working.

---

## What this costs

Measured on Xenium pancreas (8.1 M transcripts, 377 genes) and Prime skin (74 M, 5,006).

### On disk, measured on the rebuilt stores

| | pancreas | skin |
|---|---|---|
| table, before → after | 7.9 MB → 17 MB | 58 MB → 162 MB |
| profile dir, before → after | 140 MB → 100 MB | 600 MB → 415 MB |
| **whole store** | **3.3 GB → 3.3 GB** | **5.1 GB → 5.1 GB** |

The store does not grow. The gene-major layer costs 104 MB for skin against 55 MB for `X`
itself — **1.9×**, not 1×, because chunking for single-gene reads compresses worse than
chunking for whole-matrix reads. That is the tunable: `genes_per_chunk` defaults to 2, and
raising it trades read cost for storage. Even so the layer is smaller than the 150 MB CBG
Parquet it replaces, and the profile directory shrinks by more than the table grows.

Tiling the canonical points still costs +39.8% over an equivalently-compressed untiled
store — fragmentation, not the extra columns.

### In the browser, measured against the rebuilt stores

| | pancreas (2.6 M nnz) | skin (33.3 M nnz) |
|---|---|---|
| gene list | 0.017 MB | 0.126 MB |
| one gene | 0.084 MB | 0.060 MB |
| *whole matrix, the old way* | *4.5 MB* | *54.8 MB* |

A 12.8× larger matrix does not cost 12.8× more per gene: the cost tracks non-zeros **per
gene**, which is roughly constant across datasets.
