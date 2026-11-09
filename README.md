# ck-parts

Standalone parts library builder for CivilKit. Converts OpenSCAD libraries (NopSCADlib) and CadQuery scripts
into kernel-importable B-rep parts. Lives outside the kernel and the app repos.

## Important: what the output is
A `.ckpart` is a **feature tree** (sketches, extrudes, ...). The kernel has no feature that embeds an imported
B-rep, and no STL importer, so a converted part cannot be a native `.ckpart`. Output per part is:

- `<cat>/<name>.step` - sewn, coloured STEP (one solid per colour; colour is a STEP style on each solid)
- `<cat>/<name>.manifest.json` - name, category, source URL + commit, licence, generator, bbox, ok/failed, colours (rgb), solids, timing

The kernel reads it with `importStep` (heal/sew on). Colours: `.ckpart` has nowhere to hold them, and the kernel
import drops STEP colours, so they live in the STEP file and the manifest `colors` list. Closing the gap needs a
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
Per part: (1) a CSG pass with `color()` overridden to echo the palette; (2) one OFF render per colour (the override
filters geometry by colour, because OpenSCAD 2021.01 drops colour on export); (3) triangles -> OCC sewing -> solid,
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
