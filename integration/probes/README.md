# Probes

Throwaway scripts that answer one question each by measurement, kept because the answers
are load-bearing for [`../../design_notes/adapt_dega_plan.md`](../../design_notes/adapt_dega_plan.md).

```bash
npm install                    # zarrita, numcodecs, @vivjs/loaders

# serve the built stores (the probes read pancreas_full.zarr over HTTP, as a browser would)
python -m http.server 8896 --bind 127.0.0.1 --directory ../../data

node zarrita_probe.mjs         # can zarrita read a spatialdata store as-is?      -> yes, entirely
node viv_probe.mjs             # can viv open the OME-Zarr images as written?     -> no, NGFF 0.4 vs 0.5
```

`zarrita_probe.mjs` walks the pieces the `adapt_dega` work depends on: the root group, an
image pyramid level, `var/_index` (`vlen-utf8` + zstd strings), the CSR components of `X`,
an `obs` categorical, and `obsm/spatial`. All of it reads with stock `zarrita` — no codec
registration, no shims.

`viv_probe.mjs` isolates the image failure. Viv looks for `multiscales` at the top of the
group attributes; SpatialData nests it under `ome`.
