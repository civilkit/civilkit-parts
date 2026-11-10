// Line-JSON oracle for the transpiler: stdin {features:[...], variables:[...]} per line -> stdout {errors:[[id,{code,params}]], bodies:[[name,volume]]}.
// The transpiler asks which named bodies are alive after each boolean (a union leaves disjoint tools as separate lumps,
// a merged tool disappears), so later features only reference bodies that exist.
import { join } from 'node:path';
import { createInterface } from 'node:readline';
const K = process.env.CK_KERNEL; if (!K) { console.error('set CK_KERNEL'); process.exit(2); }
const { Session } = await import(join(K, 'packages/dist/session/src/session.js'));
const Q = await import(join(K, 'packages/dist/session/src/queries.js'));
const wasmPath = process.env.CK_WASM || join(K, 'target/wasm32-unknown-unknown/release/ck_wasm.wasm');
const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  let out;
  try {
    const req = JSON.parse(line);
    const doc = { format: 'ck-part', version: 1, name: 'o', features: req.features, seq: req.features.length + 1, rollback: null, material: 'steel', counters: {}, variables: req.variables ?? [] };
    const s = await Session.open(doc, { wasmPath });
    const rep = await s.regenReport();
    const m = await Q.massProps(s.kernel, { tag: s.tag, bodies: true });
    out = { errors: rep.errors, bodies: (m.bodies ?? []).map((b) => [b.name, b.volume]) };
    await s.close();
  } catch (e) { out = { errors: [], bodies: [], fatal: String(e.message ?? e).slice(0, 200) }; }
  process.stdout.write(JSON.stringify(out) + '\n');
}
