#!/usr/bin/env python3
"""OpenSCAD -> CivilKit .ckpart (feature tree) transpiler.

  single file:  openscad_to_ckpart.py part.scad -o part.ckpart [--lib DIR ...]
  NopSCADlib:   openscad_to_ckpart.py --nop LIB OUT --category ball_bearing washer ... [--check]

Output is a native feature tree: sketches (circles, polygons, annuli as nested loops), extrude / revolve /
sphere as `newBody`, moveBody for translate/rotate, scale, mirror (copy + deleteBody), and `combine` for
union / difference / intersection. Numbers that came from accessor functions (`bb_bore(type) = type[1]`) or
top-level script variables become part `variables` and are written as `=expression` in fields the kernel
evaluates (extrude depth, sphere radius, moveBody translate/rotate, revolve angle). Sketch geometry is numeric
(the kernel does not evaluate expressions there).

Unsupported constructs (hull of 3D, minkowski, polyhedron, text, import, surface, offset, twist/scale extrude,
skewed transforms) raise Unsupported; the part then falls back to its STEP file and the manifest says
`fallback: <reason>`.
"""
import time, argparse, json, math, os, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from scadlang import Interp, G, T, ex, union, Unsupported, isnum, UNDEF as UNDEF_

POLY_FN_MAX = 8        # explicit $fn up to this makes a real polygon (hex nut); above, a true circle
EPS = 1e-9
SOURCE_URL = "https://github.com/nophead/NopSCADlib"
LICENSE = "GPL-3.0-or-later"


def num(x):
    v = round(float(x), 9)
    return 0.0 if v == 0 else v

def E(x):
    """Kernel field value: number, or '=expr' when the number is tracked."""
    if isinstance(x, T) and x.e:
        return "=" + x.e
    return num(x)

def nz(x):
    return abs(float(x)) > 1e-12


# ------------------------------------------------------------------ 2D shapes (transforms applied, numeric)
def mm2(M, N):
    a, b, c, d, e, f = M; A, B, C, D, Ee, F = N
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, a * Ee + b * F + e, c * Ee + d * F + f)

def ap(M, x, y):
    return (M[0] * x + M[1] * y + M[4], M[2] * x + M[3] * y + M[5])

def op2(op):
    """2D affine (a,b,c,d,tx,ty) of a 3D-syntax transform op applied to a 2D child."""
    k = op[0]
    if k == "t": return (1, 0, 0, 1, float(op[1][0]), float(op[1][1]))
    if k == "s": return (float(op[1][0]), 0, 0, float(op[1][1]), 0, 0)
    if k == "r":
        if nz(op[1][0]) or nz(op[1][1]): raise Unsupported("3D rotation of 2D geometry")
        a = math.radians(float(op[1][2])); return (math.cos(a), -math.sin(a), math.sin(a), math.cos(a), 0, 0)
    if k == "ra":
        v = op[2]
        if nz(v[0]) or nz(v[1]): raise Unsupported("3D rotation of 2D geometry")
        a = math.radians(float(op[1])); return (math.cos(a), -math.sin(a), math.sin(a), math.cos(a), 0, 0)
    if k == "m":
        nx, ny = float(op[1][0]), float(op[1][1]); n = math.hypot(nx, ny)
        if n < EPS: raise Unsupported("mirror normal not in XY")
        nx, ny = nx / n, ny / n
        return (1 - 2 * nx * nx, -2 * nx * ny, -2 * nx * ny, 1 - 2 * ny * ny, 0, 0)
    if k == "mm":
        m = op[1]
        return (float(m[0][0]), float(m[0][1]), float(m[1][0]), float(m[1][1]), float(m[0][3]), float(m[1][3]))
    raise Unsupported(f"2D transform {k}")

def hull2d(pts):
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in pts))
    if len(pts) < 3: return pts
    cr = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 1e-12: lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cr(up[-2], up[-1], p) <= 1e-12: up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


class Shape2D:
    """tree of ('circle',cx,cy,r) | ('poly',[loops]) | ('u'|'d'|'i',[shapes])"""

