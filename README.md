# Spatial tiling for SpatialData

Work on an opt-in profile that makes a SpatialData store directly viewable in
[Celldega](https://github.com/broadinstitute/celldega), without first exporting a separate
DegaFiles bundle — and without the store ceasing to be an ordinary SpatialData store.

This repository holds the **workspace**: notes, the integration environment, and the test
notebook. The code lives in three forks cloned alongside (and git-ignored here).

---

## The idea

```
raw Xenium ──spatialdata_io.xenium()──> normal SpatialData ──add_spatial_tiling()──> same store + profile
```

For an existing store, the opt-in tiling pass reads the store and:

- **reorders** canonical Points and Shapes into a deterministic tile grid, intended to
  have one Parquet row group per tile, for selective reads by a tile-aware client;
- in the proposed **canonical** layout, writes no display files: canonical Points keep
  separate `x`/`y`, canonical Shapes use GeoArrow polygons, and the root `zarr.json`
  carries the `spatial_tiling` manifest;
- adds gene statistics, palettes and a CSC expression layer to the table.

The proposal has three primary storage capabilities: spatially addressed Parquet row
groups plus root discovery metadata, GeoArrow polygon encoding for canonical Shapes, and
a gene-major `X_csc` layer alongside the analysis-oriented `X`. Gene statistics and the
`uns` palettes are supporting profile metadata. These are experimental conventions, not
three ratified changes to the SpatialData specification.

```
sample.zarr/
├── points/transcripts/points.parquet/      canonical columns, reordered into tile row groups
├── shapes/cell_boundaries/shapes.parquet   file or directory; geometry + cell_code
├── tables/table/
│   ├── var[mean|std|max|non_zero]          gene statistics
│   ├── uns["gene_colors"]                 gene colors, in var_names order
│   └── layers/X_csc                        gene-major expression, small fixed chunks
└── zarr.json
    └── attributes.spatial_tiling            root manifest for the canonical layout
```

Cell names and centroids, gene names, clusters, expression and images are read from the
store's own `obs`, `var`, `obsm`, `uns` and OME-Zarr. Centroids use the selected Shapes
transform; general registration and physical scale inference still need work. Native
OME-Zarr images are the new profile's default and are converted to 8-bit for rendering.
An optional WebP pyramid can be built by `celldega.pre.spatialdata_images`.

Celldega reads canonical transcript `x`, `y`, and `feature_name` columns directly. A custom
ScatterplotLayer binds the separate x/y Arrow buffers and applies the micron-to-pixel
affine transform on the GPU, resetting the rendered world z coordinate to zero. Canonical
GeoArrow polygons are decoded without WKB parsing, transformed into visible JavaScript
path arrays on the CPU, and rendered with deck.gl's standard `PathLayer`. The branch does
not use `@geoarrow/deck.gl-layers`.

The tiled store is readable by ordinary SpatialData. An ordinary SpatialData save to a
new store retains analysis content but does not promise to preserve the physical row-group
layout, so regenerate the profile after saving or changing source data.

`profile_layout="v1"` remains available for comparison and backward compatibility. It
writes interleaved display Parquets plus
`visualization/grid_files_v1/landscape_parameters.json`. Celldega continues to support
standalone DegaFiles through their existing `landscape_parameters.json`.

The entry point accepts alternate element/feature names, for example:

```python
from spatialdata_io.experimental import add_spatial_tiling

add_spatial_tiling(
    "merscope.zarr",
    points_element="detected_transcripts",
    shapes_element="cell_polygons",
    feature_key="gene",
    technology="MERSCOPE",
    profile_layout="canonical",
)
```

---

Current support targets Xenium's single table instance namespace, compatible
`obsm["spatial"]`, and a target coordinate system already in image-pixel space. Cell codes
are resolved through the table's SpatialData `region_key` and `instance_key`. This is
experimental, not support for every valid SpatialData store. See the
[implementation review](design_notes/implementation_review.md) for confirmed gaps.

## Layout

```
.
├── design_notes/          notes for reviewers (tracked here)
├── integration/           environment, test notebook, probes (tracked here)
├── spatialdata/           fork, ignored -- branch adapt_dega_v2, unmodified
├── spatialdata-io/        fork, ignored -- branch adapt_dega_v2
├── celldega/              fork, ignored -- branch adapt_dega_v2
└── data/                  ignored -- raw bundles and built stores, tens of GB
```

### Two directions

The earlier `feat/xenium-celldega-regular-grid` and `feat/spatialdata-regular-grid-reader`
branches made **SpatialData produce what Celldega reads**. The current `adapt_dega_v2`
branches instead make **Celldega read what SpatialData already writes** (`obs`/`var`/`X`
via zarrita), using the canonical transcript and boundary Parquets directly. See
[`design_notes/adapt_dega_plan.md`](design_notes/adapt_dega_plan.md); the feasibility
measurements behind it are reproducible via [`integration/probes/`](integration/probes/).

**SpatialData core is unmodified.** Experimental stores read without a core patch;
preserving the tile contract on save remains unresolved. The one-shot Xenium path still
writes canonical Points and Shapes once through `SpatialData.write()` and then replaces
their Parquets with tiled versions. A small Points/Shapes writer-options or writer-hook API
in SpatialData would let spatialdata-io supply the final tiled representation during the
initial write. A Points-only prototype is kept in `design_notes/` as a starting point.

Celldega temporarily uses `@cornhundred/parquet-wasm@0.7.2-celldega.0`, which carries the
column-projection fix pending upstream merge and release.

---

## Setup

Python 3.12 is the only version all three accept (celldega caps at `<3.13`, the other two
require `>=3.12`).

```bash
git clone git@github.com:cornhundred/spatialdata.git
git clone git@github.com:cornhundred/spatialdata-io.git
git clone git@github.com:cornhundred/celldega.git

# The forks have no tags, and both packages derive their version from tags via hatch-vcs.
# Without this the editable install reports something like 0.1.dev1+g<sha>, which then
# fails celldega's `spatialdata>=0.7.2` floor with a confusing error.
for r in spatialdata spatialdata-io; do
  git -C $r remote add upstream "https://github.com/scverse/$r.git"
  git -C $r fetch upstream --tags
done

git -C spatialdata-io switch adapt_dega_v2
git -C celldega     switch adapt_dega_v2

bash integration/setup_env.sh          # uv venv + editable installs + npm ci + build
git config core.hooksPath .githooks     # strips notebook widget state before commits
```

Register the kernel. The environment variables matter: celldega chooses its front-end
bundle at import time, and a clean `X.Y.Z` install silently serves the published bundle
from jsDelivr, so local `js/` edits do nothing with no warning anywhere.

```bash
integration/.venv/bin/python -m ipykernel install --user \
  --name spatial-tiles --display-name "spatial-tiles (integration)"
```

then add to `~/Library/Jupyter/kernels/spatial-tiles/kernel.json`:

```json
"env": { "ANYWIDGET_HMR": "1", "CELLDEGA_LOCAL_ESM": "1" }
```

`ANYWIDGET_HMR` also enables hot reload, so `npm run build` refreshes the widget without
restarting the kernel.

---

## Data

Not committed. Download and build:

```bash
mkdir -p data/xenium_data && cd data/xenium_data
curl -L -O https://cf.10xgenomics.com/samples/xenium/2.0.0/Xenium_V1_human_Pancreas_FFPE/Xenium_V1_human_Pancreas_FFPE_outs.zip
curl -L -O https://cf.10xgenomics.com/samples/xenium/3.0.0/Xenium_Prime_Human_Skin_FFPE/Xenium_Prime_Human_Skin_FFPE_outs.zip
for z in *.zip; do unzip -q "$z" -d "${z%.zip}"; done
```

```python
from spatialdata_io.experimental import xenium_spatially_tiled

xenium_spatially_tiled(
    "data/xenium_data/Xenium_V1_human_Pancreas_FFPE_outs",
    "data/pancreas_full.zarr",
    nucleus_boundaries=False, cells_labels=False, nucleus_labels=False,
    morphology_mip=False, morphology_focus=True, aligned_images=False,
    tiling={"profile_layout": "canonical"},
)
```

Reference DegaFiles for comparison:

```python
from celldega.pre.run_pre_processing import main
main(sample="Xenium_V1_human_Pancreas_FFPE_outs", data_root_dir="data/xenium_data",
     tile_size=250, image_tile_layer="all", path_dega_files="data/pancreas_degafiles",
     use_int_index=True, use_row_groups=True, max_row_groups_per_file=400)
```

> Build into a **clean** output directory. Re-running over an existing one skips tile
> generation and then writes a manifest with `use_row_groups: true` but no
> `row_group_files` or `tile_grid`, which silently disables row-group mode.

---

## Testing

```bash
jupyter lab integration/test_spatialdata_landscape.ipynb   # kernel: spatial-tiles
```

Four Landscapes: pancreas and skin, each as DegaFiles and as a tiled SpatialData store.
The DegaFiles views are the controls — reading across a row isolates the storage layout,
reading down a column isolates dataset scale.

```bash
(cd spatialdata-io && ../integration/.venv/bin/python -m pytest tests/ -q)
(cd celldega && ../integration/.venv/bin/python -m pytest tests/ -q --no-cov)
(cd celldega && npx jest --runInBand)
```

---

The 2026-09-09 review ran the six spatialdata-io tiling suites (118 passed, 1 skipped),
all Celldega JS tests (169 passed), and Celldega Python tests (407 passed). The
complete spatialdata-io suite is 171 passed, 36 skipped.
Use the integration interpreter explicitly: plain `npm test` also invokes `pytest`
from PATH, which can select a different Python installation.

## Notes

- [`design_notes/proposal_summary.md`](design_notes/proposal_summary.md) — what is actually
  being proposed: store conventions, implementation responsibilities and upstream scope.
- [`design_notes/implementation_review.md`](design_notes/implementation_review.md) —
  confirmed issues, reproductions, test results and recommendations.
- [`design_notes/review_guide.md`](design_notes/review_guide.md) — reading order for the
  diff, the measurement behind each non-obvious decision, storage figures, limitations.
- [`design_notes/interop_findings.md`](design_notes/interop_findings.md) — eight things
  that only surfaced by rendering in a real viewer. Every one failed *silently*. Worth
  reading before the spec.
- [`design_notes/regular_grid_tiled_access.md`](design_notes/regular_grid_tiled_access.md) —
  the current protocol, including explicitly documented implementation gaps.
- [`design_notes/spatialdata-points-writer-hook.patch`](design_notes/spatialdata-points-writer-hook.patch) —
  the dropped core change.

### Known limitations

- Cluster coloring defaults to one group unless `cluster_column` is provided. Configured
  palettes follow the categorical column's stored order, including unused categories.
- Cell codes use table row positions resolved through SpatialData region/instance keys.
- Each tile is written and footer-validated as one physical Parquet row group. A single
  tile above 67,108,864 rows is rejected rather than producing an ambiguous layout.
- Gene colors stay in `uns["gene_colors"]`; gene filtering/reordering needs explicit
  palette synchronization. Ordinary saves also require profile regeneration.
- Asset replacement is not transactional. The one-shot Xenium path writes table additions
  initially; the existing-store entry point still rewrites the table when indexing expression.
- Cell hover labels need `cats.nameMapping_inv`, which the profile does not populate.
- The Xenium `transcripts.zarr` fast path is not implemented — deferred, not cut.
- Browser rendering remains a manual integration check; unit tests cover manifest
  discovery, both transcript encodings, both polygon encodings and DegaFiles defaults.
