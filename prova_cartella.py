"""Prova una cartella di DWG/DXF: esporta ogni tavola in PNG e PDF e riporta errori e tempi.

Uso:  .venv\\Scripts\\python.exe prova_cartella.py "C:\\cartella" "C:\\uscita"
"""

import sys
import time
import traceback
from pathlib import Path

from app import export, get_layout, has_content, layout_names, load_drawing


def main(src: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    files = sorted([*src.glob("*.dwg"), *src.glob("*.dxf")])
    if not files:
        print(f"nessun DWG/DXF in {src}")
        return 1

    failed = 0
    for path in files:
        print(f"\n=== {path.name} ({path.stat().st_size // 1024} KB)")
        try:
            t = time.time()
            doc = load_drawing(path)
            print(f"  aperto in {time.time() - t:.1f}s — {len(doc.layers)} layer, {len(doc.blocks)} blocchi")
        except Exception as exc:
            failed += 1
            print("  APERTURA FALLITA:", type(exc).__name__, exc)
            continue

        for name in layout_names(doc):
            if not has_content(doc, name):
                continue
            base = out / f"{path.stem}__{name.replace(' ', '_')}"
            t = time.time()
            try:
                png = export(doc, get_layout(doc, name), base.with_suffix(".png"), fmt="png", dpi=110)
                pdf = export(doc, get_layout(doc, name), base.with_suffix(".pdf"), fmt="pdf")
                print(f"  [{name}] ok in {time.time() - t:.1f}s — "
                      f"png {png.stat().st_size // 1024} KB, pdf {pdf.stat().st_size // 1024} KB")
            except Exception as exc:
                failed += 1
                print(f"  [{name}] ERRORE:", type(exc).__name__, exc)
                traceback.print_exc(limit=3)

    print(f"\n{'OK' if not failed else f'{failed} errori'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
