#!/usr/bin/env python3
"""Turn a converter output folder into a CivilKit library folder (library.json + parts/ + thumbs/).

usage: build_library.py <converter out dir> <library dir> [--name NAME]
Copies every checked .ckpart to <library>/parts/<category>/<id>.ckpart, keeps its manifest in <library>/meta/<id>.json
(source, commit, licence, check result) and writes <library>/library.json (format fwlib). Pictures are made afterwards by the
kit's own tool:  node <kit>/tools/library_thumbs.mjs <library dir>   (fills `thumb`, writes thumbs/<id>.webp + hashes.json).
"""
import argparse, hashlib, json, shutil, sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("lib")
    ap.add_argument("--name", default="CivilKit parts")
    ap.add_argument("--homepage", default="https://github.com/civilkit/civilkit-parts")
    a = ap.parse_args()
    src, lib = Path(a.src), Path(a.lib)
    parts, seen = [], {}
    for mf in sorted(src.glob("*/*.manifest.json")):
        m = json.loads(mf.read_text())
        ck = src / m.get("ckpart", "")
        chk = m.get("check") or {}
        if not ck.is_file() or chk.get("errors") or chk.get("validate") is False: continue   # only parts the kernel accepted
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
    manifest = {"format": "fwlib", "version": 1, "name": a.name,
                "description": "Electronic and mechanical vitamins (bearings, nuts, washers, pulleys, LEDs) as parametric feature trees, converted from OpenSCAD (NopSCADlib) with colour. Each part keeps its source licence.",
                "homepage": a.homepage, "licence": "GPL-3.0-or-later", "parts": parts}
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "library.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{len(parts)} parts -> {lib}/library.json")


if __name__ == "__main__":
    sys.exit(main())
