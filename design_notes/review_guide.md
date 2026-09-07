# Review guide

Two branches. **spatialdata-io is the substance**; the celldega one is small and can be
reviewed in a few minutes. **SpatialData core needs no change at all.**

| repo | branch | diff | status |
|---|---|---|---|
| spatialdata-io | `feat/xenium-celldega-regular-grid` | +4,264 | the profile |
| celldega | `feat/spatialdata-regular-grid-reader` | +528 / −19 | reader + 3 unrelated bug fixes |
| spatialdata | — | — | **no change needed** |

---

## What the profile actually does

An opt-in set of derived files that make a SpatialData store directly viewable, plus one
change to the canonical elements: **rows are reordered into a deterministic tile grid**,
one Parquet row group per tile. Nothing else about the canonical data changes.

```
sample.zarr/
├── points/transcripts/points.parquet/      canonical columns, reordered into tile row groups
├── shapes/cell_boundaries/shapes.parquet/  canonical GeoParquet, same reordering
└── visualization/grid_files_v1/            all new, all derived
    ├── landscape_parameters.json           the manifest
    ├── trx/chunk_NN.parquet                display_xy + feature_code, same row groups
    ├── cell_seg/chunk_NN.parquet           display_geometry + cell_code
    ├── cbg/chunk_N.parquet                 gene-major expression, one gene per row group
    ├── images/<channel>/chunk_N.parquet    WebP pyramid per channel
    ├── cell_metadata.parquet               cell centroids + names
    ├── meta_gene.parquet                   per-gene stats + colours
    ├── micron_to_image_transform.csv       micron→pixel affine (drives the scale bar)
    └── cell_clusters/                      placeholder clustering
```

The row grouping is the one thing that touches canonical data, and it is what makes
spatial subsetting cheap from Python — a 20-tile read is **8 ms on 8 M transcripts,
10 ms on 74 M**, versus a full scan.

---

## spatialdata-io: `feat/xenium-celldega-regular-grid`

15 commits, +4,264 lines. **~1,400 lines are executable code**; the rest is docstrings
(24%), tests (1,445 lines) and comments.

### Review in this order

**1. `regular_grid.py` (247)** — start here. Pure, dependency-light tile math. Everything
else builds on it.

```python
tile_x  = floor((x_px - origin_x) / tile_size_px)     # half-open bounds
tile_id = tile_x * num_tiles_y + tile_y               # x-major
file_index, local_row_group = divmod(tile_id, max_row_groups_per_file)
```

Reimplements Celldega's formula rather than importing it — Celldega already depends on
spatialdata-io, so importing back would be circular. A conformance test pins the two
together instead.

**2. `feature_catalog.py` (195)** — genes first in `var_names` order, controls appended
above them. That ordering is load-bearing three ways:

```
feature_code == row position in meta_gene.parquet == CBG row group
```

**3. `points_parquet.py` (504)** — the main writer. Two paths that must agree:

```python
write_points_regular_grid(points, out, catalog=cat, grid=grid)                    # canonical
write_points_regular_grid(points, out, catalog=cat, grid=grid, render_only=True)  # render file
```

In-memory below ~20 M rows; above that a two-pass spill. Grouping by tile is a *global*
sort, so streaming the read is not enough — pass 1 spills rows into per-output-file
buckets, pass 2 sorts each independently. A test asserts both paths produce identical row
groups.

**4. `shapes_parquet.py` (322)**, **`cbg_parquet.py` (181)**, **`webp_parquet.py` (310)** —
independent, reviewable in any order.

**5. `manifest.py` (192)** and **`tiled_access.py` (395)** — the two entry points:

```python
add_spatial_tiling("sample.zarr", tile_size_px=250, image_element="morphology_focus")
xenium_spatially_tiled(raw, "out.zarr", tiling={"image_element": "morphology_focus"})
```

### Decisions worth checking, with the measurement behind each

