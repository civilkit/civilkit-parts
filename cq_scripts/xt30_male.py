# SPDX-License-Identifier: MIT-0
# XT30-style 2-pole connector (male), approximate public dimensions: 10.0 x 5.0 body, 2.5 mm pin pitch 5.0 mm.
import cadquery as cq
w, h, l = 10.0, 5.0, 10.0
shell = cq.Workplane("XY").rect(w, h).extrude(l).edges("|Z").fillet(1.0)
shell = shell.faces(">Z").workplane().pushPoints([(-2.5, 0), (2.5, 0)]).hole(2.6, 6.0)   # pin cavities
pins = cq.Workplane("XY").workplane(offset=1.0).pushPoints([(-2.5, 0), (2.5, 0)]).circle(1.0).extrude(8.0)
solder = cq.Workplane("XY").workplane(offset=-4).pushPoints([(-2.5, 0), (2.5, 0)]).circle(1.0).extrude(5.0)
assembly = cq.Assembly(name="xt30_male")
assembly.add(shell, name="shell", color=cq.Color(0.9, 0.7, 0.05))
assembly.add(pins.union(solder), name="contacts", color=cq.Color(0.85, 0.65, 0.2))
