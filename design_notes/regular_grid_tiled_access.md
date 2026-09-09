# Regular-grid tiled access profile (`grid_files_v1`)

**Status:** experimental · **Profile version:** 0.1.0 · **Reviewed:** 2026-09-09

This describes the current `adapt_dega` layout and its intended access contract. It
replaces the earlier `celldega_regular_grid_v1` draft. Celldega is the reference client;
the grid and encodings are reusable, while parts of the manifest remain Celldega-specific.
This is not an accepted SpatialData standard. Known conformance gaps are called out below
and reproduced in [the implementation review](implementation_review.md).

## 1. Scope and representation

A profile gives a client a formula for selecting spatial tiles, then Parquet footer
metadata gives it the byte ranges to fetch. Footers and the manifest are still needed;
the viewport alone does not identify byte offsets.

```text
sample.zarr/
├── points/<points>/points.parquet/       canonical columns + original index, tile ordered
├── shapes/<shapes>/shapes.parquet        file or directory; canonical geometry + cell_code
├── tables/<table>/
│   ├── var/{mean,std,max,non_zero}
│   ├── uns/gene_colors
│   ├── uns/<cluster_column>_colors       when requested and categorical
│   └── layers/X_csc                      gene-major copy of sparse X
└── visualization/grid_files_v1/
    ├── landscape_parameters.json
    ├── trx/                             display_xy + feature_code
    └── cell_seg                          file or directory: display_geometry + cell_code
```

Original points and polygons are authoritative. The display Parquets contain derived
coordinates and compact positional codes. In the current writer, only canonical Shapes
also acquire `cell_code`; canonical Points do not acquire display columns. Statistics,
palettes and the optional CSC layer are added to the annotating table.

A single output chunk for shapes is a **file**, including the display path `cell_seg`.
Multiple shape chunks are a directory of Parquets. Points always use a directory.

## 2. Coordinates

The writer applies the selected element-to-coordinate-system affine in float64, then
stores **unrounded float32** x/y values. It assumes the selected coordinate system is
level-0 image pixel space. For the tested Xenium setup, `global` has that meaning.
SpatialData does not require every `global` coordinate system to be image pixels.

The transcript fragment records:

```json
"display_transform": {
  "coordinate_space": "image-pixel",
  "coordinate_system": "global",
  "affine_matrix": [[4.70588235, 0, 0], [0, 4.70588235, 0]],
  "rounding": "nearest"
}
```

**Known metadata defect:** `rounding: "nearest"` is stale. No integer rounding is applied
to the stored display coordinates; clients must follow `position_dtype: "float32"` and
`position_scale: 1.0`. The writer rejects negative/non-finite display coordinates and
coordinates above `2**24`. That upper limit does not guarantee 0.01-pixel accuracy.

Automatic grid derivation uses origin `(0, 0)` and transforms the separate x/y maxima,
rounding the resulting bounds. It is not a correct bounds algorithm for every affine.
The current browser centroid reader supports identity, scale, translation and sequences,
not arbitrary affine transforms. Native image placement assumes pixel coordinates and
does not apply the image-to-target transform. These restrictions must be resolved or
validated explicitly before claiming generic registered-store support.

## 3. Grid and row groups

The grid has `x_min`, `y_min`, `tile_size`, `num_tiles_x` and `num_tiles_y`.

```text
tile_x = floor((x_px - x_min) / tile_size)
tile_y = floor((y_px - y_min) / tile_size)
tile_id = tile_x * num_tiles_y + tile_y
file_index, local_row_group = divmod(tile_id, max_row_groups_per_file)
```

The current default tile size is 250 display pixels; file capacity defaults to 400 row
groups. Boundaries are half-open at internal tile edges. The intended outer-edge rule
includes coordinates exactly on the upper edge in the last tile. The implementation
also accepts the whole next tile-index band and clamps it; this is a conformance gap,
not a precise spatial bounds check.

A producer must write **one physical row group per tile, including empty tiles**, and
preserve every source row exactly once. Empty tiles occupy zero-row row groups.
The writer sets an explicit row-group size and checks every staged Parquet footer before
publishing it. It rejects a tile above 67,108,864 rows, the explicit implementation limit,
rather than allow PyArrow to split the tile and invalidate formula-based addresses.

Chunk names are zero-padded to the width of the largest file index, and their manifest
array is ordered numerically. This keeps manifest ordering and lexical directory reads
consistent. A single shape file uses the fragment's `path`; multi-file entries use
`directory` and `files`.

