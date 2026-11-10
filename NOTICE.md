# Licences in this library

The converters in the parent folder are Apache-2.0 (see `LICENSE`).

Every part under `parts/` is generated from a source library and keeps that library's licence. All parts in this
release come from [NopSCADlib](https://github.com/nophead/NopSCADlib) (Chris Palmer, GPL-3.0-or-later; text in
`LICENSE-GPL-3.0.txt`). Parts taken from this library may carry those terms. Each part's `meta/<id>.json` records its
source file, commit, licence and the converter that made it, and the `.ckpart` itself carries `license` and `source`.
The library is data only and is never bundled in the CivilKit app.
