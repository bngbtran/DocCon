import fitz, sys

sys.path.insert(0, "d:/DocCon")
from src.text_pdf_engine import TextPDFEngine

doc = fitz.open(r"C:\Users\bngbtran\Downloads\552.pdf")
engine = TextPDFEngine()
items, info = engine.analyze_page(doc[0])
print(
    f"Page: left_margin={info['left_margin_pt']:.1f}, right_margin={info['right_margin_pt']:.1f}"
)
print(f"Total items: {len(items)}")
for i, item in enumerate(items):
    itype = item.get("item_type", "?")
    if itype == "columns":
        ncols = len(item["cells"])
        parts = []
        for cell in item["cells"]:
            lines = " / ".join(b["block_content"][:25] for b in cell)
            parts.append(f"[{lines}]")
        print(f"  [{i}] COLUMNS ({ncols} cols): {' | '.join(parts)}")
    elif itype == "paragraph":
        label = item.get("block_label", "?")
        txt = item.get("block_content", "")[:60]
        print(f"  [{i}] {label}: {txt!r}")
    elif itype == "hline":
        print(f"  [{i}] HLINE y={item['y']:.1f}")
