# `adapt_dega`: implementation status and remaining work

Updated 2026-09-10 against the `adapt_dega_v2` branches.
This replaces the earlier running tally, whose pending tasks and `var["color"]`
proposal no longer described the branches. See [the review](implementation_review.md)
for reproductions and [the protocol](regular_grid_tiled_access.md) for the current layout.

## Direction

The earlier `feat/spatialdata-regular-grid-reader` / `feat/xenium-celldega-regular-grid`
branches produced a fuller Celldega bundle inside SpatialData. Both current branches are
named `adapt_dega_v2`: Celldega reads the existing store, while spatialdata-io adds
spatial row groups, GeoArrow Shapes and a small set of table annotations/indexes. The
canonical layout does not create a visualization directory.

SpatialData core is unmodified. This proves the experimental stores can be read without
a core patch; it does not establish an accepted extension specification or preservation
of the profile through ordinary saves.

## Implemented

| component | current source / behavior |
|---|---|
| gene names | AnnData `var` index |
| gene statistics | `var[mean, std, max, non_zero]`; CSR computation fallback |
| gene colors | `uns["gene_colors"]`, in `var_names` order; fallback for absent colors and extra features |
| cell names | `obs` index |
| cell centroids | `obsm["spatial"]` by default, transformed using the configured Shapes element |
| clusters | configured `obs` column, otherwise `unclustered` |
| cluster palettes | `uns["<column>_colors"]`, aligned to stored categorical order |
| gene expression | `layers/X_csc`, falling back to a whole-CSR read of `X` |
| images | native OME-Zarr via `@vivjs/loaders`, converted to 8-bit ImageBitmaps |
| transcripts | canonical `x`, `y`, and dictionary `feature_name`; x/y stay separate through GPU upload |
| cell boundaries | canonical `geoarrow.polygon` plus positional `cell_code` |
| manifest | root `zarr.json` attribute `spatial_tiling` |
| DegaFiles | unchanged `landscape_parameters.json`, interleaved geometry and legacy readers |
| optional WebP export | `celldega.pre.spatialdata_images.spatialdata_to_dega_images` |

These components are wired into `landscape_ist.js`. With a table, the writer enables
`metadata`, `cbg`, and `images` in the manifest. A no-table profile advertises images and
carries its feature names directly. WebP remains the established DegaFiles
path and an optional SpatialData export; it is not the new profile's default.

Native transform support currently handles centroid identity, scale, translation, and
sequences of those. Transcript and polygon display transforms are now taken from their
manifest entries. General image registration, Python widget transforms and physical
scale-bar inference from SpatialData metadata remain incomplete.

## Gene colors remain in `uns`

Use `uns["gene_colors"]`, not `var["color"]`. The list has one hex color per gene in
`var_names` order. This borrows Scanpy's categorical palette shape, but the gene-specific
key and alignment rule are proposed conventions, not an existing AnnData gene-color
standard. `uns` is unstructured: filtering or reordering genes does not automatically
align this list. Keep its gene association synchronized before regenerating a profile.
The current writer preserves an existing list without validating it.

Cluster palettes follow `obs[column].cat.categories` order, including unused categories.
The writer and JS reader both retain that stored order.

## Expression access

The initial experiment downloaded the whole CSR matrix. That fallback still exists, but
the default writer now adds statistics and a CSC layer. CSC is the same cell-by-gene
matrix stored by column, **not its mathematical transpose**. It enables per-gene slices
without making cell-oriented analysis use CSC as its primary `X`.

Chunk length targets two average genes' non-zeros, with a floor of 1,024 entries. Chunks
are fixed-length buffers, not aligned gene boundaries. Highly expressed genes can span
many chunks. Dense `X` is accepted by the Python statistics writer but cannot be used for
gene reads by the current JS adapter; CSC `X` needs the derived layer and statistics.

Historical measurements from the earlier probes:

| dataset | cells | genes | nnz | compressed CSR `X` |
|---|---:|---:|---:|---:|
| pancreas | 140,702 | 377 | 2.6 M | 4.5 MB |
| Prime skin | 112,551 | 5,006 | 33.3 M | 54.8 MB |

The rebuilt skin CSC layer was about 104 MB, not 54.8 MB: smaller chunks compress less
well. These are measurements for these stores, not general storage or bandwidth bounds.

## Image feasibility

`zarrita@0.7.5` and `@vivjs/loaders@0.22.1` read the tested SpatialData Zarr v3 store.
The earlier viv failure was caused by passing a zarrita Location instead of a URL string;
viv does understand the nested NGFF 0.5 `ome` metadata.

The loader reads uint16 data, but `tileToRgba` windows it to uint8 before creating an
ImageBitmap. The intensity slider operates on that converted image. Preserving 16-bit
contrast throughout interactive rendering would need further work.

The historical pancreas comparison was 2.9 GB for its four-channel uint16 OME-Zarr
pyramid versus 25 MB for the derived WebP pyramid. A full-resolution Zarr chunk was
about 16 MB. Those numbers depend on dtype, compression, chunk shape and dataset.

`spatialdata_to_dega_images` exports images and returns manifest fragments. It does not
write a complete DegaFiles bundle or patch an existing manifest automatically. Metadata,
expression, transcript and boundary exports still need an integrated conversion entry point.

## Remaining work before a generic proposal

1. Make coordinate selection consistent across points, polygons, centroids, images and
   scale bars. Validate unsupported transforms instead of silently misaligning.
2. Define profile lifecycle on save, subset, table reorder, geometry edits and expression
   changes. Existing-store expression indexing still replaces the table in place.
3. Preserve gene associations for `uns` palettes across gene reorder/subset.
4. Correct expression statistics for integer and noncanonical sparse inputs; define dtype
   and large-index handling for CSC storage.
5. Add automated writer-to-browser integration coverage. The manual notebook and unit
   suites do not exercise all these relationships.

Jitter is a future display policy, not implemented by this profile. It should record a
reproducible seed and displacement rule while preserving canonical locations. Cell-level
expression can supply Celldega's coarse view, but CSC alone does not define a multiscale
transcript hierarchy or level-selection protocol.
