"""In cấu trúc layout (đoạn / cột / bảng / ảnh) mà DocCon dựng cho một trang PDF."""
import sys

import pymupdf

sys.path.insert(0, "d:/DocCon")
from src.layout import build_page_layout
from src.pdf_processor import classify_page
from src.text_pdf_engine import extract_text_page

pdf_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\bngbtran\Downloads\552.pdf"
page_no = int(sys.argv[2]) if len(sys.argv) > 2 else 0
page = pymupdf.open(pdf_path)[page_no]

kind = classify_page(page)
if kind == "text":
    ir = extract_text_page(page)
else:
    from src.ocr_engine import extract_scanned_page
    ir = extract_scanned_page(page, use_text_layer=(kind == "searchable"))
lay = build_page_layout(ir)
print(f"Page type: {kind}  margins: { {k: round(v, 1) for k, v in lay['margins'].items()} }")
print(f"Floating images: {len(lay['floats'])}")


def show(items, indent=""):
    for it in items:
        t = it["type"]
        if t == "para":
            text = " | ".join(
                "".join("→" if r.get("tab") else r["text"] for r in ln["runs"]) for ln in it["lines"]
            )
            print(f"{indent}P y={it['top']:.0f} {it['align']:7s} L={it['left']:.0f} "
                  f"F={it['first']:.0f} R={it['right']:.0f} {text[:70]!r}")
        elif t == "columns":
            print(f"{indent}COLUMNS y={it['top']:.0f} bounds={[round(b) for b in it['bounds']]}")
            for col in it["cols"]:
                show(col, indent + "    ")
                print(indent + "    --")
        else:
            print(f"{indent}{t.upper()} y={it['top']:.0f}-{it['bottom']:.0f}")


show(lay["items"])
