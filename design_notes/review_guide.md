# Review guide

Reviewed local branch heads on 2026-09-09:

| repository | branch | commit | role |
|---|---|---|---|
| spatialdata-io | `adapt_dega` | `88b8f10` | profile producer |
| celldega | `adapt_dega` | `2d6fc99` | native reader and optional WebP export |
| spatialdata | `main` | `ccf1ea0` | unmodified core |

Start with [proposal_summary.md](proposal_summary.md), then
[implementation_review.md](implementation_review.md) for confirmed issues. The current
layout and known conformance gaps are in [regular_grid_tiled_access.md](regular_grid_tiled_access.md).
[adapt_dega_plan.md](adapt_dega_plan.md) tracks delivered and remaining work.

## Reading order

1. `spatialdata-io/src/spatialdata_io/experimental/regular_grid.py`: tile math and numbering.
2. `feature_catalog.py`: table feature order followed by extra observed features.
3. `points_parquet.py`: canonical/display modes, stable sorting and multi-partition spill.
4. `shapes_parquet.py`: canonical GeoParquet, lossy display geometry and cell-code mapping.
5. `expression_index.py` and `display_colors.py`: `var` statistics, CSC and `uns` palettes.
6. `tiled_access.py` and `manifest.py`: sequencing, references and validation.
7. `celldega/js/spatialdata/`: AnnData reader, adapter, manifest options and native images.
8. `celldega/js/viz/landscape_ist.js` and metadata/cell-layer call sites: actual opt-in behavior.
9. `celldega/src/celldega/pre/spatialdata_images.py`: the optional WebP exporter.

The original full-profile branches are superseded. The current producer no longer writes
CBG, gene/cell metadata, clusters or transform CSV files into the profile. Cell centroids
use Shapes transforms, but Python widget transforms and scale-bar inference are not fully
adapted. DegaFiles still use the existing manifest and Parquet paths.

## Decisions to retain

- Keep scientific x/y and geometry authoritative; put interleaved float32 display geometry
  in separate Parquets. The tested Dask round-trip and parquet-wasm projection behavior
  support this choice. It avoids coordinate interleaving in JS, not every memory copy.
- Retain a CSR primary matrix where appropriate and add a CSC layer for column reads.
  CSC is another storage orientation of the same matrix, not a mathematical transpose.
- Keep gene colors in `uns["gene_colors"]`. Document the explicit `var_names` association
  and maintain it on gene reorder/subset; AnnData does not do that automatically.
- Keep WebP export in Celldega. Native profiles default to OME-Zarr; both paths currently
  produce 8-bit display images. A full DegaFiles exporter is not yet implemented here.

## Claims to qualify

The grid is reusable, but the full manifest still contains Celldega settings. Existing
SpatialData readers accept the store without core changes; ordinary saves do not preserve
its profile or row-group contract. Alternate names alone do not establish compatibility
with all valid SpatialData stores. Tile-aware Python reads can be cheap, but no core
SpatialData spatial-query acceleration has been added.

Two deferred defects are worth knowing before reading the code, both confirmed by
reproduction and both currently latent for Xenium:

- **Gene statistics can be wrong on integer matrices.** `csc.multiply(csc)` squares before
  the cast to float64, so an `int16` column `[300, 0]` reports `std=0` instead of `150`.
  Explicitly stored zeros are also counted as non-zero, because the count comes from
  `np.diff(csc.indptr)`. Xenium's `X` is float32 without stored zeros, so neither bites
  today. The fix is `matrix.astype(np.float64).tocsc(copy=True)` plus `eliminate_zeros()`.
- **Grid derivation transforms only the maximum x and y.** That is correct for the
  axis-aligned scale/translation Xenium uses and wrong for rotation, shear or a non-zero
  minimum. The profile should either validate that the transform is axis-aligned or
  transform all bounding-box corners.

Historical benchmark numbers are retained in [proposal_summary.md](proposal_summary.md)
with their baseline identified. They compare the earlier full profile with `adapt_dega`,
not an untiled stock store with a zero-cost extension. Old mixed compression/encoding
comparisons should not be used to promise general overhead or latency.

## Verification performed

| check | 2026-09-09 result |
|---|---|
| spatialdata-io six tiling suites | 118 passed, 1 skipped |
| spatialdata-io complete suite | 171 passed, 36 skipped |
| Celldega complete JS suite | 169 passed in 20 suites |
| Celldega Python suite, integration interpreter | 407 passed |
| raw-Xenium one-shot on real data | pancreas built in 49 s; store reopens with the CSC layer, `uns["gene_colors"]`, `var` statistics and a v3 table |
| review diagnostics | confirmed cell-link, dense-row-group and palette fixes; retained save, affine, gene-palette lifecycle and statistics reproductions |

Commands and reproduction details are in [the review](implementation_review.md) and
[integration/probes/README.md](../integration/probes/README.md). The environment-gated
raw-Xenium *test* still describes the superseded full profile and was not run; the one-shot
path was instead exercised directly against the real pancreas dataset, which is what the
row above records.

The existing notebook records manual comparisons on pancreas and skin. This review did
not rebuild the large reference datasets or rerun browser rendering. The unit suites do
not provide an automated producer-to-browser rendering test, which remains a significant
coverage gap. Test counts are a dated snapshot, not part of the protocol.
