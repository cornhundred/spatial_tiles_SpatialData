"""Small diagnostic checks for the 2026-09-09 adapt_dega review.

Run from the workspace with integration/.venv/bin/python. All stores are temporary;
the script reports fixed behavior and known deferred limitations. No reference datasets
are modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import scipy.sparse as sp
from anndata import AnnData
from shapely.geometry import box
from spatialdata import SpatialData, read_zarr
from spatialdata.models import PointsModel, ShapesModel, TableModel

from spatialdata_io.experimental.display_colors import add_gene_colors
from spatialdata_io.experimental.expression_index import add_gene_statistics
from spatialdata_io.experimental.feature_catalog import FeatureCatalog
from spatialdata_io.experimental.points_parquet import DisplayTransform, write_points_regular_grid
from spatialdata_io.experimental.regular_grid import RegularGrid
from spatialdata_io.experimental.tiled_access import add_spatial_tiling


def make_store(path: Path, *, string_ids: bool = True) -> None:
    points = PointsModel.parse(
        pd.DataFrame({"x": [1.0, 11.0], "y": [1.0, 11.0],
                      "feature_name": pd.Categorical(["G1", "G2"])}),
        feature_key="feature_name",
    )
    ids = ["a", "b"] if string_ids else [10, 20]
    shapes = ShapesModel.parse(gpd.GeoDataFrame(geometry=[box(1, 1, 2, 2), box(11, 11, 12, 12)], index=ids))
    obs = pd.DataFrame({"region": pd.Categorical(["cells", "cells"]),
                        "instance_id": ids[::-1]}, index=["a", "b"])
    table = TableModel.parse(
        AnnData(X=sp.csr_matrix([[1.0, 0], [0, 2.0]]), obs=obs,
                var=pd.DataFrame(index=["G1", "G2"])),
        region="cells", region_key="region", instance_key="instance_id",
    )
    table.obsm["spatial"] = np.array([[11.5, 11.5], [1.5, 1.5]])
    SpatialData(points={"transcripts": points}, shapes={"cells": shapes}, tables={"table": table}).write(path)


def parquet_layout(path: Path) -> dict:
    files = sorted(path.glob("*.parquet")) if path.is_dir() else [path]
    readers = [pq.ParquetFile(f) for f in files]
    return {"row_groups": sum(r.num_row_groups for r in readers),
            "has_tile_metadata": all(b"tile_grid" in (r.schema_arrow.metadata or {}) for r in readers)}


def main() -> None:
    report = {}
    with TemporaryDirectory(prefix="adapt-dega-review-") as tmp:
        root = Path(tmp)
        store = root / "valid.zarr"
        make_store(store)
        manifest = add_spatial_tiling(store, shapes_element="cells", tile_size_px=10)
        shapes = read_zarr(store).shapes["cells"]
        report["cell_link"] = {"expected_codes_by_shape": {"a": 1, "b": 0},
                               "actual_codes_by_shape": shapes["cell_code"].to_dict()}
        report["canonical_shape_columns"] = list(shapes.columns)
        report["rounding_metadata"] = manifest["row_group_files"]["transcripts"]["display_transform"]["rounding"]
        report["before_save"] = parquet_layout(store / "points/transcripts/points.parquet")
        copy = root / "rewritten.zarr"
        read_zarr(store).write(copy)
        report["after_save"] = parquet_layout(copy / "points/transcripts/points.parquet")
        report["after_save"]["visualization_exists"] = (copy / "visualization").exists()
        report["after_save"]["csc_exists"] = "X_csc" in read_zarr(copy).tables["table"].layers

        integer_store = root / "integer_ids.zarr"
        make_store(integer_store, string_ids=False)
        try:
            add_spatial_tiling(integer_store, shapes_element="cells", tile_size_px=10)
            report["integer_instance_ids"] = "accepted"
        except ValueError as exc:
            report["integer_instance_ids"] = str(exc)

        no_table = root / "no_table.zarr"
        make_store(no_table)
        m = add_spatial_tiling(no_table, table_element=None, shapes_element=None, tile_size_px=10)
        report["table_none_manifest"] = {"spatialdata": m["spatialdata"], "feature_catalog": m["feature_catalog"]}

        failed_store = root / "failed_write.zarr"
        make_store(failed_store)
        with patch.object(SpatialData, "write_element", side_effect=RuntimeError("injected write failure")):
            try:
                add_spatial_tiling(failed_store, shapes_element="cells", tile_size_px=10)
            except RuntimeError:
                report["failed_table_write"] = {"table_path_exists": (failed_store / "tables/table").exists()}

        affine_points = pd.DataFrame({"x": [1., 9.], "y": [9., 1.], "feature_name": ["G1", "G1"]})
        try:
            write_points_regular_grid(
                affine_points, root / "affine", catalog=FeatureCatalog(("G1",), 1), tile_size_px=2,
                display_transform=DisplayTransform(((1, -1, 10), (0, 1, 0)), "global"), render_only=True,
            )
            report["affine_grid"] = "accepted"
        except ValueError as exc:
            report["affine_grid"] = str(exc)

        dense_tile = pd.DataFrame({"x": np.ones(1_048_577), "y": np.ones(1_048_577),
                                  "feature_name": pd.Categorical(["G1"] * 1_048_577)})
        tiled = root / "dense_tile"
        m = write_points_regular_grid(
            dense_tile, tiled, catalog=FeatureCatalog(("G1",), 1),
            grid=RegularGrid(0, 0, 10, 1, 1),
            display_transform=DisplayTransform(((1, 0, 0), (0, 1, 0)), "global"), render_only=True,
        )
        report["dense_tile"] = {"declared_row_groups": m["total_row_groups"], **parquet_layout(tiled)}

    palette = AnnData(X=np.zeros((1, 3)), var=pd.DataFrame(index=["A", "B", "C"]))
    add_gene_colors(palette)
    reordered = palette[:, [2, 0, 1]].copy()
    report["gene_palette_reorder"] = {"genes": list(reordered.var_names),
        "actual": list(reordered.uns["gene_colors"]),
        "expected": [palette.uns["gene_colors"][i] for i in [2, 0, 1]]}

    stats = AnnData(X=sp.csr_matrix(np.array([[300], [0]], dtype=np.int16)))
    add_gene_statistics(stats)
    report["integer_stats"] = {"expected_std": 150.0, "actual_std": float(stats.var["std"].iloc[0])}
    zeros = AnnData(X=sp.csr_matrix((np.array([0., 2.]), np.array([0, 0]), np.array([0, 1, 2])), shape=(2, 1)))
    add_gene_statistics(zeros)
    report["stored_zero_stats"] = {"expected_non_zero": 0.5, "actual_non_zero": float(zeros.var["non_zero"].iloc[0])}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
