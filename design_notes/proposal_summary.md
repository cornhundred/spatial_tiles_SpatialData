# What we are proposing

An opt-in extension for spatial access and visualization, implemented on the `adapt_dega_v2`
branches of spatialdata-io and Celldega. SpatialData core is currently unmodified. Stores
open with ordinary SpatialData; the extension is experimental and is not yet a ratified
SpatialData specification. See [the implementation review](implementation_review.md)
before treating the current code as a generic producer/consumer implementation.

## Store conventions

The proposal can be discussed as three primary storage capabilities:

1. Spatial row-group/chunk addressing for canonical Points and Shapes, with a generic root
   manifest that describes the grid, files, row groups, encodings and source elements.
2. GeoArrow encoding for canonical polygon Shapes, plus a positional `cell_code` that links
   visible boundaries to table rows.
3. A gene-major `layers/X_csc` representation alongside `X` for small per-gene reads.

Gene statistics and palettes support the client experience and also need documented
association rules. They are listed separately below rather than hidden inside the three
larger capabilities. None is yet a ratified SpatialData specification change.

| addition | location | purpose |
|---|---|---|
| spatial row groups | canonical Points and Shapes Parquet | compute tile-to-file/row-group addresses |
| viewer-readable points | canonical Points Parquet | adjacent `x`, `y`, `feature_name` columns; no display duplicate |
| viewer-readable polygons | canonical Shapes Parquet | `geoarrow.polygon` geometry plus integer `cell_code` |
| gene-major matrix copy | `tables/table/layers/X_csc` | small per-gene reads while retaining `X` in its original format |
| per-gene statistics | `var["mean", "std", "max", "non_zero"]` | populate gene controls without reading all of `X` |
| gene colors | `uns["gene_colors"]` | one hex color per gene, aligned with `var_names` |
| cluster palette | `uns["<column>_colors"]` | colors in categorical `obs` category order |
| manifest | root `zarr.json`, attribute `spatial_tiling` | grid, canonical paths, encodings, table location and feature ordering |

Canonical transcript coordinates and polygon geometries remain authoritative. Canonical
Points keep their source columns in a projection-friendly order; canonical Shapes gain a
positional `cell_code` column and use GeoArrow encoding without simplifying geometry. For raw
Xenium conversion, statistics and palettes are present in the initial table write and the
CSC buffers are tuned afterward, so the table is written once. Adding tiling to an existing
store still deletes and rewrites its table.

Canonical **Points and Shapes** are still written twice on the one-shot path: once by
`sdata.write()` and again by the tiling pass that reorders them into row groups and adds
the final encoding/index columns. Removing that would mean writing their final Parquet
layouts during the initial write. SpatialData already exposes a Shapes GeoArrow option,
but not the row-group/file controls or a Points writer override needed here. A small,
generic writer-options or prepared-writer hook in SpatialData core would allow
spatialdata-io to perform the sort once and publish the final Parquets directly. The
dropped [Points-only writer-hook patch](spatialdata-points-writer-hook.patch) demonstrates
the seam but would need to cover Shapes and stable public options before an upstream
proposal. The current double write costs conversion time and temporary I/O, not read
correctness.

The canonical layout creates no `visualization/` directory. An ordinary
`read_zarr(...).write(new_store)` preserves supported analysis content but does not promise
to preserve its tile row groups. Regenerate the profile after saving or changing source
data. The older `profile_layout="v1"` still produces display files for comparison.

## What needs standardization

The reusable part is a spatial access contract: coordinate system, grid extent and
numbering, tile-to-row-group mapping, source/instance associations, discovery, and
invalidation. Display encodings and gene-major access can be optional extensions.

The canonical root manifest contains the grid, row-group paths, encodings, table index and
source metadata. Celldega settings such as `segmentation_approach` and `image_info` stay in
the client adapter. The older v1 file manifest retains those settings for compatibility.
Names such as `grid_files_v1` and `cell_segmentation` still deserve review before proposing
the contract upstream.

