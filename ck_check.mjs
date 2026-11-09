// Check .ckpart files with the kernel: regen errors, validate, volume, bbox, and (opt.) volume vs a STEP reference.
// usage: CK_KERNEL=<kernel checkout> node ck_check.mjs [--step-dir out] a.ckpart b.ckpart ...
// One JSON line per part: {file, ok, errors, validate, volume, box, refVolume, relErr}.
import { readFileSync, existsSync } from 'node:fs';
import { join, basename } from 'node:path';
const K = process.env.CK_KERNEL; if (!K) { console.error('set CK_KERNEL'); process.exit(2); }
const args = process.argv.slice(2); const files = []; let stepDir;
for (let i = 0; i < args.length; i++) { if (args[i] === '--step-dir') stepDir = args[++i]; else files.push(args[i]); }
const { Session } = await import(join(K, 'packages/dist/session/src/session.js'));
const Q = await import(join(K, 'packages/dist/session/src/queries.js'));
const wasmPath = process.env.CK_WASM || join(K, 'target/wasm32-unknown-unknown/release/ck_wasm.wasm');
async function stepVolume(f) {
  const s = await Session.open({ format: 'ck-part', version: 1, name: 'ref', features: [] }, { wasmPath });
  try {
    const imp = await Q.importStep(s.kernel, readFileSync(f, 'utf8'), { tag: 'main', name: 'ref' });
    if (imp.errors.length) return null;
    return (await Q.massProps(s.kernel, { tag: 'main' })).volume;
  } finally { await s.close(); }
}
for (const f of files) {
  const r = { file: basename(f) }; const t0 = Date.now();
  try {
    const doc = JSON.parse(readFileSync(f, 'utf8'));
    const s = await Session.open(doc, { wasmPath });
    const rep = await s.regenReport();
    r.errors = rep.errors.map((e) => JSON.stringify(e).slice(0, 160));
    const facts = await s.facts();
    r.solids = facts.solids; r.volume = facts.volume; r.box = facts.box; r.faces = facts.faces.length;
    const v = await s.validate(); r.validate = v.ok;
    if (!v.ok) r.issues = v.issues.slice(0, 3);
    r.ok = r.errors.length === 0 && v.ok && r.volume > 0;
    await s.close();
    const m = JSON.parse(readFileSync(f.replace(/\.ckpart$/, '.manifest.json'), 'utf8').toString());
    if (stepDir || m.step) {
      const sf = join(stepDir ?? 'out', m.step_ref ?? m.step ?? '');
      if (m.step_ref || m.step) { if (existsSync(sf)) { r.refVolume = await stepVolume(sf); if (r.refVolume) r.relErr = (r.volume - r.refVolume) / r.refVolume; } }
    }
  } catch (e) { r.ok = false; r.error = String(e.message ?? e).slice(0, 200); }
  r.ms = Date.now() - t0;
  console.log(JSON.stringify(r));
}
process.exit(0);
