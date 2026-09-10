# `adapt_dega` implementation review

Updated 2026-09-10 for spatialdata-io and Celldega `adapt_dega_v2`, with unmodified
SpatialData core. The latest fixes remain uncommitted pending review.

## Current conclusion

The design is a reasonable Xenium-focused integration boundary. SpatialData remains the
analysis representation. Canonical Points and Shapes receive deterministic spatial row
grouping. Points retain separate x/y columns and Shapes use GeoArrow polygons; Celldega
consumes both directly and applies their transforms. Table metadata, expression and
OME-Zarr images also come from the SpatialData store. No display Parquets are required.

The profile is experimental rather than a generic SpatialData specification. The reusable
piece to discuss upstream is the spatial index contract: coordinate frame, grid, tile
numbering, one physical row group per tile, instance association, discovery and lifecycle.
The current manifest still contains Celldega fields.

Gene colors use `uns["gene_colors"]`, aligned to `var_names`; they are not stored in `var`.
Cluster colors use `uns["<column>_colors"]`, aligned to the categorical column's stored
categories, including unused categories.

## Fixes in this review

0. **Canonical discovery and rendering.** Celldega falls back from
   `landscape_parameters.json` to `zarr.json` root attributes, projects canonical point
   columns, sends separate x/y buffers to a custom GPU shader, and accepts
   `geoarrow.polygon` boundaries. DegaFiles keep the file-first legacy path.

   `@geoarrow/deck.gl-layers` 0.3.2 was evaluated first. Its separated-coordinate helper
   allocates a new interleaved `Float64Array` and loops over every coordinate before
   rendering. The custom transcript shader is therefore the narrower zero-copy path; no
   GeoArrow deck.gl dependency is added to Celldega.

1. **Cell identity.** Boundary `cell_code` values now use absolute table row positions
   resolved through the SpatialData table's `region_key` and `instance_key`. The Xenium
   case is supported when its single table region is `cell_labels` and the requested
   boundary Shapes element is `cell_boundaries`, because both carry the same instance IDs.
   Multi-region tables require an exact element/region match.

2. **Physical row groups.** Every tile write supplies an explicit `row_group_size`, and
   staged Parquet footers are checked before publication. A tile above 67,108,864 rows is
   rejected. A regression test uses 1,048,577 rows, immediately above PyArrow's default
   split point.

3. **One-shot Xenium table write.** `xenium_spatially_tiled()` adds statistics, palettes and
   the CSC layer to the in-memory table before its initial `SpatialData.write()`. It then
   replaces the CSC buffers with the small chunks needed for browser gene reads. It does
   not delete and recreate the fresh table. Points and Shapes are still initially written
   by SpatialData and then replaced with tiled Parquets; avoiding that would require a
   deeper writer hook.

4. **Cluster palette order.** The JavaScript reader retains the encoded categorical order
   rather than sorting observed values, so `uns` colors stay associated with their labels.

5. **No-table manifest.** A no-table profile no longer advertises metadata or expression
   components backed by a nonexistent `tables/table`. It advertises native images and
   embeds feature names so transcript `feature_code` values remain decodable.

## Deferred limitations

- Ordinary `SpatialData.write()` does not preserve the visualization directory, Parquet
  row-group layout or tuned CSC chunks. The profile must be regenerated after such a save.
- `uns["gene_colors"]` does not automatically follow gene subset/reorder operations. The
  writer currently preserves an existing palette without validating that association.
- Grid derivation and browser placement are not generic for arbitrary affine transforms or
  registered coordinate systems. The current claim is limited to the tested Xenium layout.
- Native OME-Zarr uint16 values are read successfully, then windowed into uint8 RGBA for
  the current image layers. Preserved 16-bit interactive contrast is future work.
- Expression statistics need stronger handling for integer overflow, explicitly stored
  sparse zeros and noncanonical sparse inputs. CSC dtype and large-index limits also need
  an explicit contract.
- Existing-store expression indexing is not transactional because it deletes and rewrites
  the table. The optimized one-shot Xenium path avoids this particular risk.
- Browser rendering is still an integration check rather than an automated CI test. The
  2026-09-10 check rendered both the rebuilt pancreas canonical store and its DegaFiles
  control at close zoom with no new browser errors.

## Verification

- spatialdata-io six tiling suites: 118 passed, 1 skipped.
- Celldega complete JavaScript suite: 169 passed in 20 suites.
- spatialdata-io complete suite: 171 passed, 36 skipped.
- The dense-tile regression confirms one footer row group for 1,048,577 rows.
- The cell-link regression deliberately makes `obs_names` disagree with `instance_key`.
- The palette regression includes nonalphabetical and unused categories.
- The one-shot regression fails if table deletion is attempted.

The diagnostics in `integration/probes/review_adapt_dega.py` and
`integration/probes/review_adapt_dega.mjs` retain checks for the resolved issues and the
deferred save, affine, palette-lifecycle and statistics limitations.
