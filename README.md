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

Two phases. The first is stock SpatialData. The second reads that store back and:

- **reorders** rows in the canonical Points and Shapes into a deterministic tile grid, one
  Parquet row group per tile — which also makes spatial subsetting cheap from Python
  (a 20-tile read is ~8 ms on 8 M transcripts, ~10 ms on 74 M);
- **writes derived files** under `visualization/grid_files_v1/` holding everything a viewer
  needs and nothing a scientist does.

```
sample.zarr/
├── points/transcripts/points.parquet/      canonical columns, reordered into tile row groups
├── shapes/cell_boundaries/shapes.parquet/  canonical GeoParquet, same reordering
└── visualization/grid_files_v1/            all derived, all regenerable
    ├── landscape_parameters.json           the manifest
    ├── trx/                                display_xy + feature_code
    ├── cell_seg/                           display_geometry + cell_code
    ├── cbg/                                gene-major expression, one gene per row group
    ├── images/<channel>/                   WebP pyramid per channel
    ├── cell_metadata.parquet               cell centroids + names
    ├── meta_gene.parquet                   per-gene stats + colours
    ├── micron_to_image_transform.csv       micron→pixel affine
    └── cell_clusters/                      placeholder clustering
```

Delete `visualization/` and you have an ordinary SpatialData store back. The row ordering
is the only change to canonical data, and row order is meaningless for a point cloud.

Nothing in the profile is instrument-specific except default argument values, so it
converts an existing store from any reader:

```python
from spatialdata_io.experimental import add_spatial_tiling

add_spatial_tiling(
    "merscope.zarr",
    points_element="detected_transcripts",
    shapes_element="cell_polygons",
    feature_key="gene",
    technology="MERSCOPE",
)
```

---

## Layout

```
.
├── design_notes/          notes for reviewers (tracked here)
├── integration/           environment + the test notebook (tracked here)
├── spatialdata/           fork, ignored -- should be on `main`, unmodified
├── spatialdata-io/        fork, ignored -- branch feat/xenium-celldega-regular-grid
├── celldega/              fork, ignored -- branch feat/spatialdata-regular-grid-reader
└── data/                  ignored -- raw bundles and built stores, tens of GB
```

**SpatialData core needs no change.** A `points_writer` hook was prototyped and dropped
because nothing used it; the patch is kept in `design_notes/` if it is ever wanted.

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

git -C spatialdata-io switch feat/xenium-celldega-regular-grid
git -C celldega     switch feat/spatialdata-regular-grid-reader

bash integration/setup_env.sh          # uv venv + editable installs + npm ci + build
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
    tiling={"image_element": "morphology_focus"},
    nucleus_boundaries=False, cells_labels=False, nucleus_labels=False,
    morphology_mip=False, morphology_focus=True, aligned_images=False,
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
cd spatialdata-io && ../integration/.venv/bin/python -m pytest tests/ -q   # 193 passed
cd celldega && ../integration/.venv/bin/python -m pytest tests/ -q         # 389 passed
cd celldega && npx jest                                                    # 131 passed
```

---

## Notes

- [`design_notes/review_guide.md`](design_notes/review_guide.md) — reading order for the
  diff, the measurement behind each non-obvious decision, storage figures, limitations.
- [`design_notes/interop_findings.md`](design_notes/interop_findings.md) — eight things
  that only surfaced by rendering in a real viewer. Every one failed *silently*. Worth
  reading before the spec.
- [`design_notes/regular_grid_tiled_access.md`](design_notes/regular_grid_tiled_access.md) —
  the protocol, written viewer-independently. Two claims in it are corrected by the
  interop findings.
- [`design_notes/spatialdata-points-writer-hook.patch`](design_notes/spatialdata-points-writer-hook.patch) —
  the dropped core change.

### Known limitations

- Cluster colouring is a single placeholder group; SpatialData does not require a
  clustering and the Xenium reader does not load one.
- Cell hover labels need `cats.nameMapping_inv`, which the profile does not populate.
- The Xenium `transcripts.zarr` fast path is not implemented — deferred, not cut.
- There is **no automated end-to-end test that a written store renders**. The notebook is
  manual, and that gap is what let most of the interop findings through.
