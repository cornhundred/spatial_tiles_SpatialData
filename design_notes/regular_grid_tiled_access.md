# Regular-grid tiled access profile (`grid_files_v1`)

**Status:** experimental · **Profile version:** 0.1.0 · **Reviewed:** 2026-09-10

This describes the current `adapt_dega_v2` layout and its intended access contract. It
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
└── zarr.json
    └── attributes.spatial_tiling         root manifest
```

Original points and polygons are authoritative and are also the visualization source.
Canonical Points keep separate x/y and dictionary feature values. Canonical Shapes use
`geoarrow.polygon` and acquire `cell_code`. Statistics, palettes and the optional CSC
layer are added to the annotating table.

`profile_layout="v1"` is retained as a compatibility layout. It adds
`visualization/grid_files_v1/landscape_parameters.json`, interleaved `display_xy`, and
simplified `display_geometry`. A single output chunk for shapes is a file; multiple shape
chunks are a directory. Points always use a directory.

## 2. Coordinates

Canonical coordinates stay in element space. The manifest records the selected
element-to-coordinate-system affine; Celldega applies it to transcript coordinates in the
GPU shader and to polygon paths during their existing CPU path construction. The v1
layout stores transformed, unrounded float32 display coordinates instead. Both layouts
assume the target coordinate system is level-0 image pixel space. For the tested Xenium
setup, `global` has that meaning.
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

`rounding: "nearest"` describes grid-bound derivation and must not be interpreted as
rounding canonical or v1 display coordinates. The v1 writer rejects negative/non-finite
display coordinates and coordinates above `2**24`.

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

## 4. Transcript schemas

| layout | columns | meaning |
|---|---|---|
| canonical | `x`, `y`, dictionary `feature_name` | element coordinates and source feature values |
| v1 | `display_xy`, integer `feature_code` | interleaved level-0 pixel x/y and feature catalog position |

For v1, Parquet stores a List; readers may recover Arrow FixedSizeList from embedded schema
metadata. A client must accept either List or FixedSizeList with exactly two scalar
coordinates per point. Interleaving removes an x/y zipper step, but this is not end-to-end
zero-copy: decompression, WASM-to-Arrow IPC, buffer copies and GPU upload still occur.
The canonical Celldega path instead keeps one binary sublayer per Arrow record batch and
binds x and y as separate scalar attributes. A small ScatterplotLayer shader constructs
the position and applies the affine on the GPU, with no coordinate zipper or concatenation.

Canonical columns are ordered `x`, `y`, feature first because the patched parquet-wasm
projection coalesces reads across the byte span from the first requested column to the
last. On pancreas, requesting those columns cost 19.7 KiB versus 18.2 KiB for the old
display file (1.08×). Celldega latches back to full-column reads if projection fails.

## 5. Polygon schemas and cell identity

| layout | geometry | identity |
|---|---|---|
| canonical | `geometry: list<list<struct<x,y>>>`, extension `geoarrow.polygon` | `cell_code: uint32` |
| v1 | `display_geometry: list<list<fixed_size_list<float32>[2]>>` | `cell_code: uint32` |

Canonical GeoArrow retains the full geometry. The v1 writer retains only the largest
MultiPolygon part and its exterior ring. Cells are assigned to tiles by centroid and are
not duplicated across intersected tiles. Fetching a neighboring ring may help viewport
coverage but is not a guarantee for arbitrarily large polygons.

Celldega accepts List or FixedSizeList vertices for v1 and separated `struct<x,y>` for
canonical GeoArrow. The polygon starts follow ring and polygon offsets.

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
categories, including unused categories. The reader retains that order. Without a
configured clustering the reader uses one `unclustered` category.

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
relative to the intended file manifest and install the returned fragments. In a v1 file
manifest, remove `images` from `spatialdata.native` to use those WebP tiles. The canonical
root profile contains no image-tile entry, so Celldega reads OME-Zarr images natively.
Removing the entire `spatialdata` block does not create the missing metadata/expression
files of a DegaFiles bundle. A complete SpatialData-to-DegaFiles exporter is still future
work.

## 8. Manifest

Minimal illustrative one-tile canonical profile (additional producer fields omitted):

```json
{
  "profile": "grid_files_v1",
  "profile_version": "0.1.0",
  "tile_grid": {
    "num_tiles_x": 1, "num_tiles_y": 1, "tile_size": 250.0,
    "x_min": 0.0, "y_min": 0.0, "x_max": 250.0, "y_max": 250.0
  },
  "row_group_files": {
    "transcripts": {
      "directory": "points/transcripts/points.parquet", "files": ["chunk_0.parquet"],
      "max_row_groups_per_file": 400, "total_row_groups": 1,
      "position_encoding": "separate_columns", "position_columns": ["x", "y"],
      "feature_column": "feature_name", "feature_encoding": "dictionary",
      "render_only": false
    },
    "cell_segmentation": {
      "path": "shapes/cell_boundaries/shapes.parquet",
      "max_row_groups_per_file": 400, "total_row_groups": 1,
      "geometry_column": "geometry", "geometry_encoding": "geoarrow.polygon",
      "cell_id_column": "cell_code", "render_only": false
    }
  },
  "feature_catalog": {"n_genes": 2, "extra_features": ["NegControlProbe_1"]},
  "spatialdata": {
    "store_url": ".", "table": "table"
  },
  "source": {
    "technology": "Xenium",
    "points_element": "transcripts", "shapes_element": "cell_boundaries",
    "table_element": "table", "coordinate_system": "global"
  }
}
```

Canonical paths are relative to the store root where the attribute lives. The generic
root block omits Celldega UI settings and image-tile configuration. Celldega adds its
viewer defaults after discovering this block, projects the declared render columns, and
falls back to a full read if projection fails.

The v1 file manifest can use `spatialdata.native` to select components independently.
The canonical profile omits that viewer policy, and Celldega defaults to native metadata,
expression and images. With `table_element=None`, the manifest omits table-backed metadata;
feature names are still available from the canonical transcript column.

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
tile contract. In v1 it also does not copy `visualization/`. CSC content can round-trip,
but custom CSC chunk sizes need not survive a rewrite. Tiling is currently a final
post-save step.

The overall operation is not transactional: separate assets are replaced in sequence.
The one-shot Xenium entry point annotates the table before its initial write, while the
existing-store entry point deletes and rewrites the table when expression indexing is
requested. Preflight validation and staged publication with recovery remain future work.
