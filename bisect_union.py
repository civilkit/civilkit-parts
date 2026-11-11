#!/usr/bin/env python3
"""Find which tool bodies make a failing multi-tool union fail.

usage: bisect_union.py part.ckpart COMBINE_ID

Cuts the part at the failing `combine`, then runs the union with each tool alone, then with each pair of tools that
failed alone or that pass alone, and prints the smallest failing sets (a repro for the kernel). Needs CK_KERNEL.
"""
import json, os, subprocess, sys, itertools
from pathlib import Path

HERE = Path(__file__).parent


class Oracle:
    def __init__(self):
        self.p = subprocess.Popen(["node", str(HERE / "ck_oracle.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=os.environ)
    def ask(self, doc, feats):
        self.p.stdin.write(json.dumps({"features": feats, "variables": doc.get("variables", [])}) + "\n"); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())


def main():
    path, cid = sys.argv[1], sys.argv[2]
    doc = json.load(open(path)); feats = doc["features"]
    idx = next(i for i, f in enumerate(feats) if f["id"] == cid)
    base = feats[:idx]; comb = feats[idx]
    o = Oracle()
    import atexit; atexit.register(o.p.kill)
    r = o.ask(doc, base)
    print("features before the union:", len(base), "errors:", len(r["errors"]), "bodies:", len(r["bodies"]))
    tools = comb["tools"]

    def fails(subset):
        f = dict(comb); f["tools"] = subset
        r = o.ask(doc, base + [f])
        return [e for e in r["errors"] if e[0] == cid]

    alone = {}
    for t in tools:
        e = fails([t]); alone[t["body"]] = e
        print(f"  tool {t['body']} alone:", "FAIL " + json.dumps(e[0][1].get("params", {}).get("issue")) if e else "ok")
    ok = [t for t in tools if not alone[t["body"]]]
    bad = [t for t in tools if alone[t["body"]]]
    print("fail alone:", [t["body"] for t in bad])
    pairs = []
    for a, b in itertools.combinations(ok, 2):
        if fails([a, b]): pairs.append((a["body"], b["body"]))
    print("pairs of individually fine tools that fail together:", pairs[:20], "..." if len(pairs) > 20 else "")
    if not bad and not pairs:
        print("all tools: ", "FAIL" if fails(tools) else "ok", "(needs three or more together)")


if __name__ == "__main__":
    main()