The canonical Parquet schema records `profile`, `storage_mode`,
`max_row_groups_per_file` and `tile_grid`. It does **not** currently record the target
coordinate system or affine with that grid; those are available through the profile and
element metadata. A standalone generic spatial index needs an explicit frame association.

The writer uses zstd and disables Parquet statistics. Formula-based access does not need
statistics, but ordinary Python predicates will not thereby gain automatic tile pruning.
A Python client must implement the same tile selection and read the selected row groups.
No SpatialData spatial-query integration is added on these branches.

Streaming defaults to multi-partition Dask input. Pass one spills by destination file;
pass two sorts each spill bucket by tile. Memory depends on the largest partition and
bucket, not a fixed row-count threshold, and a very dense bucket can still be large.

## 4. Transcript display schema

| column | Arrow representation | meaning |
|---|---|---|
| `display_xy` | `fixed_size_list<float32>[2]` | interleaved level-0 pixel x/y |
| `feature_code` | `uint16`, or `uint32` for a catalog above 65,535 entries | position in the feature catalog |

Parquet stores a List; readers may recover Arrow FixedSizeList from embedded schema
metadata. A client must accept either List or FixedSizeList with exactly two scalar
coordinates per point. Interleaving removes an x/y zipper step, but this is not end-to-end
zero-copy: decompression, WASM-to-Arrow IPC, buffer copies and GPU upload still occur.
Celldega currently concatenates transcript coordinates into a Float64Array.

The canonical points retain separate x/y and other source columns. Nested display
columns are excluded because the tested Dask round-trip could stringify or reject them.
The display files also avoid the tested parquet-wasm `ParquetFile.read({columns})` failure;
Celldega reads every column of these small files. This is a workaround for the tested
library versions, not a limitation of Parquet column projection in general.

## 5. Polygon display schema and cell identity

| column | Arrow representation | meaning |
|---|---|---|
| `display_geometry` | `list<list<fixed_size_list<float32>[2]>>` | polygon → rings → interleaved vertices |
| `cell_code` | `uint32` | row position in the annotating table |

The writer retains only the largest MultiPolygon part and its exterior ring for display.
The original canonical geometry and GeoParquet metadata are retained. Cells are assigned
by the centroid of that simplified polygon. They are not duplicated across intersected
tiles. Fetching a neighboring ring may help viewport coverage but is not a guarantee for
arbitrarily large polygons; exact spatial queries need a bounds-aware policy and filtering.

Clients must accept List or FixedSizeList vertices and reject `struct<x,y>` when using
the flat interleaved path. The polygon starts follow ring and polygon offsets.

Cell codes resolve the table's `region_key` and `instance_key` to shape IDs, retaining
the corresponding table-row positions. The Xenium path also accepts a single annotated
instance namespace when the boundary Shapes element has a different region name.
Multi-region tables require an exact region match rather than an inferred association.
Circle Shapes, labels-only segmentation and absent centroid arrays are not supported by
this polygon/centroid path.

## 6. Feature ordering, colors and expression

Genes are read from the table's `var` index in its stored order. Observed features absent
from that index are appended in sorted order and recorded in
`feature_catalog.extra_features`. They often include controls; absence from a filtered
table alone does not establish that a feature is biologically a control.
`feature_catalog.n_genes` gives the split. The current Celldega metadata table uses uint16
feature codes even when the producer selects uint32; catalogs above that range need a
reader fix.

**Gene colors:** `uns["gene_colors"]`, one hex string per `var_names` entry. No
`var["color"]` column is written or read for this profile. Extra features use the client
fallback palette. The gene-specific key/alignment rule is a proposed convention using
Scanpy's familiar `uns` palette form. AnnData does not automatically realign it when
variables are subset or reordered. Validate and synchronize it before regenerating a
profile; the current writer preserves existing lists without checking their contents.

**Cluster colors:** `uns["<column>_colors"]` aligns with the categorical column's stored
categories, including unused categories. The current reader incorrectly sorts observed
values instead; this needs correction. Without a configured clustering the reader uses
one `unclustered` category.

**Expression:** the default writer computes population `mean`, `std`, `max` and
`non_zero` fraction into `var`, then writes sparse `X` as `layers/X_csc`. The matrix
shape remains cells × genes. `indptr[g]:indptr[g+1]` addresses a gene's data and cell
indices. Data are currently cast to float32, indices and pointers to int32; these casts
need range/precision validation for general inputs.