def circle_pts(cx, cy, r, n, a0=0.0):
    return [(cx + r * math.cos(a0 + 2 * math.pi * i / n), cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]

def shape2(node, M, notes):
    k = node.k
    if k == "circle":
        r = float(node.r); fn = int(node.fn)
        if r <= 0: return ("u", [])
        sx = math.hypot(M[0], M[2]); sy = math.hypot(M[1], M[3])
        cx, cy = ap(M, 0, 0)
        if 3 <= fn <= POLY_FN_MAX:
            return ("poly", [[ap(M, x, y) for x, y in circle_pts(0, 0, r, fn)]])
        if abs(sx - sy) > 1e-6 * max(sx, sy) or abs(M[0] * M[1] + M[2] * M[3]) > 1e-6 * sx * sy:
            raise Unsupported("non-uniformly scaled circle")
        return ("circle", cx, cy, r * sx)
    if k == "square":
        sx, sy = float(node.size[0]), float(node.size[1])
        x0, y0 = (-sx / 2, -sy / 2) if node.center else (0.0, 0.0)
        return ("poly", [[ap(M, x, y) for x, y in ((x0, y0), (x0 + sx, y0), (x0 + sx, y0 + sy), (x0, y0 + sy))]])
    if k == "poly":
        pts = [(float(p[0]), float(p[1])) for p in node.pts]
        paths = node.paths if node.paths else [list(range(len(pts)))]
        return ("poly", [[ap(M, *pts[int(i)]) for i in path] for path in paths])
    if k == "xf":
        return shape2(node.kid, mm2(M, op2(node.op)), notes)
    if k in ("union", "diff", "inter"):
        return ({"union": "u", "diff": "d", "inter": "i"}[k], [shape2(c, M, notes) for c in node.kids])
    if k == "off":
        return offset2(shape2(node.kid, M, notes), node, M, notes)
    if k == "hull":
        pts = []
        def collect(s):
            if s[0] == "circle":
                n = 72; notes.append("hull of circle approximated as a 72-gon"); pts.extend(circle_pts(s[1], s[2], s[3], n))
            elif s[0] == "poly":
                for l in s[1]: pts.extend(l)
            elif s[0] == "u":
                for c in s[1]: collect(c)
            elif s[0] == "i":
                polys = []
                for c in s[1]:
                    if c[0] == "circle": polys.append(circle_pts(c[1], c[2], c[3], 72)); notes.append("hull of circle approximated as a 72-gon")
                    elif c[0] == "poly" and len(c[1]) == 1 and is_convex(c[1][0]): polys.append(list(c[1][0]))
                    else: raise Unsupported("hull of non-convex intersection")
                cur = polys[0]
                for p in polys[1:]: cur = clip_convex(cur, p)
                pts.extend(cur)
            else: raise Unsupported("hull of difference")
        for c in node.kids: collect(shape2(c, M, notes))
        return ("poly", [hull2d(pts)])
    raise Unsupported(f"2D node {k}")

def to_shapely(s):
    """Shape2D tree -> shapely geometry (several loops of one 'poly' combine even-odd, as OpenSCAD does)"""
    from shapely.geometry import Polygon, Point
    if s[0] == "circle": return Point(s[1], s[2]).buffer(s[3], quad_segs=64)
    if s[0] == "poly":
        g = None
        for l in s[1]:
            if len(l) < 3: continue
            p = Polygon(l).buffer(0)
            g = p if g is None else g.symmetric_difference(p)
        return g if g is not None else Polygon()
    kids = [to_shapely(c) for c in s[1]]
    if not kids: return Polygon()
    g = kids[0]
    for c in kids[1:]: g = g.union(c) if s[0] == "u" else g.difference(c) if s[0] == "d" else g.intersection(c)
    return g

def from_shapely(g):
    from shapely.geometry import Polygon
    polys = [g] if isinstance(g, Polygon) else [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]
    loops = [[list(p.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in p.interiors] for p in polys if not p.is_empty]
    out = [("poly", ls) for ls in loops]
    return out[0] if len(out) == 1 else ("u", out)

def offset2(s, node, M, notes):
    """2D offset(r | delta, chamfer): round joins as fine arcs (the arc detector turns them back into true arcs), mitre or bevel for delta"""
    sc = math.sqrt(abs(M[0] * M[3] - M[1] * M[2]))
    g = to_shapely(s)
    if node.r is not UNDEF_:
        r = float(node.r) * sc
        fn = int(node.fn) if node.fn else 0
        n = max(fn, 3) if fn >= 3 else max(5, min(30, math.ceil(2 * math.pi * abs(r) / 2)))
        g = g.buffer(r, quad_segs=max(8, math.ceil(n / 4)))
    else:
        d = float(node.delta) * sc
        g = g.buffer(d, join_style="bevel" if node.chamfer else "mitre", mitre_limit=1e6)
    notes.append("offset() computed with shapely")
    return from_shapely(g)

def clip_convex(subj, clip):
    """Sutherland-Hodgman: convex subject polygon clipped by a convex polygon"""
    area = sum(clip[i][0] * clip[(i + 1) % len(clip)][1] - clip[(i + 1) % len(clip)][0] * clip[i][1] for i in range(len(clip)))
    sg = 1 if area > 0 else -1
    out = subj
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        side = lambda p: sg * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]))
        inp, out = out, []
        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            sp, sq = side(p), side(q)
            if sp >= 0: out.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq); out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        if not out: break
    return out

def loops_of(s):
    """leaf -> list of loop descriptors ('c',cx,cy,r) | ('p',[pts])"""
    if s[0] == "circle": return [("c", s[1], s[2], s[3])]
    return [("p", l) for l in s[1]]

def leaf_loops(s):
    """every loop of every leaf of a Shape2D tree"""
    if s[0] in ("circle", "poly"): return loops_of(s)
    return [l for c in s[1] for l in leaf_loops(c)]

def bbox_of(l):
    if l[0] == "c": return (l[1] - l[3], l[2] - l[3], l[1] + l[3], l[2] + l[3])
    xs = [p[0] for p in l[1]]; ys = [p[1] for p in l[1]]
    return (min(xs), min(ys), max(xs), max(ys))

def is_convex(pts):
    n = len(pts); sg = 0
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(z) > 1e-12:
            s = 1 if z > 0 else -1
            if sg and s != sg: return False
            sg = s
    return True

