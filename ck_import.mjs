// Import STEP parts into a CivilKit kernel session, validate, and optionally render a contact sheet.
// usage: CK_KERNEL=<kernel checkout> node ck_import.mjs [--sheet sheet.png] [--cols 6] part1.step part2.step ...
// Prints one JSON line per part: {file, ok, volume, faces, errors, validate}. CK_KERNEL needs packages/dist built and ck_wasm.wasm.
import { readFileSync, writeFileSync } from 'node:fs';
import { join, basename } from 'node:path';
const K = process.env.CK_KERNEL; if (!K) { console.error('set CK_KERNEL'); process.exit(2); }
const args = process.argv.slice(2); const files = []; let sheet, cols = 6;
for (let i = 0; i < args.length; i++) { if (args[i] === '--sheet') sheet = args[++i]; else if (args[i] === '--cols') cols = +args[++i]; else files.push(args[i]); }
const { Session } = await import(join(K, 'packages/dist/session/src/session.js'));
const Q = await import(join(K, 'packages/dist/session/src/queries.js'));
const { meshFromBody } = await import(join(K, 'packages/dist/render/src/mesh.js'));
const { renderTriangles } = await import(join(K, 'packages/dist/render/src/raster.js'));
const { encodePng } = await import(join(K, 'packages/dist/render/src/png.js'));
const wasmPath = process.env.CK_WASM || join(K, 'target/wasm32-unknown-unknown/release/ck_wasm.wasm');
const T = 300, tiles = [];
for (const f of files) {
  const r = { file: basename(f) };
  const t0 = Date.now();
  try {
    const s = await Session.open({ format: 'ck-part', version: 1, name: basename(f, '.step'), features: [] }, { wasmPath });
    const imp = await Q.importStep(s.kernel, readFileSync(f, 'utf8'), { tag: 'main', name: basename(f, '.step') });
    r.errors = imp.errors.length; r.faces = imp.import?.faces; r.solids = imp.import?.solids;
    const v = await Q.validate(s.kernel, { tag: 'main' });
    const mp = await Q.massProps(s.kernel, { tag: 'main' });
    r.validate = v.ok; r.volume = mp.volume; r.ok = imp.errors.length === 0 && v.ok && mp.volume > 0;
    if (sheet && imp.body) tiles.push(renderTriangles(meshFromBody(imp.body), 'iso', T, T, new Map()));
    await s.close();
  } catch (e) { r.ok = false; r.error = String(e.message ?? e).slice(0, 200); }
  r.ms = Date.now() - t0;
  console.log(JSON.stringify(r));
}
if (sheet && tiles.length) {
  const rows = Math.ceil(tiles.length / cols), W = cols * T, H = rows * T, rgb = new Uint8Array(W * H * 3).fill(255);
  tiles.forEach((t, i) => { const ox = (i % cols) * T, oy = Math.floor(i / cols) * T;
    for (let y = 0; y < T; y++) rgb.set(t.rgb.subarray(y * T * 3, (y + 1) * T * 3), ((oy + y) * W + ox) * 3); });
  writeFileSync(sheet, encodePng(W, H, rgb));
}
process.exit(0);
