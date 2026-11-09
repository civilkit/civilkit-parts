# SPDX-License-Identifier: CC0-1.0
# Radial electrolytic capacitor 6.3 mm diameter x 11 mm tall, 2.5 mm lead pitch (EIA/JEITA typical).
import cadquery as cq
can = (cq.Workplane("XY").workplane(offset=0.5).circle(3.15).extrude(11.0).faces(">Z").edges().fillet(0.4)
       .faces(">Z").workplane().circle(2.4).cutBlind(-0.3))
sleeve_top = cq.Workplane("XY").workplane(offset=0.5).circle(3.2).extrude(0.4)
leads = cq.Workplane("XY").workplane(offset=-4).pushPoints([(-1.25, 0), (1.25, 0)]).circle(0.25).extrude(4.6)
stripe = cq.Workplane("XY").box(1.4, 0.2, 9.5, centered=(True, False, False)).translate((0, 3.12, 1.0))
assembly = cq.Assembly(name="elec_cap_6p3x11")
assembly.add(can, name="can", color=cq.Color(0.05, 0.05, 0.3))
assembly.add(sleeve_top, name="base", color=cq.Color(0.15, 0.15, 0.15))
assembly.add(stripe, name="polarity", color=cq.Color(0.85, 0.85, 0.85))
assembly.add(leads, name="leads", color=cq.Color(0.75, 0.75, 0.75))