def inside(a, b):
    """loop a strictly inside loop b (b a circle or convex polygon)"""
    tol = 1e-6
    if b[0] == "c":
        cx, cy, r = b[1:]
        if a[0] == "c": return math.hypot(a[1] - cx, a[2] - cy) + a[3] < r - tol
        return all(math.hypot(x - cx, y - cy) < r - tol for x, y in a[1])
    pts = b[1]
    if not is_convex(pts): return False
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    sg = 1 if area > 0 else -1
    def margin(x, y):  # min signed distance to the edges (positive = inside)
        m = 1e18
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            m = min(m, sg * ((q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0])) / L)
        return m
    if a[0] == "c": return margin(a[1], a[2]) > a[3] + tol
    return all(margin(x, y) > tol for x, y in a[1])

def disjoint(a, b):
    A, B = bbox_of(a), bbox_of(b)
    return A[2] < B[0] - 1e-6 or B[2] < A[0] - 1e-6 or A[3] < B[1] - 1e-6 or B[3] < A[1] - 1e-6 or \
        (a[0] == "c" and b[0] == "c" and math.hypot(a[1] - b[1], a[2] - b[2]) > a[3] + b[3] + 1e-6)


# ------------------------------------------------------------------ kernel oracle (body liveness)
def circ3(a, b, c):
    """circumcentre/radius of three points, or None when collinear"""
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12: return None
    ux = ((ax*ax + ay*ay) * (by - cy) + (bx*bx + by*by) * (cy - ay) + (cx*cx + cy*cy) * (ay - by)) / d
    uy = ((ax*ax + ay*ay) * (cx - bx) + (bx*bx + by*by) * (ax - cx) + (cx*cx + cy*cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)

ARCS = True

def arc_runs(ps, min_pts=6):
    """open polyline vertex list -> segments ('l', i, j) | ('a', i, j, (cx,cy), r). A run of >= min_pts vertices on one circle
    with equal chord lengths (a mesh-approximated arc) becomes one true arc."""
    segs = []; i = 0; n = len(ps)
    while i < n - 1:
        if not ARCS: segs.append(("l", i, i + 1)); i += 1; continue
        best = None
        if i + 2 < n:
            c = circ3(ps[i], ps[i + 1], ps[i + 2])
            if c:
                (cx, cy), r = c
                ch = math.dist(ps[i], ps[i + 1]); j = i + 2
                while j + 1 < n and abs(math.hypot(ps[j+1][0]-cx, ps[j+1][1]-cy) - r) <= 1e-6 * max(r, 1) \
                        and abs(math.dist(ps[j], ps[j + 1]) - ch) <= 1e-4 * max(ch, 1e-9): j += 1
                # a regular hexagon also lies on a circle: only a fine mesh (<= 12 deg per edge, >= 5 edges, < 340 deg in all) is an arc
                step = 2 * math.asin(min(1.0, ch / (2 * r)))
                if j - i + 1 >= min_pts and r < 1e6 and step <= math.radians(12) and (j - i) * step < math.radians(340): best = (j, (cx, cy), r)
        if best:
            segs.append(("a", i, best[0], best[1], best[2])); i = best[0]
        else:
            segs.append(("l", i, i + 1)); i += 1
    return segs

class Oracle:
    """Persistent node process: given the feature list so far, which named bodies are alive and which features errored."""
    def __init__(self):
        env = dict(os.environ); (env.get("CK_KERNEL") or sys.exit("set CK_KERNEL to a kernel checkout"))
        self.p = subprocess.Popen(["node", str(Path(__file__).parent / "ck_oracle.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        self.queries = 0
    def ask(self, features, variables):
        self.queries += 1
        self.p.stdin.write(json.dumps({"features": features, "variables": variables}) + "\n"); self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        if r.get("fatal"):
            if "empty result" in r["fatal"]: raise Unsupported("empty geometry (the OpenSCAD render is empty too)")
            raise RuntimeError("oracle: " + r["fatal"])
        return r
    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception: self.p.kill()

_ORACLE = []
def get_oracle():
    if not _ORACLE: _ORACLE.append(Oracle())
    return _ORACLE[0]


# ------------------------------------------------------------------ feature tree emitter
class Emit:
    def __init__(self, name, interp):
        self.name = name; self.I = interp; self.f = []; self.n = 0; self.nb = 0; self.used = set()
        self.notes = []; self.counts = {}; self.oracle_calls = 0; self.appearance = {}

    def fid(self):
        self.n += 1; return f"F{self.n}"

    def body(self):
        self.nb += 1; return f"b{self.nb}"

    def add(self, d, label=None):
        d["id"] = self.fid(); d.setdefault("name", label or d["type"])
        self.counts[d["type"]] = self.counts.get(d["type"], 0) + 1
        self.f.append(d)
        return d["id"]

    def e(self, x):
        v = E(x)
        if isinstance(v, str):
            for m in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", v):
                if m not in ("sqrt", "sin", "cos", "tan", "abs"): self.used.add(m)
        return v

    def vec(self, v):
        return [self.e(x) for x in v]

    # sketch of loops -> feature id
    def sketch(self, loops, axis=False):
        pts = [{"id": "O", "x": 0, "y": 0, "fixed": True}]; ents = []; pn = [0]; en = [0]
        def P(x, y):
            pn[0] += 1; pts.append({"id": f"p{pn[0]}", "x": num(x), "y": num(y)}); return f"p{pn[0]}"
        for l in loops:
            if l[0] == "c":
                c = P(l[1], l[2]); en[0] += 1; ents.append({"id": f"e{en[0]}", "type": "circle", "c": c, "r": num(l[3])})
            else:
                ps = []
                for p in l[1]:
                    if not ps or math.hypot(p[0] - ps[-1][0], p[1] - ps[-1][1]) > 1e-9: ps.append(p)
                if len(ps) > 1 and math.hypot(ps[0][0] - ps[-1][0], ps[0][1] - ps[-1][1]) <= 1e-9: ps.pop()
                if len(ps) < 3: continue
                ids = [P(*p) for p in ps]
                cl = ps + [ps[0]]; idc = ids + [ids[0]]
                for sg in arc_runs(cl):
                    en[0] += 1
                    if sg[0] == "l":
                        ents.append({"id": f"e{en[0]}", "type": "line", "p1": idc[sg[1]], "p2": idc[sg[2]]})
                    else:
                        i0, j0 = sg[1], sg[2]
                        # the kernel wants both ends equidistant from the centre to ~1e-9: snap the centre to 1e-6 and put the
                        # end vertex on the circle through the start vertex (a shift of ~1e-7 mm)
                        ccx, ccy = round(sg[3][0], 6) + 0.0, round(sg[3][1], 6) + 0.0
                        rr = math.dist((ccx, ccy), cl[i0]); ex, ey = cl[j0][0] - ccx, cl[j0][1] - ccy; el = math.hypot(ex, ey) or 1.0
                        for pp in pts:
                            if pp["id"] == idc[j0]: pp["x"] = num(ccx + ex / el * rr); pp["y"] = num(ccy + ey / el * rr)
                        cc = P(ccx, ccy)
                        cr = (cl[i0+1][0]-cl[i0][0]) * (cl[i0+2][1]-cl[i0+1][1]) - (cl[i0+1][1]-cl[i0][1]) * (cl[i0+2][0]-cl[i0+1][0])
                        a, b = (idc[i0], idc[j0]) if cr > 0 else (idc[j0], idc[i0])
                        ents.append({"id": f"e{en[0]}", "type": "arc", "c": cc, "p1": a, "p2": b})
        if axis:
            a = P(0, 0); b = P(0, 1); en[0] += 1; ents.append({"id": "ax", "type": "line", "p1": a, "p2": b})
        return self.add({"type": "sketch", "plane": {"kind": "std", "id": "front"}, "points": pts, "entities": ents, "constraints": []}, "profile")

    def extrude(self, loops, depth, center=False):
        sk = self.sketch(loops); b = self.body()
        self.add({"type": "extrude", "op": "newBody", "body": b, "sketch": sk, "end": "mid" if center else "blind", "depth": self.e(depth)}, "extrude")
        return b

    def revolve(self, loops, angle=360.0):
        """profile in XY about the Y axis, then Y -> Z (OpenSCAD rotate_extrude)"""
        for l in loops:
            if bbox_of(l)[0] < -1e-9: raise Unsupported("rotate_extrude profile crosses the axis")
        sk = self.sketch(loops, axis=True); b = self.body()
        self.add({"type": "revolve", "op": "newBody", "body": b, "sketch": sk, "axis": "ax", "end": "blind", "angle": self.e(angle)}, "revolve")
        self.rot([b], "x", 90.0)
        return b

    def rot(self, g, axis, ang, origin=(0, 0, 0)):
        self.add({"type": "moveBody", "bodies": [{"body": b} for b in g], "rotate": {"axis": axis, "origin": list(origin), "angle": self.e(ang)}}, "rotate")

    # ---- booleans on groups of lumps; the kernel is asked which bodies survive
    def query(self):
        self.oracle_calls += 1
        t0 = time.time()
        r = get_oracle().ask(self.f, kernel_expr_vars(self))
        if os.environ.get("CK_TRACE"): print(f"  [oracle {self.name} #{self.oracle_calls}] {len(self.f)} features, last {self.f[-1]['type']}/{self.f[-1].get('op')}: {time.time()-t0:.1f}s", file=sys.stderr, flush=True)
        return r

    def last_error(self, r, fid):
        for e in r["errors"]:
            if e[0] == fid: return e[1].get("code", "?")
        return None

    def union_group(self, lumps):
        lumps = list(dict.fromkeys(lumps))
        if len(lumps) <= 1: return lumps
        fid = self.add({"type": "combine", "op": "union", "target": {"body": lumps[0]}, "tools": [{"body": n} for n in lumps[1:]], "body": lumps[0]}, "union")
        r = self.query(); alive = {b[0] for b in r["bodies"]}
        c = self.last_error(r, fid)
        if c: self.notes.append(f"union: {c}")
        return [n for n in lumps if n in alive]

    def cut_group(self, targets, tools):
        targets = list(targets); tools = list(dict.fromkeys(tools))
        if not targets or not tools: return targets
        out = []
        keep = len(targets) > 1
        for t in targets:
            fid = self.add({"type": "combine", "op": "cut", "target": {"body": t}, "tools": [{"body": n} for n in tools], "body": t, **({"keepTools": True} if keep else {})}, "cut")
            r = self.query(); c = self.last_error(r, fid); alive = {b[0] for b in r["bodies"]}
            if c == "cutNoEffect": self.f.pop(); self.n -= 1; self.counts["combine"] -= 1; out.append(t)
            else:
                if c: self.notes.append(f"cut: {c}")
                if t in alive: out.append(t)
        r = self.query(); alive = {b[0] for b in r["bodies"]}
        left = [n for n in tools if n in alive]
        if left: self.add({"type": "deleteBody", "bodies": [{"body": n} for n in left], "mode": "delete"}, "drop tools")
        return [n for n in out if n in alive]

    def intersect_group(self, a, b):
        if not a or not b: return []
        if len(a) > 1 and len(b) > 1: raise Unsupported("intersection of two multi-lump operands")
        many, one = (a, b[0]) if len(b) == 1 else (b, a[0])          # intersection is symmetric: keep the single lump as the tool
        ids = {t: self.add({"type": "combine", "op": "intersect", "target": {"body": t}, "tools": [{"body": one}], "body": t, "keepTools": True}, "intersect") for t in many}
        r = self.query(); alive = {x[0] for x in r["bodies"]}      # one kernel query for all the lumps (every query replays the whole tree)
        out = []
        for t, fid in ids.items():
            c = self.last_error(r, fid)
            if c:                                                  # refused: no overlap leaves nothing; the feature becomes a delete of that lump
                self.notes.append(f"intersect: {c}")
                d = next(x for x in self.f if x["id"] == fid); d.clear(); d.update({"id": fid, "type": "deleteBody", "bodies": [{"body": t}], "mode": "delete", "name": "drop empty intersection"})
            elif t in alive: out.append(t)
        self.add({"type": "deleteBody", "bodies": [{"body": one}], "mode": "delete"}, "drop tool")
        return out

    # 2D tree -> group of bodies, with a maker that turns loops into a body name
    def shape_body(self, s, maker):
        k = s[0]
        if k in ("circle", "poly"):
            ls = loops_of(s)
            return [maker(ls)] if ls else []
        if k == "u":
            gs = [x for c in s[1] for x in self.shape_body(c, maker)]
            return self.union_group(gs)
        if k == "i":
            gs = [self.shape_body(c, maker) for c in s[1]]
            if not gs or any(not g for g in gs): return []
            cur = gs[0]
            for g in gs[1:]: cur = self.intersect_group(cur, g)
            return cur
        if k == "d":
            kids = s[1]
            if not kids: return []
            base = kids[0]; others = kids[1:]
            if base[0] in ("circle", "poly") and len(loops_of(base)) == 1:
                bl = loops_of(base)[0]; held = []; rest = []
                for o in others:
                    if o[0] in ("circle", "poly") and len(loops_of(o)) == 1:
                        ol = loops_of(o)[0]
                        if inside(ol, bl) and all(disjoint(ol, h) for h in held):
                            held.append(ol); continue
                    rest.append(o)
                g = [maker([bl] + held)]
            else:
                g = self.shape_body(base, maker); rest = others
            cuts = [x for o in rest for x in self.shape_body(o, maker)]
            return self.cut_group(g, cuts)
        raise Unsupported(f"shape {k}")

    # 3D tree -> group of body names (alive lumps)
    def emit(self, n):
        n0 = len(self.f)
        g = self._emit(n)
        col = getattr(n, "col", None)
        if col:
            for d in self.f[n0:]:
                if d.get("op") == "newBody" and d["type"] in ("extrude", "revolve", "sphere"):
                    self.appearance.setdefault(d["id"], {"color": col})
        return g

    def _emit(self, n):
        k = n.k
        if k == "box":
            sx, sy, sz = n.size
            if min(map(float, n.size)) <= 0: return []
            x0, y0 = (-float(sx) / 2, -float(sy) / 2) if n.center else (0.0, 0.0)
            l = ("p", [(x0, y0), (x0 + float(sx), y0), (x0 + float(sx), y0 + float(sy)), (x0, y0 + float(sy))])
            return [self.extrude([l], sz, n.center)]
        if k == "sphere":
            if 3 <= int(n.fn) <= POLY_FN_MAX: raise Unsupported("low-$fn sphere")
            if float(n.r) <= 0: return []
            b = self.body()
            self.add({"type": "sphere", "op": "newBody", "body": b, "center": [0, 0, 0], "radius": self.e(n.r)}, "sphere")
            return [b]
        if k == "cyl":
            h = n.h; r1, r2 = float(n.r1), float(n.r2); fn = int(n.fn)
            if float(h) <= 0 or (r1 <= 0 and r2 <= 0): return []
            if abs(r1 - r2) < 1e-12:
                s = shape2(G("circle", r=n.r1, fn=fn), (1, 0, 0, 1, 0, 0), self.notes)
                return [self.extrude(loops_of(s), h, n.center)]
            if 3 <= fn <= POLY_FN_MAX: raise Unsupported("low-$fn cone")
            hv = float(h)
            prof = [(0.0, 0.0), (r1, 0.0), (r2, hv), (0.0, hv)]
            if r1 <= 0: prof = [(0.0, 0.0), (r2, hv), (0.0, hv)]
            if r2 <= 0: prof = [(0.0, 0.0), (r1, 0.0), (0.0, hv)]
            b = self.revolve([("p", prof)])
            if n.center: self.move([b], [0, 0, self.I.binop("/", self.I.neg(h), 2.0) if isinstance(h, T) else -hv / 2])
            return [b]
        if k == "lext":
            if n.h is UNDEF_: raise Unsupported("linear_extrude height is undefined (OpenSCAD falls back to 100 mm; the part is not meant to be drawn like that)")
            if float(n.h) <= 0: return []   # OpenSCAD makes nothing of a zero (or negative) height; a zero-depth extrude would be a sliver body in the kernel
            if nz(n.twist): raise Unsupported("linear_extrude twist")
            if isinstance(n.scale, list) or abs(float(n.scale) - 1) > 1e-12: raise Unsupported("linear_extrude scale")
            s = shape2(n.kid, (1, 0, 0, 1, 0, 0), self.notes)
            return self.shape_body(s, lambda ls: self.extrude(ls, n.h, n.center))
        if k == "rext":
            s = shape2(n.kid, (1, 0, 0, 1, 0, 0), self.notes)
            if s[0] in ("u", "d", "i") and any(bbox_of(l)[0] < -1e-9 for l in leaf_loops(s)):
                # an operand (a cutter, say) reaches past the axis; OpenSCAD combines the 2D shapes first and only objects if the result crosses it
                g = to_shapely(s)
                if g.is_empty: return []
                if g.bounds[0] < -1e-9: raise Unsupported("rotate_extrude profile crosses the axis")
                self.notes.append("rotate_extrude profile combined in 2D with shapely")
                s = from_shapely(g)
            return self.shape_body(s, lambda ls: self.revolve(ls, n.angle))
        if k == "xf":
            g = self.emit(n.kid)
            return self.apply(g, n.op) if g else []
        if k == "union":
            return self.union_group([x for c in n.kids for x in self.emit(c)])
        if k == "diff":
            gs = [self.emit(c) for c in n.kids]
            if not gs or not gs[0]: return []
            return self.cut_group(gs[0], [x for g in gs[1:] for x in g])
        if k == "inter":
            gs = [self.emit(c) for c in n.kids]
            if not gs or any(not g for g in gs): return []
            cur = gs[0]
            for g in gs[1:]: cur = self.intersect_group(cur, g)
            return cur
        raise Unsupported(f"3D node {k}")

    def move(self, g, v):
        if all(isinstance(x, (int, float)) and not isinstance(x, T) and abs(float(x)) < 1e-12 for x in v): return
        self.add({"type": "moveBody", "bodies": [{"body": b} for b in g], "translate": self.vec(v)}, "translate")

    def apply(self, g, op):
        k = op[0]
        if k == "t": self.move(g, op[1])
        elif k == "r":
            for ax, a in zip("xyz", op[1]):
                if nz(a): self.rot(g, ax, a)
        elif k == "ra":
            v = [float(x) for x in op[2]]
            if nz(op[1]): self.add({"type": "moveBody", "bodies": [{"body": b} for b in g], "rotate": {"axis": v, "origin": [0, 0, 0], "angle": self.e(op[1])}}, "rotate")
        elif k == "s":
            f = [float(x) for x in op[1]]
            if any(abs(x) < 1e-12 for x in f): raise Unsupported("scale by zero")
            neg = [i for i, x in enumerate(f) if x < 0]
            if neg: g = self.mirror(g, [1.0 if i in neg else 0.0 for i in range(3)])
            if any(abs(abs(x) - 1) > 1e-12 for x in f):
                self.add({"type": "scale", "factor": [num(abs(x)) for x in f], "at": [0, 0, 0], "bodies": [{"body": b} for b in g]}, "scale")
        elif k == "m": g = self.mirror(g, [float(x) for x in op[1]])
        elif k == "mm":
            m = op[1]
            lin = [[float(m[i][j]) for j in range(3)] for i in range(3)]
            if all(abs(lin[i][j] - (1.0 if i == j else 0.0)) < 1e-12 for i in range(3) for j in range(3)):
                self.move(g, [m[0][3], m[1][3], m[2][3]])
            else: raise Unsupported("multmatrix with a non-translation linear part")
        else: raise Unsupported(f"transform {k}")
        return g

    def mirror(self, g, nrm):
        nn = [i for i, x in enumerate(nrm) if abs(x) > 1e-12]
        if len(nn) != 1: raise Unsupported("mirror plane not axis aligned")
        plane = ["right", "top", "front"][nn[0]]
        out = []
        for b in g:
            nb = self.body()
            self.add({"type": "moveBody", "bodies": [{"body": b}], "copy": True, "body": nb, "mirror": {"kind": "std", "id": plane}}, "mirror")
            self.add({"type": "deleteBody", "bodies": [{"body": b}], "mode": "delete"}, "delete original")
            out.append(nb)
        return out


def kernel_expr_vars(em):
    out = []
    for n in sorted(em.used):
        if n in em.I.varvals:
            v = em.I.varvals[n]; s = ("%.10f" % v).rstrip("0").rstrip(".")
            out.append({"name": n, "expr": s or "0"})
    return out


def transpile(src, libpaths, name, track_main=True):
    """-> (ckpart dict, info dict). Raises Unsupported."""
    I = Interp(libpaths, track_main=track_main)
    nodes, env = I.run_main(src)
    top = union(nodes)
    if top is None: raise Unsupported("no geometry")
    if top.dim != 3: raise Unsupported("top-level 2D geometry")
    em = Emit(name, I)
    g = em.emit(top)
    if not g: raise Unsupported("empty result")
    grp = name.split("__")[-1]          # feature-tree folder (cosmetic `group`, left out of the regen hash)
    for f in em.f: f["group"] = grp
    doc = {"format": "ck-part", "version": 1, "name": name, "features": em.f, "seq": em.n + 1, "rollback": None,
           "material": "steel", "counters": {}, "variables": kernel_expr_vars(em)}
    if em.appearance: doc["appearance"] = em.appearance
    info = {"features": len(em.f), "by_type": em.counts, "variables": {v["name"]: v["expr"] for v in doc["variables"]},
            "warnings": sorted(set(I.warnings + em.notes))[:20], "colors": len(I.colors), "oracle_calls": em.oracle_calls, "bodies": len(g)}
    return doc, info


# ------------------------------------------------------------------ CLI
# constants that sit in a category file but are a piece of a part, not a part (servo faceplate and shaft definitions)
NOT_PARTS = {("servo_motor", "80ST_faceplate"), ("servo_motor", "Shaft_19mm_keyed")}

def nop_parts(lib, cats):
    sys.path.insert(0, str(Path(__file__).parent))
    import convert_openscad as CO
    return [(c, k) for c, k in CO.enumerate_parts(lib) if (not cats or c in cats) and (c, k) not in NOT_PARTS]

def nop_source(lib, cat, const):
    # core.scad is how NopSCADlib is included: the shared utilities and the screw catalogue (parts that take a screw need it)
    inc = ["include <core.scad>", f"include <vitamins/{cat}.scad>"]
    for suf in ("s", "es"):
        if (Path(lib) / "vitamins" / f"{cat}{suf}.scad").exists(): inc.append(f"include <vitamins/{cat}{suf}.scad>"); break
    call = cat
    if (cat == "camera" and (const.endswith("_pcb") or const == "ESP32_module")) or (cat == "display" and const.endswith("_PCB")):   # these constants are circuit boards, not camera or display types
        inc.append("include <vitamins/pcb.scad>"); call = "pcb"
    return "\n".join(inc) + f"\n{call}({const});\n"

def scad_mesh_volume(lib, cat, const):
    """Ground-truth volume: OpenSCAD's own CSG result (OFF mesh, signed tetra sum)."""
    import tempfile, numpy as np
    with tempfile.TemporaryDirectory() as td:
        sf, of = Path(td) / "t.scad", Path(td) / "t.off"
        sf.write_text(nop_source(lib, cat, const))
        subprocess.run([os.environ.get("OPENSCAD", "/opt/homebrew/bin/openscad"), "-o", str(of), str(sf)], capture_output=True, timeout=300,
                       env={**os.environ, "OPENSCADPATH": str(lib)})
        if not of.exists(): return None
        L = of.read_text().split("\n"); h = L[0].split(); n, f = int(h[1]), int(h[2])
        V = np.array([[float(x) for x in l.split()] for l in L[1:1 + n]]); v = 0.0
        for l in L[1 + n:1 + n + f]:
            p = [int(x) for x in l.split()][1:]
            for i in range(1, len(p) - 1): v += float(np.dot(V[p[0]], np.cross(V[p[i]], V[p[i + 1]]))) / 6
        return v

def done_parts(dirs):
    """Names (<category>__<part>) of parts that already passed: a .ckpart exists, the kernel accepted it and its volume is within 1 % of OpenSCAD's."""
    done = set()
    for d in map(Path, dirs):
        for mf in list(d.glob("*/*.manifest.json")) + list(d.glob("meta/*.json")):
            try: m = json.loads(mf.read_text())
            except Exception: continue
            c = m.get("check") or {}
            if not c.get("ok") or c.get("errors") or c.get("validate") is False or abs(c.get("relErrScad") or 0) >= 0.01: continue
            if mf.parent.name == "meta" or (mf.parent / (mf.name.replace(".manifest.json", ".ckpart"))).is_file(): done.add(m["name"])
    return done


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("scad", nargs="?"); ap_.add_argument("-o")
    ap_.add_argument("--lib", nargs="*", default=[])
    ap_.add_argument("--nop", nargs=2, metavar=("LIB", "OUT"))
    ap_.add_argument("--category", nargs="*"); ap_.add_argument("--limit", type=int)
    ap_.add_argument("--step-dir", default="out", help="existing STEP conversions (convert_openscad.py output) used as fallback / volume reference")
    ap_.add_argument("--script", action="store_true", help="single file: also write <out>.ck.js (a CivilKit script) and rebuild the part by running it (needs KIT, a kit checkout)")
    ap_.add_argument("--check", action="store_true", help="run ck_check.mjs on the results (needs CK_KERNEL)")
    ap_.add_argument("--skip-done", nargs="*", default=[], metavar="DIR", help="skip parts that already passed in these folders: a library (meta/*.json) or earlier converter output (<cat>/<part>.manifest.json)")
    a = ap_.parse_args()
    if a.scad:
        src = Path(a.scad).read_text()
        doc, info = transpile(src, [Path(a.scad).parent] + [Path(p) for p in a.lib], Path(a.scad).stem, track_main=True)
        out = Path(a.o or Path(a.scad).with_suffix(".ckpart")); out.write_text(json.dumps(doc))
        if a.script:
            import scriptgen, tempfile
            kit = os.environ.get("KIT") or sys.exit("set KIT to a kit checkout")
            js = out.with_suffix(".ck.js")
            js.write_text(scriptgen.decompile(doc, f"from {Path(a.scad).name}"))
            with tempfile.TemporaryDirectory() as td:
                r = subprocess.run(["node", str(Path(__file__).parent / "run_script.mjs"), "--out", td, str(js.resolve())], capture_output=True, text=True, env={**os.environ, "KIT": kit})
                j = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"ok": False, "errors": [r.stderr[-200:]]}
                if j.get("ok"): out.write_text((Path(td) / (js.name[:-6] + ".ckpart")).read_text()); info["script"] = str(js); info["scriptVolume"] = j["volume"]
                else: info["scriptError"] = j.get("errors")
        print(json.dumps({"out": str(out), **info})); return
    lib, outdir = Path(a.nop[0]), Path(a.nop[1]); outdir.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "-C", str(lib), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    parts = nop_parts(lib, a.category)
    if a.skip_done:
        done = done_parts(a.skip_done)
        print(f"skipping {sum(1 for c, k in parts if f'{c}__{k}' in done)} parts that already passed")
        parts = [(c, k) for c, k in parts if f"{c}__{k}" not in done]
    parts = parts[: a.limit]
    files = []; results = []
    for cat, const in parts:
        t0 = time.time(); d = outdir / cat; d.mkdir(exist_ok=True)
        man = {"name": f"{cat}__{const}", "category": cat, "source": {"url": SOURCE_URL, "commit": commit, "file": f"vitamins/{cat}.scad", "call": f"{cat}({const})"},
               "license": LICENSE, "generator": "openscad_to_ckpart.py", "transpiled": False}
        stepm = Path(a.step_dir) / cat / f"{const}.manifest.json"
        step = Path(a.step_dir) / cat / f"{const}.step"
        if step.exists(): man["step_ref"] = str(step.relative_to(a.step_dir))
        try:
            doc, info = transpile(nop_source(lib, cat, const), [lib], man["name"], track_main=False)
            doc["license"] = LICENSE; doc["source"] = man["source"]
            (d / f"{const}.ckpart").write_text(json.dumps(doc)); man.update(transpiled=True, ckpart=f"{cat}/{const}.ckpart", **info)
            files.append(d / f"{const}.ckpart")
        except Unsupported as e:
            man["fallback"] = f"fallback: {e}"
        except Exception as e:  # interpreter bug / unsupported syntax: also falls back, with the reason
            man["fallback"] = f"fallback: transpiler error {type(e).__name__}: {str(e)[:120]}"
        man["seconds"] = round(time.time() - t0, 2)
        (d / f"{const}.manifest.json").write_text(json.dumps(man, indent=1))
        results.append(man)
    tr = sum(1 for m in results if m["transpiled"])
    print(f"transpiled {tr}/{len(results)}, fallback {len(results) - tr}")
    for m in results:
        if not m["transpiled"]: print("  ", m["name"], m["fallback"])
    def run_check(ms):
        env = dict(os.environ)
        (env.get("CK_KERNEL") or sys.exit("set CK_KERNEL to a kernel checkout"))
        fl = [outdir / m["ckpart"] for m in ms]
        r = subprocess.run(["node", str(Path(__file__).parent / "ck_check.mjs"), "--step-dir", str(Path(a.step_dir).resolve()), *[str(f.resolve()) for f in fl]], capture_output=True, text=True, env=env)
        chk = {}
        for line in r.stdout.splitlines():
            try: j = json.loads(line); chk[j["file"]] = j
            except Exception: pass
        for m in ms:
            j = chk.get(Path(m["ckpart"]).name)
            m["check"] = j
            if j and j.get("volume"):
                sv = scad_mesh_volume(lib, m["category"], m["name"].split("__", 1)[1])
                if sv: j["scadVolume"] = sv; j["relErrScad"] = (j["volume"] - sv) / sv
            (outdir / m["category"] / f"{m['name'].split('__', 1)[1]}.manifest.json").write_text(json.dumps(m, indent=1))
    def good(m):
        c = m.get("check")
        return bool(c and c.get("ok") and abs(c.get("relErrScad") or 0) < 0.01)
    if a.check and files:
        run_check([m for m in results if m["transpiled"]])
        # a part the kernel refuses, or whose volume is off, is converted again with true arcs off (straight-edge polylines)
        global ARCS
        retry = [m for m in results if m["transpiled"] and not good(m)]
        ARCS = False
        for m in retry:
            cat, const = m["category"], m["name"].split("__", 1)[1]
            try:
                doc, info = transpile(nop_source(lib, cat, const), [lib], m["name"], track_main=False)
            except Exception: continue
            doc["license"] = LICENSE; doc["source"] = m["source"]
            (outdir / cat / f"{const}.ckpart").write_text(json.dumps(doc)); m.update(info); m["arcs"] = False
        if retry: run_check(retry)
        ARCS = True
        okn = [m for m in results if m["transpiled"] and m.get("check") and m["check"].get("ok")]
        print(f"kernel ok {len(okn)}/{tr}")
        for key, lab in (("relErr", "STEP reference"), ("relErrScad", "OpenSCAD mesh")):
            errs = sorted(abs(m["check"][key]) for m in okn if m["check"].get(key) is not None)
            if errs: print(f"volume rel error vs {lab}: n={len(errs)} median={errs[len(errs)//2]*100:.3f}% mean={sum(errs)/len(errs)*100:.3f}% max={errs[-1]*100:.3f}% <1%: {sum(e < 0.01 for e in errs)}")
        for m in results:
            if m["transpiled"] and not (m.get("check") and m["check"].get("ok")): print("  BAD", m["name"], json.dumps(m.get("check"))[:220])
    (outdir / "index.json").write_text(json.dumps(results, indent=1))

if __name__ == "__main__":
    main()
