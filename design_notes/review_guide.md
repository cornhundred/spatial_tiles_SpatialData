# Review guide

Two branches, both named `adapt_dega`. **spatialdata-io is the substance**; the celldega
branch is reader code and can be reviewed independently. **SpatialData core needs no change.**

| repo | branch | diff | status |
|---|---|---|---|
| spatialdata-io | `adapt_dega` | +3,615 / −1 | the proposal |
| celldega | `adapt_dega` | +3,310 / −55 | the reader (excluding the generated bundle) |
| spatialdata | — | — | **no change needed** |

Read [`proposal_summary.md`](proposal_summary.md) first if you only read one thing: it
separates *store conventions* (which any tool can consume) from *new code*.

> An earlier pair of branches — `feat/xenium-celldega-regular-grid` and
> `feat/spatialdata-regular-grid-reader` — are superseded. They wrote the viewer's whole
> bundle into the store. These branches keep only what Zarr genuinely cannot serve.

---

## What the proposal actually is

Row-group the canonical Points and Shapes into a deterministic tile grid, add a gene-major
copy of the expression matrix, and write two small display Parquets. Everything else a
viewer needs is read from the store's own `obs`, `var`, `obsm`, `uns` and OME-Zarr.

```
sample.zarr/
├── points/transcripts/points.parquet/      reordered into tile row groups
├── shapes/cell_boundaries/shapes.parquet/  same reordering
├── tables/table/
│   ├── var[mean|std|max|non_zero]          per-gene statistics
│   ├── uns[gene_colors]                    AnnData's <name>_colors convention
│   └── layers/X_csc                        gene-major, chunked per gene
└── visualization/grid_files_v1/
    ├── landscape_parameters.json
    ├── trx/                                display_xy + feature_code
    └── cell_seg/                           display_geometry + cell_code
```

Only the row reordering touches canonical data, and row order is meaningless for a point
cloud. Delete `visualization/` and the store is an ordinary SpatialData store.

---

## Reading order

**1. `regular_grid.py` (247)** — start here. Pure, dependency-light tile math that
everything else builds on.

```python
tile_x  = floor((x_px - origin_x) / tile_size_px)     # half-open bounds
tile_id = tile_x * num_tiles_y + tile_y               # x-major
file_index, local_row_group = divmod(tile_id, max_row_groups_per_file)
```

Reimplements Celldega's formula rather than importing it — Celldega already depends on
spatialdata-io, so importing back would be circular. A conformance test pins the two
together instead.

**2. `feature_catalog.py` (185)** — genes first in `var` order, controls appended after.
That ordering is load-bearing: `feature_code` *is* the position in this catalog. Because
`var` holds only the genes, the manifest records the control names — see the interop note
below.

**3. `points_parquet.py` (559)** — the main writer. Two paths that must agree:

```python
write_points_regular_grid(points, out, catalog=cat, grid=grid)                    # canonical
write_points_regular_grid(points, out, catalog=cat, grid=grid, render_only=True)  # display
```

In-memory below ~20 M rows; above that a two-pass spill. Grouping by tile is a *global*
sort, so streaming the read is not enough — pass 1 spills rows into per-output-file
buckets, pass 2 sorts each independently. A test asserts both paths produce identical row
groups.

**4. `expression_index.py` (197)** — the newest piece, and the one that makes CBG scale.
`var` statistics plus a gene-major `X_csc` layer, chunked by the *average gene* rather than
for whole-matrix reads.

**5. `shapes_parquet.py` (266)**, **`display_colors.py` (85)** — independent.

**6. `manifest.py` (206)** and **`tiled_access.py` (316)** — the entry points:

```python
add_spatial_tiling("sample.zarr")
xenium_spatially_tiled(raw, "out.zarr")
```

---

## Decisions worth checking, with the measurement behind each

