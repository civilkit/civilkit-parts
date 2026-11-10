"""Category and tag scheme for the generated library.

The app takes ONE category per part (lower-case, up to 40 chars) and up to 20 tags (lower-case, up to 40 chars each).
So: `category` is a coarse group (few values, good for a dropdown); `tags` carry everything finer (type, size, material,
standard, domain) so several can be combined. library.json also gets a `categories` list (id, title, count, tags) that
the app ignores today but a UI can use for counts without scanning every part.
"""
import re

# NopSCADlib folder -> (category, kind tags)
GROUPS = {
    "nut": ("fasteners", ["nut"]), "washer": ("fasteners", ["washer"]), "insert": ("fasteners", ["threaded insert", "insert"]),
    "pillar": ("fasteners", ["standoff", "pillar", "spacer"]), "leadnut": ("motion", ["leadscrew", "nut"]),
    "ball_bearing": ("bearings", ["ball bearing", "bearing"]), "linear_bearing": ("bearings", ["linear bearing", "bearing", "bushing"]),
    "pulley": ("motion", ["pulley", "belt", "gt2"]), "shaft_coupling": ("motion", ["coupling", "shaft"]),
    "led": ("electronics", ["led", "indicator", "light"]), "ssr": ("electronics", ["solid state relay", "relay", "mains"]),
    "psu": ("power", ["power supply", "psu", "mains"]), "spool": ("printing", ["filament", "spool", "3d printing"]),
    "tubing": ("tubing & pipe", ["tube", "tubing"]), "ht_pipe": ("tubing & pipe", ["pipe", "ht pipe", "drain", "plumbing"]),
    "swiss_clip": ("hardware", ["clip", "cable"]),
    # ready for the next conversions
    "pcb": ("electronics", ["pcb", "board"]), "display": ("electronics", ["display", "screen"]),
    "microswitch": ("electronics", ["switch", "microswitch"]), "potentiometer": ("electronics", ["potentiometer", "knob control"]),
    "d_connector": ("electronics", ["connector", "d-sub"]), "pin_header": ("electronics", ["connector", "header", "pins"]),
    "dip": ("electronics", ["ic", "dip", "chip"]), "jack": ("electronics", ["connector", "jack", "audio"]), "smd": ("electronics", ["smd", "chip"]),
    "iec": ("power", ["iec", "mains", "connector"]), "mains_socket": ("power", ["socket", "mains"]), "transformer": ("power", ["transformer"]),
    "faston": ("electronics", ["terminal", "faston", "connector"]), "ring_terminal": ("electronics", ["terminal", "connector"]),
    "gear_motor": ("motion", ["motor", "gearbox"]), "servo_motor": ("motion", ["motor", "servo"]), "geared_stepper": ("motion", ["motor", "stepper"]),
    "blower": ("cooling", ["fan", "blower"]), "magnet": ("hardware", ["magnet"]), "ziptie": ("hardware", ["cable tie", "ziptie"]),
}
DOMAIN = {"fasteners": "mechanical", "bearings": "mechanical", "motion": "mechanical", "tubing & pipe": "mechanical", "hardware": "mechanical",
          "printing": "mechanical", "electronics": "electronics", "power": "electronics", "cooling": "electronics"}
MATERIAL = {"nylon": "nylon", "brass": "brass", "rubber": "rubber", "penny": "penny washer", "carbonfiber": "carbon fibre", "hshrnk": "heat shrink",
            "neop": "neoprene", "silicone": "silicone", "alu": "aluminium", "steel": "steel", "plastic": "plastic", "ptfe": "ptfe", "pet": "pet"}
FEATURE = {"hex": "hex", "hammer": "hammer", "sliding": "sliding", "thin": "thin", "nyloc": "nyloc", "idler": "idler", "toothed": "toothed",
           "plain": "plain", "flange": "flanged", "cap": "cap", "pipe": "pipe", "rigid": "rigid", "square": "square", "wing": "wing", "dome": "dome"}


def classify(pid: str, folder: str):
    """-> (category, tags) for part id `pid` from NopSCADlib folder `folder` (underscored)."""
    cat, kind = GROUPS.get(folder, ("other", [folder.replace("_", " ")]))
    tags = list(kind)
    if cat in DOMAIN: tags.append(DOMAIN[cat])
    low = pid.lower()
    for m in re.findall(r"(?<![a-z0-9])m(\d+)(?:p(\d))?(?=[a-z_x]|$)", low):   # M3, M2p5 (not 'um' etc.)
        tags.append("m" + m[0] + (("." + m[1]) if m[1] else ""))
    for m in re.findall(r"(?<![a-z0-9])m\d+(?:p\d)?x(\d+)", low): tags.append("length " + m + "mm")   # M3x20 -> length 20mm
    for m in re.findall(r"(?<![0-9])(?<!m)(?<!gt)(\d+(?:p\d)?)x(\d+(?:p\d)?)(?:x(\d+))?", low):          # 20x5 sizes, 8x2 lead screws
        tags.append("x".join(s.replace("p", ".") for s in m if s))
    if folder in ("ball_bearing", "linear_bearing"):
        for m in re.findall(r"(?:bb|lm)(\d{3,4})", low): tags.append(m)           # 608, 6200, LM8
        for m in re.findall(r"lm(\d+)", low): tags.append("lm" + m)
    if folder == "ht_pipe":
        for m in re.findall(r"ht_(\d+)", low): tags.append(m + "mm")
    if re.match(r"led\d", low):
        for m in re.findall(r"led(\d+)", low): tags.append(m + "mm")
    if folder == "pulley" or "gt2" in low: tags += [t for t in ("gt2",) if t not in tags]
    for k, v in MATERIAL.items():
        if k in low: tags.append(v)
    for k, v in FEATURE.items():
        if re.search(rf"(?<![a-z]){k}", low): tags.append(v)
    out, seen = [], set()
    for t in tags:
        t = t.lower()[:40]
        if t not in seen: seen.add(t); out.append(t)
    return cat, out[:20]


def summarise(parts):
    """The `categories` block: [{id, title, count, tags:[top tags]}] sorted by size."""
    from collections import Counter, defaultdict
    cc, tt = Counter(), defaultdict(Counter)
    for p in parts:
        cc[p["category"]] += 1
        tt[p["category"]].update(p["tags"])
    return [{"id": c, "title": c.title() if c.islower() and "&" not in c else c, "count": n,
             "tags": [t for t, _ in tt[c].most_common(8)]} for c, n in cc.most_common()]
