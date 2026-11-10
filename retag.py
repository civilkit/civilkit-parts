#!/usr/bin/env python3
"""Re-apply taxonomy.py to library.json in place (no reconversion): retag.py [library dir]"""
import json, sys
from pathlib import Path
import taxonomy

lib = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
man = json.loads((lib / "library.json").read_text())
for p in man["parts"]:
    folder = Path(p["file"]).parent.name
    p["category"], p["tags"] = taxonomy.classify(p["id"], folder)
man["categories"] = taxonomy.summarise(man["parts"])
(lib / "library.json").write_text(json.dumps(man, indent=1) + "\n")
for c in man["categories"]: print(f'{c["count"]:4} {c["id"]:16} {", ".join(c["tags"])}')
