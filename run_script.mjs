#!/usr/bin/env node
// Run CivilKit scripts headless and write the parts they build.
// usage: KIT=<kit checkout> node run_script.mjs [--out DIR] a.ck.js b.ck.js ...
// Per script: <out>/<name>.ckpart (the recorded document, with the script in its `script` field) and one JSON line
// {file, ok, errors, volume, valid, features}. Needs the kit's node_modules and kernel wasm (CK_WASM, default apps/cad/public/kernel/ck_wasm.wasm).
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
const kit = process.env.KIT;
if (!kit) { console.error('set KIT to a kit checkout'); process.exit(2); }
const here = new URL('.', import.meta.url).pathname;
const r = spawnSync(resolve(kit, 'node_modules/.bin/vite-node'), ['--config', resolve(kit, 'vite.config.ts'), resolve(here, 'run_script_cli.ts'), '--', ...process.argv.slice(2)],
  { stdio: 'inherit', cwd: kit, env: { ...process.env, CK_WASM: process.env.CK_WASM ?? resolve(kit, 'apps/cad/public/kernel/ck_wasm.wasm'), INIT_CWD: process.cwd() } });
process.exit(r.status ?? 1);
