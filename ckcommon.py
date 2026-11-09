"""Shared helpers: mesh -> sewn solid, coloured STEP export, bbox, manifest, colour parsing."""
import json, re, subprocess, time
from pathlib import Path

import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.ShapeFix import ShapeFix_Solid
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

NAMED = {  # OpenSCAD/CSS names NopSCADlib uses
    "black": (0.1, 0.1, 0.1), "white": (1, 1, 1), "silver": (0.75, 0.75, 0.75), "gray": (0.5, 0.5, 0.5),
    "grey": (0.5, 0.5, 0.5), "red": (1, 0, 0), "green": (0, 0.5, 0), "blue": (0, 0, 1), "yellow": (1, 1, 0),
    "orange": (1, 0.65, 0), "gold": (1, 0.84, 0), "brown": (0.65, 0.16, 0.16), "purple": (0.5, 0, 0.5),
    "lime": (0, 1, 0), "cyan": (0, 1, 1), "magenta": (1, 0, 1), "pink": (1, 0.75, 0.8), "tan": (0.82, 0.71, 0.55),
    "darkgray": (0.66, 0.66, 0.66), "dimgray": (0.41, 0.41, 0.41), "lightgray": (0.83, 0.83, 0.83),
    "darkred": (0.55, 0, 0), "darkgreen": (0, 0.39, 0), "navy": (0, 0, 0.5), "ivory": (1, 1, 0.94),
    "beige": (0.96, 0.96, 0.86), "olive": (0.5, 0.5, 0), "teal": (0, 0.5, 0.5), "aqua": (0, 1, 1),
}

def parse_colour(lit):
    """OpenSCAD literal ('"silver"', '[0.2,0.2,0.2]', '"#aabbcc"') -> (r,g,b) 0..1 or None."""
    s = lit.strip()
    if s.startswith('"'):
        n = s.strip('"').lower()
        if n.startswith("#") and len(n) >= 7:
            return tuple(int(n[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return NAMED.get(n)
    nums = re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", s)
    if len(nums) >= 3:
        return tuple(max(0, min(1, float(x))) for x in nums[:3])
    return None

def read_off(path):
    """OFF (triangles/polygons, optional per-face colour) -> (verts, faces). Header may share the OFF line."""
    t = Path(path).read_text().split()
    assert t[0].startswith("OFF")
    nv, nf = int(t[1]), int(t[2])
    i = 4
    v = [tuple(map(float, t[i + 3 * k:i + 3 * k + 3])) for k in range(nv)]
    i += 3 * nv
    f = []
    for _ in range(nf):
        n = int(t[i]); f.append([int(x) for x in t[i + 1:i + 1 + n]]); i += 1 + n
        # a face colour follows only when the file has more tokens per face than the loop consumed; OpenSCAD writes none
    return v, f

def mesh_to_solid(verts, faces, tol=1e-4):
    """Sew a closed triangle mesh into one solid, merging coplanar faces. Raises on failure."""
    sew = BRepBuilderAPI_Sewing(tol)
    pts = [gp_Pnt(*p) for p in verts]
    n = 0
    for f in faces:
        poly = BRepBuilderAPI_MakePolygon()
        for i in f:
            poly.Add(pts[i])
        poly.Close()
        if not poly.IsDone():
            continue
        mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        if mf.IsDone():
            sew.Add(mf.Face()); n += 1
    if n == 0:
        raise RuntimeError("no faces")
    sew.Perform()
    sh = sew.SewedShape()
    ex = TopExp_Explorer(sh, TopAbs_SHELL)
    if not ex.More():
        raise RuntimeError("sewing produced no shell")
    shell = TopoDS.Shell_s(ex.Current())
    ms = BRepBuilderAPI_MakeSolid(shell)
    fx = ShapeFix_Solid(ms.Solid()); fx.Perform()
    solid = fx.Solid()
    uf = ShapeUpgrade_UnifySameDomain(solid, True, True, True)
    uf.Build()
    solid = uf.Shape()
    ex = TopExp_Explorer(solid, TopAbs_SOLID)
    if not ex.More():
        raise RuntimeError("no solid after unify")
    if not BRepCheck_Analyzer(solid).IsValid():
        raise RuntimeError("solid invalid after sew")
    p = GProp_GProps(); BRepGProp.VolumeProperties_s(solid, p)
    if p.Mass() <= 0:
        raise RuntimeError(f"non-positive volume {p.Mass():.4g} (open or inverted mesh)")
    return cq.Shape.cast(solid)

def bbox_of(shapes):
    bbs = [s.BoundingBox() for s in shapes]
    return {"min": [round(min(b.xmin for b in bbs), 4), round(min(b.ymin for b in bbs), 4), round(min(b.zmin for b in bbs), 4)],
            "max": [round(max(b.xmax for b in bbs), 4), round(max(b.ymax for b in bbs), 4), round(max(b.zmax for b in bbs), 4)]}

def write_step(items, path, name="part"):
    """items: [(label, cq.Shape, (r,g,b)|None)] -> coloured STEP (one coloured child per item)."""
    a = cq.Assembly(name=name)
    for label, shp, rgb in items:
        a.add(shp, name=label, color=cq.Color(*rgb) if rgb else None)
    a.export(str(path), "STEP")

def write_manifest(path, d):
    Path(path).write_text(json.dumps(d, indent=1, default=str) + "\n")
