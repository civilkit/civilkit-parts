#!/usr/bin/env python3
"""Turn a converter output folder into a CivilKit library folder (library.json + parts/ + thumbs/).

usage: build_library.py <converter out dir> <library dir> [--name NAME]
Copies every checked .ckpart to <library>/parts/<category>/<id>.ckpart, keeps its manifest in <library>/meta/<id>.json
(source, commit, licence, check result) and writes <library>/library.json (format fwlib). Pictures are made afterwards by the
kit's own tool:  node <kit>/tools/library_thumbs.mjs <library dir>   (fills `thumb`, writes thumbs/<id>.webp + hashes.json).
"""
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("lib")
    ap.add_argument("--name", default="CivilKit parts")
    ap.add_argument("--homepage", default="https://github.com/civilkit/civilkit-parts")
    ap.add_argument("--scripts", action="store_true", help="also write each part as a CivilKit script (library/scripts/) and take the part from running it (needs KIT)")
    a = ap.parse_args()
    src, lib = Path(a.src), Path(a.lib)
    parts, seen = [], {}
    for mf in sorted(src.glob("*/*.manifest.json")):
        m = json.loads(mf.read_text())
        ck = src / m.get("ckpart", "")
        chk = m.get("check") or {}
        if not ck.is_file() or chk.get("errors") or chk.get("validate") is False: continue   # only parts the kernel accepted
        if abs(chk.get("relErrScad") or 0) >= 0.01: continue                                  # and whose volume matches the OpenSCAD mesh
        cat, const = m["category"], m["name"].split("__", 1)[-1]
        pid = const if const not in seen else f"{cat}-{const}"
        seen[pid] = 1
        dst = lib / "parts" / cat / f"{pid}.ckpart"; dst.parent.mkdir(parents=True, exist_ok=True)
        data = ck.read_bytes()
        # the .ckpart carries its own provenance, so it stays attributable when copied out of the library
        doc = json.loads(data)
        src_ = m["source"]
        doc["license"] = m["license"]
        doc["source"] = f'{src_["url"]}/blob/{src_["commit"]}/{src_["file"]}'
        data = json.dumps(doc, separators=(",", ":")).encode()
        dst.write_bytes(data)
        (lib / "meta").mkdir(exist_ok=True)
        (lib / "meta" / f"{pid}.json").write_text(json.dumps(m, indent=1))
        tags = sorted({cat.replace("_", " "), *[w for w in const.replace("_", " ").split() if len(w) > 1]})
        parts.append({"id": pid, "title": const.replace("_", " "), "category": cat.replace("_", " "), "tags": tags,
                      "file": f"parts/{cat}/{pid}.ckpart", "source": doc["source"], "bytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})
    if a.scripts:
        sys.path.insert(0, str(Path(__file__).parent)); import scriptgen
        kit = os.environ.get("KIT") or sys.exit("set KIT to a kit checkout")
        sdir = lib / "scripts"; tmp = lib / ".run"; sdir.mkdir(exist_ok=True); tmp.mkdir(exist_ok=True)
        files = []
        for p in parts:
            doc = json.loads((lib / p["file"]).read_text()); mm = json.loads((lib / "meta" / f'{p["id"]}.json').read_text())
            try: txt = scriptgen.decompile(doc, f'{mm["source"]["call"]} from NopSCADlib {mm["source"]["commit"]} ({mm["license"]}); see ../NOTICE.md')
            except Exception as e: print("no script", p["id"], e); continue
            if len(txt) > 40000: print("script too long for the app (40000 chars), history only:", p["id"]); continue
            f = sdir / f'{p["id"]}.ck.js'; f.write_text(txt); files.append(f)
        r = subprocess.run(["node", str(Path(__file__).parent / "run_script.mjs"), "--out", str(tmp), *[str(f.resolve()) for f in files]], capture_output=True, text=True, env={**os.environ, "KIT": kit})
        res = {}
        for line in r.stdout.splitlines():
            try: j = json.loads(line); res[j["file"]] = j
            except Exception: pass
        n_ok = 0
        for p in parts:
            j = res.get(p["id"]); ref = json.loads((lib / "meta" / f'{p["id"]}.json').read_text()).get("check", {}).get("volume")
            if not (j and j.get("ok") and ref and abs(j["volume"] - ref) / ref < 1e-4):
                (sdir / f'{p["id"]}.ck.js').unlink(missing_ok=True); continue
            doc = json.loads((tmp / f'{p["id"]}.ckpart').read_text()); old = json.loads((lib / p["file"]).read_text())
            doc["license"] = old["license"]; doc["source"] = old["source"]
            data = json.dumps(doc, separators=(",", ":")).encode(); (lib / p["file"]).write_bytes(data)
            p["bytes"] = len(data); p["sha256"] = hashlib.sha256(data).hexdigest(); p["script"] = f'scripts/{p["id"]}.ck.js'; n_ok += 1
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"{n_ok}/{len(parts)} parts carry their script")
    import taxonomy
    for p in parts: p["category"], p["tags"] = taxonomy.classify(p["id"], Path(p["file"]).parent.name)
    manifest = {"format": "fwlib", "version": 1, "name": a.name,
                "description": "Electronic and mechanical vitamins (bearings, nuts, washers, pulleys, LEDs) as parametric feature trees, converted from OpenSCAD (NopSCADlib) with colour. Each part keeps its source licence.",
                "homepage": a.homepage, "licence": "GPL-3.0-or-later", "categories": taxonomy.summarise(parts), "parts": parts}
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "library.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{len(parts)} parts -> {lib}/library.json")


if __name__ == "__main__":
    sys.exit(main())
