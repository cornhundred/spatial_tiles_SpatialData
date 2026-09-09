// Bundle with celldega/node_modules/.bin/esbuild --bundle --platform=node
// --format=esm --outfile=/tmp/review-adapt-dega.mjs, then run with node.
// Uses controlled store responses to exercise the real adapter, without network IO.
import { SpatialDataAdapter } from "../../celldega/js/spatialdata/adapter.js";
import { tileToRgba } from "../../celldega/js/spatialdata/image_source.js";

const adapter = new SpatialDataAdapter("http://unused.invalid", {
  clusterColumn: "cluster",
});
adapter.store.cellNames = async () => ["cell1", "cell2"];
adapter.store.obsColumn = async () => ["B", "A"];
// AnnData category order is B, A, unused; the colors follow that order.
adapter.store.obsCategorical = async () => ({
  values: ["B", "A"],
  categories: ["B", "A", "unused"],
  codes: new Int8Array([0, 1]),
});
adapter.store.unsArray = async () => ["#ff0000", "#00ff00", "#0000ff"];
const meta = await adapter.metaClusterTable();
const actual = Object.fromEntries(
  Array.from({ length: meta.numRows }, (_, i) => [
    meta.getChild("__index_level_0__").get(i),
    meta.getChild("color").get(i),
  ]),
);
console.log(
  JSON.stringify(
    {
      cluster_palette: { expected: { B: "#ff0000", A: "#00ff00" }, actual },
      uint16_conversion: {
        input: [0, 1, 128, 129, 256],
        output_red: Array.from(
          tileToRgba(new Uint16Array([0, 1, 128, 129, 256]), 5, 1, [0, 65535]),
        ).filter((_, i) => i % 4 === 0),
      },
    },
    null,
    2,
  ),
);
