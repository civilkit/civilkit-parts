# civilkit-parts

A library of parametric parts for CivilKit, plus the converters that make it. 204 NopSCADlib vitamins (bearings, nuts, washers, pulleys, LEDs, connectors, modules and more) are converted from OpenSCAD ([NopSCADlib](https://github.com/nophead/NopSCADlib)) into native `.ckpart` feature trees with colour.
The converters are Apache-2.0; the parts keep their source licence (GPL-3.0-or-later for NopSCADlib), see `NOTICE.md`.
The parts are never bundled in the CivilKit app.

## Use the library
The repository root is a CivilKit library: `library.json` (format `fwlib`), `parts/<category>/<id>.ckpart`, `thumbs/<id>.png` (a picture
for every part), `meta/<id>.json` (source file, commit, licence, kernel check result). In the app: Catalog > Libraries > **+ Add
library** > `github:civilkit/civilkit-parts` (or the raw `library.json` address). Drag a card onto the model, or Insert.

Each part is a real feature history (sketches, revolves, extrudes, booleans) grouped in a feature-tree folder named after the part,
with true arcs for domes and rounds and a colour per body (`appearance`). It is parametric where the OpenSCAD source is (for example
`led_rim_t`, `led_pitch` are variables).

Measured on the 204 parts: all pass the kernel check (valid solids), volumes within 1% of the OpenSCAD mesh (median 0.18%); 202 carry
their script. 133 of the 337 NopSCADlib parts are not converted yet: 113 use 2D `offset()`, 7 `hull()` of 3D shapes, 2 `polyhedron`. Known gaps: LED leads render in the body colour in the thumbnail
(they are unioned into the body); curved surfaces made by `hull()` of circles are approximated; parts needing extra arguments (screws)
are not enumerated yet.

## Import a single OpenSCAD file: script + history
    export CK_KERNEL=<kernel checkout> KIT=<kit checkout>
    .venv/bin/python openscad_to_ckpart.py part.scad -o part.ckpart --script

Writes `part.ck.js`, a CivilKit script (docs/scripting.md in the kit: `variables`, `sketch`, `combine`, `appearance`, grouped under the
part's name), runs it through the kernel (`run_script.mjs`) and writes `part.ckpart`, whose feature history comes from that script and
which keeps it in its `script` field. Open the `.ckpart` in the app and the Script tab shows it; editing and running it rebuilds the part.
`build_library.py ... --scripts` does the same for the whole library (`scripts/<id>.ck.js`).
Measured on the library: 202 of 204 scripts rebuild the same part (volume within 1e-5); two (the 80-tooth pulley and a carbon-fibre
sheet) have scripts longer than the app's 40000-character limit, so they ship with their history only.
Limits: sketches are numbers (the script API cannot link sketch sizes to variables), and OpenSCAD variables are kept as document
variables only where they feed a feature parameter (extrude depth, offsets), not where they only size a sketch.

## Rebuild the library
    export CK_KERNEL=<a kernel checkout with packages/dist built>
    git clone --depth 1 https://github.com/nophead/NopSCADlib.git /scratch/NopSCADlib      # never commit it here
    .venv/bin/python openscad_to_ckpart.py --nop /scratch/NopSCADlib out --category ball_bearing led nut pulley washer --check
    .venv/bin/python build_library.py out .
    node <kit checkout>/tools/library_thumbs.mjs . --png        # pictures; drop --png when cwebp is installed

`openscad_to_ckpart.py` (with `scadlang.py`, an evaluator for a practical OpenSCAD subset) turns the script into a feature tree, not a
mesh. A part the kernel refuses, or whose volume is off by 1% or more, is converted again with straight edges instead of arcs.

## STEP route (older, separate)
### What the STEP route outputs
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
