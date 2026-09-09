# Interop findings

Facts established by rendering the profile in a real viewer, several of which contradict
what the original protocol notes asserted. These are historical observations; see the
[current protocol](regular_grid_tiled_access.md) and [implementation review](implementation_review.md).
Each is recorded with how it was verified,
because each one produced a *silent* failure rather than an error.

---

## 1. Parquet has no fixed-size-list type

The original prototype wrote `display_xy` as `fixed_size_list<uint32>[2]` and
`display_geometry` as `list<list<fixed_size_list<uint32>[2]>>`. Current writers use
**unrounded float32**. In either case, **Parquet stores the nesting as plain `List`**. The historical
physical schema of our own file shows three nested `List`s where the Arrow schema reports
the fixed-size type:

```
display_geometry (List) { list { element (List) { list { element (List) { list { int32 } } } } } }
```

pyarrow reconstructs the fixed-size type only by reading the embedded `ARROW:schema` hint.
parquet-wasm 0.7.x *does* honour it (verified: it returns `typeId=16`), but a reader that
does not would see `List`.

**Consequence for the spec.** The protocol must say the vertex level may be *either*
`List` or `FixedSizeList`, and a client must accept both. Requiring `FixedSizeList`
regressed DegaFiles, whose polars `concat_list` column is a plain `List`.

**What it must still reject:** `struct<x, y>`, which GeoArrow also permits and which
`geopandas.to_parquet` emits. Walking child 0 there yields the x column alone and renders
wrong polygons with no error.

---

## 2. parquet-wasm's column projection is broken

Passing `columns` to `ParquetFile.read` corrupts the IPC stream it emits; the failure
surfaces later, in `tableFromIPC`:

```
TypeError: Cannot destructure property 'length' of '(intermediate value)' as it is undefined
```

Reproduced across:

| variable | values tried |
|---|---|
| parquet-wasm | 0.7.1, 0.7.2 (versions tested at the time) |
| apache-arrow | 15.0.2, 18.1.0 |
| column type | scalar (`cell_code`, `x`, `feature_code`) and nested (`display_xy`, `display_geometry`) |
| argument | one column, two columns, **and an empty array** |

Only reads that pass no `columns` succeed. `readParquet(..., {columns})` silently ignores
the argument instead, returning all columns.

**Consequence for the design.** Column projection is unusable, so the profile writes its
render columns to their own files instead: reading every column of a two-column file *is*
the projection. This also removed the need for any projection support in the client.

Worth reporting upstream.

---

## 3. A nested Arrow column cannot live in a canonical Points element

`SpatialData.write()` round-trips a Points element through dask's `to_parquet`, which
infers the schema from the pandas `_meta`. A nested column has `object` dtype there, so
dask declares it `string` and then either fails on the mismatch or **silently writes the
column as a string**:

| column encoding | `sdata.write()` |
|---|---|
| two scalar `uint32` columns | clean |
| nested `display_xy` | silently returns as `string`, or fails |
| pandas `ArrowDtype` | dask cannot read it back |

**Consequence.** The canonical element keeps only its own columns and the tile row
ordering; the render columns live in the profile's own files. This is the same change
point 2 forced, arrived at independently.

---

## 4. Files a client reads by convention, not through the manifest

The legacy DegaFiles/full-profile path fetches these relative to `base_url`. The current
native adapter replaces metadata, cluster and expression reads with AnnData sources.
The Python widget still has CSV-transform consumers; general transform integration is
not complete. In the legacy path, a missing or mis-shaped file
degrades silently — the viewer renders without that layer and logs nothing.

| file | contract | failure mode if wrong |
|---|---|---|
| `cell_metadata.parquet` | `name` + `geometry` as `[x, y]`; **row order is the integer cell id** | no cell centroids |
| `meta_gene.parquet` | gene name as the **unnamed** index, plus `color`, `mean`, `std`, `max`, `non-zero` | no gene list, so no transcript controls at all |
| `micron_to_image_transform.csv` | the real micron→pixel affine | Python widget coordinates fall back to identity; scale-bar defaults are separate |
| `cell_clusters/cluster.parquet` | cluster per cell | category machinery fails on the 404 |

Two traps inside `meta_gene.parquet`, each of which produced an empty gene list with no
error:

1. The gene list is read from the parquet **index**, not a `name` column.
2. pandas writes a *named* index as a column of that name. The index must be **unnamed**
   so pandas emits `__index_level_0__`, which is the only name the client looks for.

---

## 5. Image intensity should not be stretched

A percentile stretch is applied *on top of* the viewer's own intensity slider. Measured on
one Xenium DAPI tile:

| | mean | p50 | p99 | saturated (>=250) |
|---|---|---|---|---|
| DegaFiles | 1.3 | 0 | 10 | 0.0% |
| 1st–99.9th percentile stretch | 37.4 | 8 | 254 | 1.2% |

DegaFiles tiles are nearly black by design; the slider does the brightening. WebP export
therefore defaults to the full dtype range (a linear mapping, no stretch), with
`display_min`/`display_max` available to override and recorded in the manifest.

---

## 6. A trailing slash in `base_url` breaks relative paths

The readers join `${baseUrl}/${directory}/${file}`. A trailing slash produces `//`, an
empty path segment, which absorbs one `..`:

```
'http://h/s.zarr/visualization/prof/' + '../../points/x.parquet'
  -> /s.zarr/visualization/points/x.parquet   (404)
'http://h/s.zarr/visualization/prof'  + '../../points/x.parquet'
  -> /s.zarr/points/x.parquet                 (correct)
```

Harmless for a plain directory, fatal for one that climbs. Fixed by normalising the base
URL in all three readers rather than requiring one form.

---

## 7. Celldega's local server ignored `Range`

`CORSHTTPRequestHandler` advertised `Range` in its CORS headers but inherited
`SimpleHTTPRequestHandler.do_GET`, which ignores it and returns 200 with the whole file. A
`Range: bytes=0-7` request for a 3.86 MB chunk returned all 3,861,910 bytes.

Nothing reported it, because `RowGroupTileReader._checkRangeSupport` short-circuits to
`true` for localhost. **Every local row-group read was a full-file download**, which means
any local benchmark of the row-group path measured the wrong thing — for DegaFiles too,
not just the new profile. The adapt_dega local server now implements single-byte ranges
and suffix ranges; use that server for range-dependent probes.

---

## 8. Re-running Celldega preprocessing over an existing output corrupts its manifest

Tiles already present are skipped, and the manifest is then written **without
`row_group_files` or `tile_grid`** while still claiming `use_row_groups: true`. The client
falls back to per-tile files that do not exist, and nothing renders. A clean output
directory is required. Worth reporting upstream.
