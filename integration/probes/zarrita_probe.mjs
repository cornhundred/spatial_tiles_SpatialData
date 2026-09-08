// Can zarrita read a real spatialdata-written store as-is?
// The store is Zarr v3, every array zstd-compressed, strings as vlen-utf8,
// and the OME metadata declares version "0.5-dev-spatialdata".
import * as zarr from 'zarrita';

const BASE = 'http://127.0.0.1:8896/pancreas_full.zarr';
const store = new zarr.FetchStore(BASE);
const root = zarr.root(store);

const ok = (s) => console.log(`  OK    ${s}`);
const bad = (s, e) => console.log(`  FAIL  ${s}\n          ${e.name}: ${String(e.message).slice(0, 200)}`);

async function step(label, fn) {
  try { await fn(); } catch (e) { bad(label, e); }
}

console.log('\n=== 1. root group ===');
await step('open root', async () => {
  const root = await zarr.open(store, { kind: 'group' });
  ok(`root group, zarr_format inferred; attrs keys = ${Object.keys(root.attrs)}`);
});

console.log('\n=== 2. image pyramid (uint16, zstd, chunk 1x4096x4096) ===');
await step('read image tile', async () => {
  const arr = await zarr.open(root.resolve('images/morphology_focus/s3'), { kind: 'array' });
  ok(`s3 shape=${arr.shape} dtype=${arr.dtype} chunks=${arr.chunks}`);
  const t0 = Date.now();
  const view = await zarr.get(arr, [0, zarr.slice(0, 256), zarr.slice(0, 256)]);
  ok(`read 256x256 window in ${Date.now() - t0} ms, first px = ${view.data[0]}`);
});

console.log('\n=== 3. gene names (string array: vlen-utf8 + zstd) ===');
await step('read var/_index', async () => {
  const arr = await zarr.open(root.resolve('tables/table/var/_index'), { kind: 'array' });
  ok(`var/_index shape=${arr.shape} dtype=${arr.dtype}`);
  const v = await zarr.get(arr, [zarr.slice(0, 5)]);
  ok(`first 5 genes = ${JSON.stringify(Array.from(v.data))}`);
});

console.log('\n=== 4. CBG as CSR (X/data, X/indices, X/indptr) ===');
await step('read CSR pieces', async () => {
  const indptr = await zarr.open(root.resolve('tables/table/X/indptr'), { kind: 'array' });
  ok(`indptr shape=${indptr.shape} dtype=${indptr.dtype}`);
  const t0 = Date.now();
  const head = await zarr.get(indptr, [zarr.slice(0, 3)]);
  ok(`indptr[0:3] = ${Array.from(head.data)} in ${Date.now() - t0} ms`);
  const data = await zarr.open(root.resolve('tables/table/X/data'), { kind: 'array' });
  ok(`X/data shape=${data.shape} dtype=${data.dtype} chunks=${data.chunks}`);
});

console.log('\n=== 5. obs categorical (region: codes + categories) ===');
await step('read obs/region', async () => {
  const codes = await zarr.open(root.resolve('tables/table/obs/region/codes'), { kind: 'array' });
  const cats = await zarr.open(root.resolve('tables/table/obs/region/categories'), { kind: 'array' });
  const c = await zarr.get(cats, [zarr.slice(0, 3)]);
  ok(`codes shape=${codes.shape} dtype=${codes.dtype}; categories = ${JSON.stringify(Array.from(c.data))}`);
});

console.log('\n=== 6. cell centroids (obsm/spatial) ===');
await step('read obsm/spatial', async () => {
  const arr = await zarr.open(root.resolve('tables/table/obsm/spatial'), { kind: 'array' });
  ok(`obsm/spatial shape=${arr.shape} dtype=${arr.dtype} chunks=${arr.chunks}`);
  const v = await zarr.get(arr, [zarr.slice(0, 2), null]);
  ok(`first 2 centroids = ${Array.from(v.data)}`);
});

console.log('');
