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
| 5 | **gene colours** | `var["color"]` | ⚠️ **a new convention** — see below |
| 6 | **cluster palettes** | `uns["<column>_colors"]` | the existing scanpy convention, followed exactly |
| 7 | **a manifest** | `visualization/grid_files_v1/landscape_parameters.json` | records the grid, the display files, and the feature ordering |

Only the **row grouping (1)** touches canonical data, and only by reordering rows — which is
meaningless for a point cloud. Everything else is additive. Delete `visualization/` and the
store is unchanged.

### The one thing to flag in review

**`var["color"]` is a new convention.** AnnData has `uns["<column>_colors"]` for *obs*
categoricals but nothing for genes. It should be proposed as a convention rather than
slipped in. The alternative — a colour file in the profile directory — is worse, because it
would be invisible to every tool except the viewer that wrote it.

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
| `display_colors.py` | 78 | the palette for (5) and (6) |

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

| | |
|---|---|
| tiling the canonical points | +39.8% over an equivalently-compressed untiled store — fragmentation, not columns |
| the gene-major layer | a second copy of the non-zeros: 4.5 MB pancreas, 54.8 MB skin. Smaller than the 11.9 / 150.3 MB Parquet it replaces |
| a gene list, in the browser | 0.02 MB (was 4.5 MB) |
| one gene, in the browser | 0.048 MB (was 4.5 MB), and bounded by the gene rather than the matrix |
