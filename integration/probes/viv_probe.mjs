// Does viv's OME-Zarr loader accept a spatialdata-written image group?
// The group declares  ome.version = "0.5-dev-spatialdata"  (not a released NGFF version).
import * as zarr from 'zarrita';
import { loadOmeZarr } from '@vivjs/loaders';

const store = new zarr.FetchStore('http://127.0.0.1:8896/pancreas_full.zarr');
const root = zarr.root(store);

try {
  const src = await loadOmeZarr(root.resolve('images/morphology_focus'), { type: 'multiscales' });
  console.log('  OK    loadOmeZarr accepted the group');
  console.log('        resolutions :', src.data.length);
  console.log('        base shape  :', src.data[0].shape);
  console.log('        labels      :', src.data[0].labels);
  console.log('        meta keys   :', Object.keys(src.metadata ?? {}));
  const t0 = Date.now();
  const tile = await src.data[src.data.length - 1].getRaster({ selection: { c: 0, y: 0, x: 0 } });
  console.log(`  OK    getRaster on coarsest level: ${tile.width}x${tile.height} in ${Date.now() - t0} ms`);
} catch (e) {
  console.log('  FAIL  loadOmeZarr rejected the group');
  console.log('        ', e.name + ':', String(e.message).slice(0, 500));
}
