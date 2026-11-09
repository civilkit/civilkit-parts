# ck-parts

Standalone parts library builder for CivilKit. Converts OpenSCAD libraries (NopSCADlib) and CadQuery scripts
into kernel-importable B-rep parts. Lives outside the kernel and the app repos.

## Important: what the output is
A `.ckpart` is a **feature tree** (sketches, extrudes, ...). The kernel has no feature that embeds an imported
B-rep, and no STL importer, so a converted part cannot be a native `.ckpart`. Output per part is:

- `<cat>/<name>.step` - sewn, coloured STEP (one solid per colour; colour is a STEP style on each solid)
- `<cat>/<name>.manifest.json` - name, category, source URL + commit, licence, generator, bbox, ok/failed, colours (rgb), solids, timing

The kernel reads it with `importStep` (heal/sew on). Colours: `.ckpart` has nowhere to hold them, and the kernel
import does not surface STEP colours (not verified per face), so they live in the STEP file and the manifest `colors` list. Closing the gap needs a
kernel `importedBody` feature (STEP payload + colour map); until then `ck_import.mjs` is the bridge.

## Setup
    uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python cadquery numpy
    git clone --depth 1 https://github.com/nophead/NopSCADlib.git /scratch/NopSCADlib   # never commit it here
    brew install openscad    # 2021.01 works; colours need no nightly (see below)

## OpenSCAD / NopSCADlib
    .venv/bin/python convert_openscad.py /scratch/NopSCADlib out --category ball_bearing washer --jobs 6
    .venv/bin/python convert_openscad.py /scratch/NopSCADlib out --list      # enumerate only

Enumeration: `vitamins/<c>.scad` with `module <c>(type, ...)` (no other required args) paired with the rows
`NAME = ["...` in `vitamins/<c>s.scad`. Modules needing extra arguments (screws, ...) are skipped.
Per part: (1) a CSG pass with `color()` overridden to echo the palette; (2) one OFF render per colour (a scratch copy of the
library has `color(` rewritten to a filtering `ckcolor(`, because OpenSCAD 2021.01 drops colour on export and
cannot override the builtin); (3) triangles -> OCC sewing -> solid,
coplanar faces unified; (4) coloured STEP. Curved surfaces stay faceted (mesh source). Failures are logged and skipped.

## CadQuery
    .venv/bin/python convert_cadquery.py out cq_scripts/*.py --category electronics
A script defines `assembly` (cq.Assembly with colours) or `result`. Licence read from its `SPDX-License-Identifier`.
Included: pin header 1x4, XT30-style connector, 6.3x11 electrolytic cap (MIT-0 / CC0, dimensions from public datasheets).

## Using a part in the kernel
    CK_KERNEL=<kernel checkout> node ck_import.mjs --sheet sheet.png --cols 6 out/ball_bearing/BB608.step
In code: `Session.open(emptyPart)`, then `importStep(kernel, stepText, {tag:'main'})`; place it in an assembly with
`insertPart`/`mate` once wrapped in a part, or `importStep` per component.

## Licence rule
Generated parts keep the licence of their source (NopSCADlib: GPL-3.0-or-later; recorded in each manifest). They are
**never bundled in the app** and never committed here; only the converters and our own CadQuery scripts are. Ship
them as a separate downloadable library with the licence text and attribution.

## Measured (sample: 5 categories, 77 NopSCADlib parts + 3 CadQuery)
- 68/77 converted (88%); all 71 STEP files import into the kernel with validate ok and volume > 0.
- Failures: 8 pulleys (sewn solid invalid, tangent/self-touching teeth meshes), 1 nut (empty render).
- Wall time about 4-5 s/part at `--jobs 6`; kernel import 0.1-0.7 s/part.
- Full run: `.venv/bin/python convert_openscad.py /scratch/NopSCADlib out --jobs 8` (337 enumerated parts, est. 25-40 min).

## OpenSCAD -> native .ckpart (feature tree)
`openscad_to_ckpart.py` (+ `scadlang.py`, a parser/evaluator for a practical OpenSCAD subset) turns a script into a real
feature tree instead of a mesh/STEP: `sketch` (circles, polygons, annuli as nested loops) -> `extrude` / `revolve` /
`sphere` as `newBody`, `moveBody` (translate/rotate), `scale`, mirror (copy + `deleteBody`), `combine` (union/cut/intersect).

    .venv/bin/python openscad_to_ckpart.py part.scad -o part.ckpart [--lib DIR]
    .venv/bin/python openscad_to_ckpart.py --nop /scratch/NopSCADlib out_ckpart --category ball_bearing washer nut pulley led --check

- Subset: variables, expressions, builtin math, user modules/functions (children(), `$` vars, default args), if/for/let,
  list comprehensions, include/use; cube/sphere/cylinder (cones, center), circle/square/polygon, 2D hull of polygons,
  translate/rotate/scale/mirror/multmatrix(translation), union/difference/intersection, linear_extrude, rotate_extrude, color.
- Named parameters: numbers returned by accessor functions (`bb_bore(type) = type[1]`) and top-level script variables
  become `variables` and are written as `=expr` in fields the kernel evaluates (extrude depth, sphere radius, moveBody
  translate/rotate, revolve angle). Sketch coordinates are plain numbers (the kernel does not evaluate expressions there).
- Fallback (manifest `fallback: <reason>`, part keeps its STEP): 3D hull, minkowski, polyhedron, text, import, surface,
  offset, twist/scale extrude, skewed/non-axis mirror, low-$fn spheres/cones, scaled circles, crossing-axis rotate_extrude.
- The transpiler asks the kernel (`ck_oracle.mjs`, needs `CK_KERNEL`) which named bodies are alive after each boolean:
  `combine union` leaves disjoint tools as separate bodies and consumes merged ones, so references must follow that.
- `ck_check.mjs` regens each .ckpart, validates, and compares volume to the STEP reference; `--check` also computes the
  OpenSCAD mesh volume as ground truth (the STEP reference is unreliable for multi-colour parts, see manifests).
- Licence: transpiled NopSCADlib parts keep GPL-3.0-or-later in the manifest and in the .ckpart (`license`); never commit them.
