// Can viv's OME-Zarr loader be made to read a SpatialData image group?
//
// viv looks for `multiscales` at the top of the group attributes (NGFF 0.4). SpatialData
// nests it under `ome` (NGFF 0.5). This tries a store wrapper that lifts `ome` up as the
// zarr.json goes past, which would be the whole fix if it works.
import * as zarr from 'zarrita';
import { loadOmeZarr } from '@vivjs/loaders';

const BASE = 'http://127.0.0.1:8896/pancreas_full.zarr';

/** Rewrites group metadata on the way through: attrs.ome.* -> attrs.* */
class NgffCompatStore {
  constructor(inner) {
    this.inner = inner;
  }

  async get(key, opts) {
    const bytes = await this.inner.get(key, opts);
    if (!bytes || !String(key).endsWith('zarr.json')) return bytes;

    let json;
    try {
      json = JSON.parse(new TextDecoder().decode(bytes));
    } catch {
      return bytes;
    }

    const ome = json?.attributes?.ome;
    if (ome && (ome.multiscales || ome.omero)) {
      json.attributes = { ...json.attributes, ...ome };
      return new TextEncoder().encode(JSON.stringify(json));
    }
    return bytes;
  }
}

const attempt = async (label, location) => {
  try {
    const src = await loadOmeZarr(location, { type: 'multiscales' });
    console.log(`  OK    ${label}`);
    console.log(`        resolutions: ${src.data.length}`);
    console.log(`        base shape : ${src.data[0].shape}`);
    console.log(`        labels     : ${src.data[0].labels}`);
    console.log(`        dtype      : ${src.data[0].dtype}`);
    const meta = src.metadata;
    const channels = meta?.omero?.channels ?? meta?.channels;
    if (channels) {
      console.log(`        channels   : ${channels.map((c) => c.label ?? c.name).join(', ')}`);
    }
    const t0 = Date.now();
    const level = src.data.length - 1;
    const raster = await src.data[level].getRaster({ selection: { c: 0, y: 0, x: 0 } });
    console.log(
      `  OK    getRaster level ${level}: ${raster.width}x${raster.height} in ${Date.now() - t0} ms`
    );
    return true;
  } catch (e) {
    console.log(`  FAIL  ${label}`);
    console.log(`        ${e.name}: ${String(e.message).slice(0, 220)}`);
    return false;
  }
};

const plain = zarr.root(new zarr.FetchStore(BASE));
const shimmed = zarr.root(new NgffCompatStore(new zarr.FetchStore(BASE)));

console.log('\n=== unmodified (expected to fail) ===');
await attempt('loadOmeZarr on the store as written', plain.resolve('images/morphology_focus'));

console.log('\n=== with ome attrs lifted to the top level ===');
await attempt('loadOmeZarr through NgffCompatStore', shimmed.resolve('images/morphology_focus'));

console.log('');