CSC data/index chunks target two average genes' non-zeros with a 1,024-entry minimum.
They are not per-gene row groups and need not end at gene boundaries. `indptr` is a single
chunk. A gene can span multiple chunks. The fallback reads CSR `X` completely; dense and
CSC `X` are unsupported by that fallback. Statistics currently mishandle stored sparse
zeros and can overflow when squaring integer inputs. See the review for reproductions.

## 7. Images and optional DegaFiles export

Fresh profiles enable native OME-Zarr images. Celldega uses `@vivjs/loaders`, not viv's
deck.gl layers, and converts each tile to an 8-bit ImageBitmap for its existing layers.
The intensity window comes from channel metadata when available, otherwise a dtype-based
default. This is uint16 input support, not preserved 16-bit interactive contrast.

An explicit `spatialdata.image_element` wins; otherwise the reader picks the first sorted
image name from root Zarr v3 consolidated metadata. That selection is not coordinate-aware.
V2 or unconsolidated stores need an explicit image element. Resolution selection assumes
a dyadic pyramid and compatible tile sizes; arbitrary pyramids are not validated.

`celldega.pre.spatialdata_images.spatialdata_to_dega_images` optionally writes WebP
Parquet pyramids and returns manifest fragments. The caller must resolve channel paths
relative to the intended manifest and install the returned fragments. For a native profile,
remove `images` from `spatialdata.native` to use those WebP tiles. Removing the entire
`spatialdata` block does not create the missing metadata/expression files of a DegaFiles
bundle. A complete SpatialData-to-DegaFiles exporter is still future work.

## 8. Manifest

Minimal illustrative one-tile profile (additional producer fields omitted):

```json
{
  "technology": "Xenium",
  "profile": "grid_files_v1",
  "profile_version": "0.1.0",
  "use_row_groups": true,
  "use_int_index": true,
  "segmentation_approach": ["default"],
  "tile_size": 250.0,
  "tile_grid": {
    "num_tiles_x": 1, "num_tiles_y": 1, "tile_size": 250.0,
    "x_min": 0.0, "y_min": 0.0, "x_max": 250.0, "y_max": 250.0
  },
  "row_group_files": {
    "transcripts": {
      "directory": "trx", "files": ["chunk_0.parquet"],
      "max_row_groups_per_file": 400, "total_row_groups": 1,
      "position_column": "display_xy", "position_dtype": "float32",
      "feature_column": "feature_code", "render_only": true
    },
    "cell_segmentation": {
      "path": "cell_seg", "max_row_groups_per_file": 400, "total_row_groups": 1,
      "geometry_column": "display_geometry", "cell_id_column": "cell_code",
      "render_only": true
    },
    "images": {}
  },
  "feature_catalog": {"n_genes": 2, "extra_features": ["NegControlProbe_1"]},
  "spatialdata": {
    "store_url": "../..", "table": "table", "native": ["metadata", "cbg", "images"]
  },
  "source": {
    "points_element": "transcripts", "shapes_element": "cell_boundaries",
    "table_element": "table", "coordinate_system": "global"
  },
  "image_info": [],
  "image_format": ".webp"
}
```

Paths are relative to the manifest directory. `image_format` is a legacy setting, not
proof that a WebP pyramid exists. There is no `columns` projection request.

`spatialdata.native` is intended to select components independently. Currently opting
into `cbg` also constructs the adapter used unconditionally at metadata call sites;
expression-only opt-in is not isolated. With `table_element=None`, the manifest omits
table-backed native components and embeds feature names so `feature_code` remains decodable.

## 9. Transport and lifecycle

Parquet serving requires byte-range and suffix-range requests with correct `206` and
`Content-Range` responses. Cross-origin hosting also requires CORS and exposed range
headers. Celldega's local server implements these ranges on `adapt_dega`.

Regenerate the profile when transcript rows, geometries, feature ordering, table row
ordering, expression, transforms, grid settings or source image change. Refresh derived
statistics/CSC after editing `X`; refresh palettes when changing gene/category ordering.
The current manifest records descriptive source metadata, not fingerprints or automatic
invalidation. A stale profile can therefore misrender silently.

Ordinary `SpatialData.write()` preserves analysis data but rebuilds Parquet without this
tile contract and does not copy `visualization/`. CSC content can round-trip, but custom
CSC chunk sizes need not survive a rewrite. Tiling is currently a final post-save step.

The overall operation is not transactional: separate assets are replaced in sequence.
The one-shot Xenium entry point annotates the table before its initial write, while the
existing-store entry point deletes and rewrites the table when expression indexing is
requested. Preflight validation and staged publication with recovery remain future work.