| decision | why |
|---|---|
| tile size **250 px** | 21.0 cells/tile; 500 px gives 81 |
| **multi-file** output | a single 7,535-row-group file has a **7.4 MB footer** the browser must fetch before its first read; split, each is ~410 KB |
| **zstd** | snappy +38.5% vs zstd +4.9% over an untiled store, same write time |
| statistics **off** | the tile formula is the index; statistics only inflate the footer |
| zero-padded chunk names | dask globs and sorts lexicographically, where `chunk_10` precedes `chunk_2` |
| display columns in **separate files** | a nested Arrow column cannot survive dask's parquet round-trip, so `SpatialData.write()` broke |
| **float32** coordinates | uint32 rounding produced a visible lattice at high zoom |
| CSC as a **layer**, not the primary | `adata[cells]` is the dominant analysis access pattern and it is row access; flipping the primary would tax every scanpy user |
| CSC chunk = **2 genes** of non-zeros | AnnData chunks for whole-matrix reads (162,948 non-zeros against ~6,915 for one gene), costing 24× per gene |
| colours in **`uns`** | AnnData's existing `<name>_colors` convention; a `var["color"]` column would have been a new one |

### What was deliberately *not* put in spatialdata-io

- **the WebP pyramid** — moved to `celldega.pre.spatialdata_images`. An 8-bit lossy pyramid
  is a viewer artefact: 25 MB against 2.9 GB for the canonical uint16 image it derives from.
- **CBG Parquet, `meta_gene.parquet`, `cell_metadata.parquet`, `cell_clusters/`,
  `micron_to_image_transform.csv`** — all read from the store itself now.

---

## Cost

Measured on the rebuilt stores, Xenium pancreas (8.1 M transcripts, 377 genes) and Prime
skin (74 M, 5,006).

| | pancreas | skin |
|---|---|---|
| table, before → after | 7.9 MB → 17 MB | 58 MB → 162 MB |
| profile dir, before → after | 140 MB → 100 MB | 600 MB → 415 MB |
| **whole store** | **3.3 GB → 3.3 GB** | **5.1 GB → 5.1 GB** |

The store does not grow: the profile shrinks by more than the table grows. The gene-major
layer costs **1.9×** the CSR matrix (104 MB against 55 MB for skin) because chunking for
single-gene reads compresses worse — `genes_per_chunk` is the knob if that matters.

Tiling the canonical points costs **+39.8%** over an equivalently-compressed untiled store.
Fragmentation, not the extra columns: zstd compresses one large block far better than 7,535
small ones.

In the browser:

| | pancreas | skin |
|---|---|---|
| gene list | 0.017 MB | 0.126 MB |
| one gene | 0.084 MB | 0.060 MB |
| *whole matrix, the old way* | *4.5 MB* | *54.8 MB* |

A 12.8× larger matrix does not cost 12.8× more per gene — cost tracks non-zeros per gene,
which is roughly constant across datasets.

---

## celldega: `adapt_dega`

`js/spatialdata/` reads the store with zarrita and builds Arrow tables with the schemas
Celldega already consumed, so `set_meta_gene`, `set_color_dict_gene`,
`set_cell_names_array` and `get_scatter_data` are untouched — only the source of the bytes
changes. The adapter also duck-types `CBGRowGroupReader.readGene`, so the whole expression
path needed no changes at all.

Opt-in per component through the manifest's `spatialdata` block. A manifest without one
takes none of these paths, which is what keeps DegaFiles working; tests assert both
directions.

`celldega.pre.spatialdata_images` builds the 8-bit WebP pyramid from a store, using Pillow
rather than pyvips so no libvips install is needed. Its DeepZoom numbering is verified
against `vips dzsave`.

Also on this branch, worth landing regardless: an esbuild-time build stamp that prints the
branch and commit to the console. anywidget silently serves the published CDN bundle for a
clean `X.Y.Z` install, so local `js/` edits can do nothing with no warning — a failure mode
that already cost one debugging session.

---

## Verification

| suite | result |
|---|---|
| spatialdata-io | 168 passed, 36 skipped |
| celldega Python | 407 passed |
| celldega JS | 160 passed |

Exercised end to end on both datasets, rebuilt from raw data in 46 s (pancreas) and 151 s
(skin), rendering in Celldega with images, cells, centroids, transcripts and gene colouring.

Interop findings that contradict the original design assumptions are in
[`interop_findings.md`](interop_findings.md); several are worth reading before the spec.

### Known limitations

- Cluster colouring is a single placeholder group unless an `obs` column is named:
  SpatialData does not require a clustering and the Xenium reader does not load one.
- Cell hover labels need `cats.nameMapping_inv`, which the reader does not populate.
- The Xenium `transcripts.zarr` fast path is not implemented — deferred, not cut.
- There is **no automated end-to-end test that a written store renders**. The notebook is
  manual, and that gap is what let most of the interop findings through.
