#!/usr/bin/env python3
"""Shrink a failing union to a small repro part.

usage: minimize_union.py part.ckpart COMBINE_ID out.ckpart

1. cuts the part at the failing `combine`;
2. drops tools while the union still fails;
3. keeps only the features that the remaining bodies depend on (sketches, planes, variables, moves of those bodies);
4. drops the remaining features one at a time while the union still fails.
Writes the result as a .ckpart and prints how far it shrank. Needs CK_KERNEL.
"""
import json, os, subprocess, sys, atexit
from pathlib import Path

HERE = Path(__file__).parent
p = subprocess.Popen(["node", str(HERE / "ck_oracle.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=os.environ)
atexit.register(p.kill)


def ask(feats, variables):
    p.stdin.write(json.dumps({"features": feats, "variables": variables}) + "\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())


def bodies_in(f):
    out = set()
    for k in ("body", "target"):
        v = f.get(k)
        if isinstance(v, str): out.add(v)
        elif isinstance(v, dict) and "body" in v: out.add(v["body"])
    for k in ("tools", "bodies"):
        for r in f.get(k, []) or []:
            if isinstance(r, dict) and "body" in r: out.add(r["body"])
    return out


def main():
    path, cid, out = sys.argv[1:4]
    doc = json.load(open(path)); feats = doc["features"]; variables = doc.get("variables", [])
    idx = next(i for i, f in enumerate(feats) if f["id"] == cid)
    base, comb = feats[:idx], feats[idx]

    def failing(fs, tools):
        c = dict(comb); c["tools"] = [{"body": b} for b in tools]
        r = ask(fs + [c], variables)
        return any(e[0] == cid and e[1].get("code") == "booleanFailed" for e in r["errors"])

    tools = [t["body"] for t in comb["tools"]]
    assert failing(base, tools), "the union does not fail here"
    for t in list(tools):                       # 2. fewer tools
        if len(tools) > 1 and failing(base, [x for x in tools if x != t]): tools.remove(t)
    need = {comb["target"]["body"], *tools}     # 3. dependency closure over bodies and sketches
    keep = set()
    changed = True
    while changed:
        changed = False
        for f in base:
            if f["id"] in keep: continue
            if f["type"] in ("sketch", "plane", "axis") or bodies_in(f) & need:
                refs = {f.get("sketch")} - {None}
                if f["type"] in ("sketch", "plane", "axis") and not any(f["id"] in (g.get("sketch"), g.get("plane", {}).get("of") if isinstance(g.get("plane"), dict) else None) for g in base if g["id"] in keep or bodies_in(g) & need):
                    continue
                keep.add(f["id"]); need |= bodies_in(f); changed = True
    sub = [f for f in base if f["id"] in keep]
    if not failing(sub, tools): sub = base      # closure lost something: fall back to the whole prefix
    i = 0
    while i < len(sub):                          # 4. drop what is not needed
        trial = sub[:i] + sub[i + 1:]
        try:
            ok = failing(trial, tools)
        except Exception:
            ok = False
        if ok: sub = trial
        else: i += 1
    c = dict(comb); c["tools"] = [{"body": b} for b in tools]
    res = dict(doc); res["features"] = sub + [c]; res["seq"] = len(res["features"]) + 1; res["name"] = "repro"
    res.pop("source", None); res.pop("license", None)
    Path(out).write_text(json.dumps(res, indent=1))
    print(f"{path} {cid}: {len(feats)} features -> {len(res['features'])}; tools {len(comb['tools'])} -> {len(tools)} {tools}")


if __name__ == "__main__":
    main()
