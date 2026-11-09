#!/usr/bin/env python3
"""Run CadQuery scripts that define `assembly` (cq.Assembly) or `result` (Workplane/Shape), export coloured STEP + manifest.

usage: .venv/bin/python convert_cadquery.py OUTDIR script.py [script2.py ...] [--category electronics]
The script's first-line SPDX comment is recorded as the part licence.
"""
import argparse, re, runpy, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import cadquery as cq
import ckcommon as C

def convert(script, outdir, category):
    script = Path(script).resolve(); name = script.stem
    txt = script.read_text()
    lic = (re.search(r"SPDX-License-Identifier:\s*(\S+)", txt) or [None, "unknown"])[1]
    commit = subprocess.run(["git", "-C", str(script.parent), "log", "-1", "--format=%H", "--", str(script)], capture_output=True, text=True).stdout.strip() or "uncommitted"
    man = {"name": name, "category": category, "source": {"url": "local:" + str(script.relative_to(Path(__file__).parent)), "commit": commit},
           "license": lic, "generator": f"convert_cadquery.py (cadquery {cq.__version__})", "ok": False, "ckpart": None}
    t0 = time.time()
    try:
        ns = runpy.run_path(str(script))
        if "assembly" in ns:
            a = ns["assembly"]
        else:
            a = cq.Assembly(name=name); a.add(ns["result"], name=name)
        items = []
        for ch in a.children or [a]:
            shp = ch.obj.val() if isinstance(ch.obj, cq.Workplane) else ch.obj
            rgb = tuple(ch.color.toTuple()[:3]) if ch.color else None
            items.append((ch.name, shp, rgb))
        d = Path(outdir) / category; d.mkdir(parents=True, exist_ok=True)
        step = d / f"{name}.step"
        C.write_step(items, step, name)
        man.update(ok=True, step=str(step.relative_to(outdir)), bbox=C.bbox_of([s for _, s, _ in items]), solids=len(items),
                   colors=[{"name": n, "rgb": c, "volume": round(s.Volume(), 4)} for n, s, c in items])
    except Exception as e:
        man["error"] = f"{type(e).__name__}: {e}"[:300]
    man["seconds"] = round(time.time() - t0, 2)
    C.write_manifest(Path(outdir) / category / f"{name}.manifest.json", man)
    return man

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("scripts", nargs="+"); ap.add_argument("--category", default="cadquery")
    a = ap.parse_args()
    for s in a.scripts:
        m = convert(s, a.out, a.category); print("ok  " if m["ok"] else "FAIL", m["name"], m["seconds"], m.get("error", ""))
