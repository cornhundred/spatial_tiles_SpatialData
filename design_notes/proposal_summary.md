# What we are proposing

An opt-in extension for spatial access and visualization, implemented on the `adapt_dega`
branches of spatialdata-io and Celldega. SpatialData core is currently unmodified. Stores
open with ordinary SpatialData; the extension is experimental and is not yet a ratified
SpatialData specification. See [the implementation review](implementation_review.md)
before treating the current code as a generic producer/consumer implementation.

## Store conventions

| addition | location | purpose |
|---|---|---|
| spatial row groups | canonical Points and Shapes Parquet | compute tile-to-file/row-group addresses |
| display points and polygons | `visualization/grid_files_v1/{trx,cell_seg}` | interleaved float32 coordinates and integer feature/cell codes |
| gene-major matrix copy | `tables/table/layers/X_csc` | small per-gene reads while retaining `X` in its original format |
| per-gene statistics | `var["mean", "std", "max", "non_zero"]` | populate gene controls without reading all of `X` |
| gene colors | `uns["gene_colors"]` | one hex color per gene, aligned with `var_names` |
| cluster palette | `uns["<column>_colors"]` | colors in categorical `obs` category order |
| manifest | `visualization/grid_files_v1/landscape_parameters.json` | grid, paths, encodings, table location and feature ordering |

Canonical transcript coordinates and polygon geometries remain authoritative. Display
polygons keep only the largest part's exterior ring. Canonical Points keep their original
columns; canonical Shapes currently also gain a positional `cell_code` column. For raw
Xenium conversion, statistics and palettes are present in the initial table write and the
CSC buffers are tuned afterward, so the table is written once. Adding tiling to an existing
store still deletes and rewrites its table.

The canonical **Points** are still written twice on the one-shot path: once by
`sdata.write()` and again by the tiling pass that reorders them into row groups. Removing
that would mean writing tile row groups during the initial write, which spatialdata-io
cannot do from outside — it needs a writer hook in SpatialData core (the dropped
[points_writer patch](spatialdata-points-writer-hook.patch)). It costs write time, not
correctness.

Deleting `visualization/` removes display files and their manifest. It does **not** undo
canonical row grouping, `cell_code`, table statistics, palettes or CSC storage. Conversely,
an ordinary `read_zarr(...).write(new_store)` preserves supported analysis content but
does not copy the profile or preserve its tile row groups/metadata. Regenerate the profile
after saving or changing its source data.

## What needs standardization

The reusable part is a spatial access contract: coordinate system, grid extent and
numbering, tile-to-row-group mapping, source/instance associations, discovery, and
invalidation. Display encodings and gene-major access can be optional extensions.

The current manifest still uses Celldega names and settings such as
`landscape_parameters.json`, `technology`, `segmentation_approach`, and `image_info`.
Other tools can implement it, but renaming the profile `grid_files_v1` alone does not
make every field viewer-independent. A small generic contract with a Celldega adapter is
a reasonable next step for an upstream discussion.

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

DegaFiles remain supported through manifests without a `spatialdata` block.
`celldega.pre.spatialdata_images` exports optional WebP pyramids from SpatialData and
returns manifest fragments. This is a useful part of a future complete SpatialData-to-
DegaFiles converter; a complete converter is not present on the reviewed branch.

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
