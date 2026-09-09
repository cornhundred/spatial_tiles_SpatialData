// Can viv's OME-Zarr loader read a SpatialData image group?
//
// `loadOmeZarr` takes a URL string and builds its own store -- passing a zarrita Location
// silently produces a broken store and an unrelated TypeError, which is what an earlier
// version of this probe did wrong.
//
// viv 0.22.1 does understand the NGFF 0.5 layout SpatialData writes:
//   const ngff_v0_5_or_later = "ome" in unknownAttrs;
//   const rootAttrs = ngff_v0_5_or_later ? unknownAttrs.ome : unknownAttrs;
import { loadOmeZarr } from '@vivjs/loaders';

const URL_ =
  process.env.IMAGE_URL ??
  'http://127.0.0.1:8896/pancreas_full.zarr/images/morphology_focus';

try {
  const src = await loadOmeZarr(URL_, { type: 'multiscales' });
  console.log('  OK    loadOmeZarr accepted the SpatialData image group');
  console.log(`        resolutions : ${src.data.length}`);
  console.log(`        base shape  : ${src.data[0].shape}`);
  console.log(`        labels      : ${src.data[0].labels}`);
  console.log(`        dtype       : ${src.data[0].dtype}`);
  console.log(`        tile size   : ${src.data[0].tileSize}`);

  const channels = src.metadata?.omero?.channels;
  if (channels) {
    console.log(
      `        channels    : ${channels.map((c) => c.label ?? c.window?.end).join(', ')}`
    );
  }

  // Coarsest level first -- one tile there is the cheapest possible read.
  const level = src.data.length - 1;
  let t0 = Date.now();
  const tile = await src.data[level].getTile({ x: 0, y: 0, selection: { c: 0 } });
  console.log(
    `  OK    getTile level ${level}: ${tile.width}x${tile.height} ${tile.data.constructor.name} in ${Date.now() - t0} ms`
  );

  // And one tile at full resolution, which is what panning at max zoom costs.
  t0 = Date.now();
  const full = await src.data[0].getTile({ x: 0, y: 0, selection: { c: 0 } });
  console.log(
    `  OK    getTile level 0 : ${full.width}x${full.height} in ${Date.now() - t0} ms`
  );
} catch (e) {
  console.log('  FAIL  loadOmeZarr');
  console.log(`        ${e.name}: ${String(e.message).slice(0, 400)}`);
}