| decision | why |
|---|---|
| tile size **250 px** | 21.0 cells/tile; 500 px gives 81 |
| **multi-file** output | a single 7,535-row-group file has a **7.4 MB footer** the browser must fetch before its first read; split, each is ~410 KB |
| **zstd** | snappy +38.5% vs zstd +4.9% over an untiled store, same write time |
| statistics **off** | the tile formula is the index; statistics only inflate the footer |
| zero-padded chunk names | Celldega indexes the manifest array; dask globs and sorts lexicographically, where `chunk_10` precedes `chunk_2` |
| render columns in **separate files** | a nested Arrow column cannot survive dask's parquet round-trip, so `SpatialData.write()` broke |
| **float32** coordinates | see below |

### Storage

Honest figure, against an equivalently-compressed untiled store (not against
SpatialData's snappy default, which flatters it):

```
zstd, untiled, no render columns    173.9 MB    baseline
+ tiling into 7,535 row groups      243.0 MB    +39.8%
```

Fragmentation, not the columns, is the cost — zstd compresses one large block far better
than 7,535 small ones. With 5,006 genes, the categorical dictionary alone is ~20% of the
points file, since it is rewritten per column chunk.

### Known limitations

- Cluster colouring is a **single placeholder group**; SpatialData does not require a
  clustering and the Xenium reader does not load one.
- Cell hover labels need `cats.nameMapping_inv`, which the profile does not populate.
- The Xenium `transcripts.zarr` fast path is not implemented (deferred, not cut).

---

## celldega: `feat/spatialdata-regular-grid-reader`

**Three of these are bugs that exist independently of this work** and are worth landing
regardless:

| commit | what |
|---|---|
| `747b032` | **local server ignored `Range`** — advertised it in CORS headers but inherited `SimpleHTTPRequestHandler.do_GET`. A `bytes=0-7` request for a 3.86 MB chunk returned all 3,861,910 bytes. Every local row-group read was a full-file download, DegaFiles included, so **any local benchmark of that path measured the wrong thing** |
| `2797d1f` | **trailing slash in `base_url`** produced `//`, an empty path segment that absorbs one `..` |
| `ef92b2b` | **CDN vs local bundle** — a clean `X.Y.Z` install silently serves the published bundle, so local `js/` edits do nothing with no warning. This cost an entire debugging session |

Profile support proper:

| commit | what |
|---|---|
| `89c0ef3` | manifest-driven column names, DegaFiles defaults preserved |
| `30d0fca` | **removes** the column projection — see below |
| `d1484c1` | accept `List` as well as `FixedSizeList` vertex coordinates |
| `f7901cd` | **revert before merging** — temporary `spatialdata<0.8` relaxation |

### parquet-wasm's column projection is broken

Passing `columns` to `ParquetFile.read` corrupts the IPC stream it emits; the failure
surfaces later in `tableFromIPC`. Reproduced on **0.7.1 and 0.7.2**, apache-arrow **15 and
18**, scalar and nested columns alike, and **even with an empty array**. Only reads that
pass no `columns` succeed.

Projection turned out to be unnecessary anyway: the render files hold only render columns,
so reading all of one *is* the projection.

### Backwards compatibility

Every change is additive. DegaFiles declare none of the new manifest keys and keep their
existing behaviour (`geometry` / `name`, all columns). Tests assert both paths.

---

## spatialdata core: no change

The profile needs nothing from core. `add_spatial_tiling` works entirely on an
already-written store, and the whole spatialdata-io suite passes against unmodified
`spatialdata` main.

A generic `points_writer` hook was prototyped and then dropped, because nothing used it:
it would have saved a double write (13.5s → 8.5s on 8 M transcripts) only on the one-shot
path, which does not pass it. Kept as
[`spatialdata-points-writer-hook.patch`](spatialdata-points-writer-hook.patch) in case
that path is optimised later.

---

## Verification

| suite | result |
|---|---|
| spatialdata-io | 192 passed, 36 skipped |
| celldega Python | 389 passed |
| celldega JS | 131 passed, 18 suites |
| spatialdata core | 1,359 passed (unchanged by the hook) |

Also exercised end to end on two real datasets — Xenium pancreas (8.1 M transcripts,
377 genes) and Xenium Prime human skin (74 M transcripts, 5,006 genes) — rendering in
Celldega with images, cells, centroids, transcripts and CBG gene colouring.

Interop findings that contradict the original design assumptions are written up separately
in [`interop_findings.md`](interop_findings.md); several are worth reading before
reviewing the spec.
