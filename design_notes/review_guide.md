# Review guide

Reviewed local branch heads and uncommitted changes on 2026-09-10:

| repository | branch | commit | role |
|---|---|---|---|
| spatialdata-io | `adapt_dega_v2` | `feaedf0` | profile producer |
| celldega | `adapt_dega_v2` | `e84a6c8` | native reader and optional WebP export |
| spatialdata | `adapt_dega_v2` | `ccf1ea0` | unmodified core |

Start with [proposal_summary.md](proposal_summary.md), then
[implementation_review.md](implementation_review.md) for confirmed issues. The current
layout and known conformance gaps are in [regular_grid_tiled_access.md](regular_grid_tiled_access.md).
[adapt_dega_plan.md](adapt_dega_plan.md) tracks delivered and remaining work.

## Reading order

1. `spatialdata-io/src/spatialdata_io/experimental/regular_grid.py`: tile math and numbering.
2. `feature_catalog.py`: table feature order followed by extra observed features.
3. `points_parquet.py`: canonical/display modes, column ordering, stable sorting and spill.
4. `shapes_parquet.py`: canonical GeoArrow, optional display geometry and cell-code mapping.
5. `expression_index.py` and `display_colors.py`: `var` statistics, CSC and `uns` palettes.
6. `tiled_access.py` and `manifest.py`: sequencing, references and validation.
7. `celldega/js/spatialdata/`: AnnData reader, adapter, manifest options and native images.
8. `celldega/js/viz/landscape_ist.js`, `separated_scatterplot_layer.js`, and tile readers:
   canonical rendering and the unchanged DegaFiles branch.
9. `celldega/src/celldega/pre/spatialdata_images.py`: the optional WebP exporter.

The original full-profile branches are superseded. The current producer no longer writes
CBG, gene/cell metadata, clusters or transform CSV files into the profile. Cell centroids
use Shapes transforms, but Python widget transforms and scale-bar inference are not fully
adapted. DegaFiles still use the existing manifest and Parquet paths.

## Decisions to retain

- Keep scientific x/y and geometry authoritative. Canonical x/y remain separate through
  GPU upload and are combined in the vertex shader. Canonical polygons use GeoArrow.
- Retain a CSR primary matrix where appropriate and add a CSC layer for column reads.
  CSC is another storage orientation of the same matrix, not a mathematical transpose.
- Keep gene colors in `uns["gene_colors"]`. Document the explicit `var_names` association
  and maintain it on gene reorder/subset; AnnData does not do that automatically.
- Keep WebP export in Celldega. Native profiles default to OME-Zarr; both paths currently
  produce 8-bit display images. A full DegaFiles exporter is not yet implemented here.

## Claims to qualify

The grid is reusable, and the canonical root manifest now omits Celldega UI settings.
Some profile and entry names still need upstream review. Existing SpatialData readers
accept the store without core changes; ordinary saves do not preserve its profile or
row-group contract. Alternate names alone do not establish compatibility with all valid
SpatialData stores. Tile-aware Python reads can be cheap, but no core SpatialData
spatial-query acceleration has been added.

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

| check | 2026-09-10 result |
|---|---|
| spatialdata-io canonical focused suite | 22 passed, 1 skipped |
| spatialdata-io complete suite | 173 passed, 36 skipped |
| Celldega complete JS suite | 180 passed in 21 suites |
| Celldega Python suite, integration interpreter | 406 passed, 1 skipped |
| raw-Xenium canonical build | pancreas built in 48 s; 8,073,840 points, 140,702 Shapes and `X_csc` reopen through SpatialData |
| browser integration | canonical SpatialData and DegaFiles control both rendered at close zoom without browser errors |

Commands and reproduction details are in [the review](implementation_review.md) and
[integration/probes/README.md](../integration/probes/README.md). The environment-gated
raw-Xenium *test* still describes the superseded full profile and was not run; the one-shot
path was instead exercised directly against the real pancreas dataset, which is what the
row above records.

The 2026-09-10 review rebuilt pancreas in 48 seconds and rendered both the canonical store
and DegaFiles control in Celldega's browser path. CI still lacks an automated
producer-to-browser rendering test. Test counts are a dated snapshot, not part of the
protocol.
