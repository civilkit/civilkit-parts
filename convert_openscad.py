#!/usr/bin/env python3
"""Bulk-convert NopSCADlib vitamins (or any lib following its type-table convention) to STEP + manifest.

usage: convert_openscad.py LIBDIR OUTDIR [--category ball_bearing ...] [--limit N] [--jobs N] [--list]
Run with the venv python: .venv/bin/python convert_openscad.py ...
"""
import argparse, json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import ckcommon as C

OPENSCAD = os.environ.get("OPENSCAD", "/opt/homebrew/bin/openscad")
SRC_URL = "https://github.com/nophead/NopSCADlib"
LICENSE = "GPL-3.0-or-later"
TIMEOUT = 300

def enumerate_parts(lib):
    """(category, constant) pairs: file vitamins/<c>.scad defines module <c>(first_param, ...) with no other
    required params; constants are the `NAME = ["...` rows of vitamins/<c>s.scad (or <c>es.scad)."""
    out = []
    v = Path(lib) / "vitamins"
    for f in sorted(v.glob("*.scad")):
        c = f.stem
        m = re.search(r"^module\s+%s\s*\(([^)]*)\)" % re.escape(c), f.read_text(), re.M)
        if not m:
            continue
        params = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if any("=" not in p for p in params[1:]):
            continue  # needs extra required args (length, ...)
        for suf in ("s", "es"):
            t = v / f"{c}{suf}.scad"
            if t.exists():
                for k in re.finditer(r'^(\w+)\s*=\s*\[\s*"', t.read_text(), re.M):
                    out.append((c, k.group(1)))
                break
    return out

PRE = 'include <lib.scad>\nmodule color(c, alpha = 1) {%s}\n'
def run_scad(lib, body, args, out, timeout=TIMEOUT):
    with tempfile.NamedTemporaryFile("w", suffix=".scad", delete=False) as f:
        f.write(PRE % body + args); p = f.name
    try:
        r = subprocess.run([OPENSCAD, "-o", str(out), p], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "OPENSCADPATH": str(lib)})
        return r.stderr
    finally:
        os.unlink(p)

def convert_one(job):
    lib, outdir, cat, const, commit = job
    name = f"{cat}__{const}"
    d = Path(outdir) / cat; d.mkdir(parents=True, exist_ok=True)
    man = {"name": name, "category": cat, "source": {"url": SRC_URL, "commit": commit, "file": f"vitamins/{cat}.scad", "call": f"{cat}({const})"},
           "license": LICENSE, "generator": f"convert_openscad.py (OpenSCAD 2021.01 per-colour render, OCC sew)",
           "ok": False, "colors": [], "ckpart": None, "step": None, "bbox": None}
    t0 = time.time()
    call = f"{cat}({const});\n"
    try:
        # pass 1: palette via echo (CSG export, no CGAL)
        err = run_scad(lib, 'echo("CK", c, alpha); children();', call, os.devnull + ".csg" if False else Path(tempfile.gettempdir()) / f"{name}.csg")
        pal = []
        for m in re.finditer(r'ECHO: "CK", (.*), (\S+)$', err, re.M):
            k = (m.group(1), m.group(2))
            if k not in pal:
                pal.append(k)
        items = []
        groups = pal or [None]
        for gi, g in enumerate(groups):
            off = Path(tempfile.gettempdir()) / f"{name}_{gi}.off"
            off.unlink(missing_ok=True)
            body = "children();" if g is None else f"if (c == {g[0]} && alpha == {g[1]}) children();"
            run_scad(lib, body, call, off)
            if not off.exists():
                continue
            verts, faces = C.read_off(off)
            off.unlink()
            solid = C.mesh_to_solid(verts, faces)
            rgb = C.parse_colour(g[0]) if g else None
            items.append((f"{name}_c{gi}", solid, rgb))
            man["colors"].append({"openscad": g[0] if g else None, "alpha": g[1] if g else None, "rgb": rgb, "volume": round(solid.Volume(), 4)})
        if not items:
            raise RuntimeError("no geometry")
        step = d / f"{const}.step"
        C.write_step(items, step, name)
        man.update(ok=True, step=str(step.relative_to(outdir)), bbox=C.bbox_of([s for _, s, _ in items]), solids=len(items))
    except Exception as e:
        man["error"] = f"{type(e).__name__}: {e}"[:300]
    man["seconds"] = round(time.time() - t0, 2)
    C.write_manifest(d / f"{const}.manifest.json", man)
    return man

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lib"); ap.add_argument("out")
    ap.add_argument("--category", nargs="*"); ap.add_argument("--limit", type=int)
    ap.add_argument("--per-category", type=int); ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    lib = Path(a.lib).resolve()
    commit = subprocess.run(["git", "-C", str(lib), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    parts = enumerate_parts(lib)
    if a.category:
        parts = [p for p in parts if p[0] in a.category]
    if a.per_category:
        seen = {}; keep = []
        for c, k in parts:
            seen[c] = seen.get(c, 0) + 1
            if seen[c] <= a.per_category:
                keep.append((c, k))
        parts = keep
    if a.limit:
        parts = parts[:a.limit]
    if a.list:
        print("\n".join(f"{c} {k}" for c, k in parts)); print(len(parts), "parts", file=sys.stderr); return
    Path(a.out).mkdir(parents=True, exist_ok=True)
    t0 = time.time(); res = []
    with ProcessPoolExecutor(a.jobs) as ex:
        for m in ex.map(convert_one, [(str(lib), a.out, c, k, commit) for c, k in parts]):
            res.append(m)
            print(("ok  " if m["ok"] else "FAIL"), m["name"], m["seconds"], m.get("error", ""), flush=True)
    ok = sum(m["ok"] for m in res)
    print(f"{ok}/{len(res)} ok in {time.time()-t0:.0f}s")
    (Path(a.out) / "index.json").write_text(json.dumps([{k: m[k] for k in ("name", "category", "ok", "step", "seconds")} for m in res], indent=1))

if __name__ == "__main__":
    main()
