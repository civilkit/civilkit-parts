# SPDX-License-Identifier: MIT-0
# 1x4 2.54 mm pin header, public-standard dimensions. Origin: pin 1 centre on the PCB surface (z=0).
import cadquery as cq
N, P = 4, 2.54
body = cq.Workplane("XY").box(N * P, P, 2.5, centered=(False, True, False)).translate((-P / 2, 0, 0))
pins = cq.Workplane("XY")
for i in range(N):
    pins = pins.union(cq.Workplane("XY").box(0.64, 0.64, 11.54, centered=(True, True, False)).translate((i * P, 0, -3.0)))
assembly = cq.Assembly(name="pin_header_1x4")
assembly.add(body, name="housing", color=cq.Color(0.1, 0.1, 0.1))
assembly.add(pins, name="pins", color=cq.Color(1.0, 0.84, 0.0))
