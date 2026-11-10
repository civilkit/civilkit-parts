// CLI behind run_script.mjs (runs inside the kit through vite-node, so its aliases resolve).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { basename, resolve } from 'node:path';
const KIT = process.env.KIT!;
const { Session } = await import('@ck/session');
const { emptyPart } = await import('@ck/part-model');
const { createStore } = await import('@kit/store');
const { Controller } = await import(resolve(KIT, 'apps/cad/src/controller'));
const { runScript } = await import(resolve(KIT, 'packages/script/src/index'));
const wasmPath = process.env.CK_WASM!;
const cwd = process.env.INIT_CWD ?? process.cwd();
const args = process.argv.slice(2);
let out = cwd; const files: string[] = [];
while (args.length) { const a = args.shift()!; if (a === '--out') out = resolve(cwd, args.shift()!); else files.push(resolve(cwd, a)); }
mkdirSync(out, { recursive: true });
for (const f of files) {
  const id = basename(f).replace(/\.ck\.js$|\.js$/, '');
  const res: Record<string, unknown> = { file: id, ok: false };
  const sessions: any[] = [];
  try {
    const store = createStore();
    const kernel = { async open(d: any) { const s = await Session.open(d, { wasmPath }); sessions.push(s); return s; } };
    const controller = new Controller({ store, view: { setBody() {}, setHighlight() {}, setSketchEdit() {} }, kernel } as any);
    const host = {
      load: (d: any) => controller.load({ ...emptyPart('x'), ...d }),
      edit: (ops: any, why: any) => controller.edit(ops, why) as never,
      geometry: () => ({ mesh: controller.bodyFaces(), edges: controller.bodyEdges(), box: controller.bodyBox() }),
    };
    const r = await runScript(readFileSync(f, 'utf8'), host as any);
    if (!r.errors) console.error('RAW', JSON.stringify(r).slice(0, 700));
    res.errors = r.errors.map((e: any) => `Line ${e.line}: ${e.message}`).slice(0, 5);
    res.warnings = (r.warnings ?? []).length;
    const s = sessions.at(-1);
    if (process.env.DEBUG) { console.error(JSON.stringify((r.document as any)?.features?.map((x: any) => x.type + ':' + x.id)), 'sessions', sessions.length); }
    mkdirSync(out, { recursive: true }); if (r.document) writeFileSync(resolve(out, id + '.raw.ckpart'), JSON.stringify(r.document));
    if (!r.errors.length && s) {
      res.volume = ((await s.massProps()) as { volume: number }).volume;
      res.valid = ((await s.validate()) as { ok: boolean }).ok;
      res.features = ((r.document as any)?.features ?? []).length;
      writeFileSync(resolve(out, id + '.ckpart'), JSON.stringify(r.document));
      res.ok = !!res.valid;
    }
  } catch (e) { res.errors = [String((e as Error).stack ?? e).split("\n").slice(0, 4).join(" | ").slice(0, 400)]; }
  finally { for (const s of sessions) await s.close().catch(() => {}); }
  console.log(JSON.stringify(res));
}
process.exit(0);
