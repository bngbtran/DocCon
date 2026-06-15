"""Debug layout của PDF tiếng Việt."""

import sys, fitz

pdf_path = (
    sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\bngbtran\Downloads\Eng_Sample.pdf"
)
doc = fitz.open(pdf_path)
page = doc[0]
pw, ph = page.rect.width, page.rect.height
print(f"Page: {pw:.1f} x {ph:.1f} pt")

data = page.get_text("dict")
print(f"\n=== TEXT BLOCKS ({len([b for b in data['blocks'] if b['type'] == 0])}) ===")
for bi, block in enumerate(data["blocks"]):
    if block["type"] != 0:
        print(f"  [B{bi}] IMAGE block")
        continue
    bbox = block["bbox"]
    cx = (bbox[0] + bbox[2]) / 2
    first_span = block["lines"][0]["spans"][0] if block["lines"] else {}
    text_preview = "".join(s["text"] for ln in block["lines"] for s in ln["spans"])[:50]
    print(
        f"  [B{bi}] y={bbox[1]:.0f}-{bbox[3]:.0f}  x={bbox[0]:.0f}-{bbox[2]:.0f}  cx={cx:.0f}"
        f"  font={first_span.get('font', '?')!r}  size={first_span.get('size', 0):.1f}"
        f"  | {text_preview!r}"
    )

print("\n=== DRAWINGS ===")
drawings = page.get_drawings()
print(f"Total drawings: {len(drawings)}")
for di, d in enumerate(drawings[:20]):
    r = d.get("rect")
    if r:
        w = r[2] - r[0]
        h = r[3] - r[1]
        if h < 3:
            print(
                f"  [D{di}] HLINE y={r[1]:.1f} x={r[0]:.1f}-{r[2]:.1f} w={w:.1f} h={h:.2f}"
            )
