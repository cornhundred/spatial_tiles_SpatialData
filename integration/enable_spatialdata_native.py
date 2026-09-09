#!/usr/bin/env python
"""Add (or remove) the `spatialdata` block in a store's landscape_parameters.json.

Historical migration helper for the earlier full-profile Xenium stores. Current
spatialdata-io already writes this block; no migration is needed for fresh profiles.
The script assumes default Xenium element/table names and replaces native settings.

Only a legacy store that still has all metadata/expression/image Parquets can be switched
back with --off or partial native flags. Fresh adapt_dega profiles omit those files, so
removing the block does not turn them into DegaFiles.

    python integration/enable_spatialdata_native.py data/pancreas_full.zarr
    python integration/enable_spatialdata_native.py data/pancreas_full.zarr --native metadata
    python integration/enable_spatialdata_native.py data/pancreas_full.zarr --off
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROFILE = "visualization/grid_files_v1"
MANIFEST = "landscape_parameters.json"
COMPONENTS = ("metadata", "cbg", "images")


def manifest_path(store: Path) -> Path:
    path = store / PROFILE / MANIFEST
    if not path.exists():
        raise SystemExit(f"no manifest at {path}")
    return path


def _feature_catalog(store: Path) -> dict:
    """Rebuild the genes-then-controls ordering `feature_code` indexes.

    Stores written before spatialdata-io recorded this need it backfilled: `var` holds only
    the genes, while feature codes run past them into the control probes, so a viewer that
    reads gene names from `var` alone has no entry for a control transcript.
    """
    import zarr

    genes = [str(v) for v in zarr.open_group(str(store / "tables/table/var"), mode="r")["_index"][:]]

    import pyarrow.parquet as pq

    observed: set[str] = set()
    for f in sorted((store / "points/transcripts/points.parquet").glob("*.parquet")):
        table = pq.read_table(f, columns=["feature_name"])
        observed.update(str(v) for v in table.column("feature_name").to_pylist())

    extra = sorted(observed - set(genes))
    return {"n_genes": len(genes), "extra_features": extra}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path, help="path to the .zarr store")
    parser.add_argument(
        "--native",
        nargs="*",
        default=list(COMPONENTS),
        choices=COMPONENTS,
        help="components to read natively (default: all)",
    )
    parser.add_argument("--off", action="store_true", help="remove the block again")
    args = parser.parse_args()

    path = manifest_path(args.store)
    manifest = json.loads(path.read_text())

    if args.off:
        removed = manifest.pop("spatialdata", None)
        print(f"{path}: {'removed' if removed else 'no'} spatialdata block")
    else:
        block = {
            "store_url": "../..",
            "table": manifest.get("source", {}).get("table_element", "table"),
            "native": list(args.native),
        }
        image_element = manifest.get("source", {}).get("image_element")
        if image_element:
            block["image_element"] = image_element
        manifest["spatialdata"] = block
        manifest["feature_catalog"] = _feature_catalog(args.store)
        print(f"{path}: native = {block['native']}")

    path.write_text(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