Gene colors stay in **`uns["gene_colors"]`**, not `var["color"]`. This borrows the form
of [Scanpy's categorical palettes](https://scanpy.scverse.org/en/stable/api/generated/scanpy.pl.umap.html),
but the gene key and `var_names` alignment are new profile conventions.
[AnnData describes `uns` as unstructured metadata](https://anndata.readthedocs.io/en/stable/generated/anndata.AnnData.uns.html);
it does not automatically reorder this gene-color list when genes are reordered. A producer
must maintain the association explicitly. Existing colors are currently preserved without
validation, so retiling alone cannot repair a stale palette.

## Division of implementation work

spatialdata-io handles grid math, feature coding, transcript sorting/spilling, polygon
encoding, table statistics/palettes/CSC and manifest assembly. Streaming is selected for
multi-partition Dask input, not by a fixed transcript-count threshold.

Celldega's `js/spatialdata/` reads AnnData with zarrita and converts it to the Arrow
schemas used by existing rendering code. Native OME-Zarr uses viv's loader and the
existing image layers. A newly generated profile enables metadata, expression and images
from Zarr. Image tiles are converted to uint8 RGBA for rendering; this is not an end-to-end
16-bit rendering path.

Canonical transcript x/y buffers stay separate through GPU upload and a custom
ScatterplotLayer applies the affine transform in its vertex shader. Canonical GeoArrow
polygon buffers avoid WKB parsing, but Celldega currently walks each newly visible tile on
the CPU to build transformed JavaScript path arrays for the standard `PathLayer`. That
conversion can affect pan/zoom tile-update latency and allocation pressure; it is bounded
by visible row groups and does not repeat every animation frame. A future binary polygon
layer could remove that materialization. Celldega does not use
`@geoarrow/deck.gl-layers` in the current implementation.

DegaFiles remain supported through `landscape_parameters.json` manifests without a
`spatialdata` block. Celldega checks that file first, then falls back to the root
`spatial_tiling` attribute when the file is absent.
`celldega.pre.spatialdata_images` exports optional WebP pyramids from SpatialData and
returns manifest fragments. This is a useful part of a future complete SpatialData-to-
DegaFiles converter; a complete converter is not present on the reviewed branch.

Celldega temporarily depends on `@cornhundred/parquet-wasm@0.7.2-celldega.0`. That package
carries the column-projection fix until the upstream change is merged and released.

## Storage and bandwidth

Historical measurements recorded for the rebuilt Xenium stores (not rerun during the
2026-09-09 review) compare **the earlier full visualization profile with `adapt_dega`**:

| | pancreas | Prime skin |
|---|---:|---:|
| table, before → after | 7.9 MB → 17 MB | 58 MB → 162 MB |
| profile, before → after | 140 MB → 100 MB | 600 MB → 415 MB |
| whole store, rounded | 3.3 GB → 3.3 GB | 5.1 GB → 5.1 GB |
| gene-list transfer | 0.017 MB | 0.126 MB |
| example single-gene transfer | 0.084 MB | 0.060 MB |

This is not a zero-overhead comparison with stock SpatialData. The skin CSC layer was
104 MB against about 55 MB for CSR `X`; the smaller per-gene chunks compressed worse.
Earlier canonical point measurements put tiling overhead at +39.8% against an
equivalently compressed untiled file. Costs depend on density, expression distribution,
chunking and compression. Gene reads scale with that gene's non-zeros, not necessarily a
constant amount per dataset.

## Coarse views and future jitter

Cell expression can supply Celldega's coarse representation of transcripts. CSC makes
those gene reads efficient; it does not create a spatial multiscale point hierarchy by
itself. A general level-of-detail convention would also specify aggregation semantics,
cell associations and when to switch representations.

Separating display coordinates makes deterministic jitter possible without changing
analysis coordinates. For sequencing bins, display points should be identified as a
visualization of counts, not newly measured molecule positions. This profile currently
implements no jitter; seed, rule, units and provenance would need to be recorded.
