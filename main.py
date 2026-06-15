import argparse
import sys
import time
from pathlib import Path


def convert(pdf_path: str, output_path: str, lang: str = "vi", dpi: int = 300):
    import fitz
    from PIL import Image
    from src.text_pdf_engine import TextPDFEngine
    from src.ocr_engine import LayoutOCR
    from src.docx_builder import DocxBuilder

    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"Opening PDF — {total} page(s)")

    engine = TextPDFEngine()
    builder = DocxBuilder()
    ocr: LayoutOCR | None = None

    for i, page in enumerate(doc):
        t0 = time.time()
        is_text = len(page.get_text().strip()) >= 50

        if is_text:
            blocks, page_info = engine.analyze_page(page)
            builder.set_page_margins(page_info)
            builder.process_blocks(blocks, None)
            mode = "text"
        else:
            if ocr is None:
                print(f"  Loading OCR engine (lang={lang})...")
                ocr = LayoutOCR(lang=lang)
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            blocks = ocr.analyze(img)
            builder.process_blocks(blocks, img)
            mode = "ocr"

        print(f"  Page {i+1}/{total} [{mode}] — {len(blocks)} blocks ({time.time()-t0:.1f}s)")
        if i < total - 1:
            builder.add_page_break()

    builder.save(output_path)
    print(f"Saved → {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to editable Word (.docx)")
    parser.add_argument("input", help="Path to input PDF file")
    parser.add_argument("-o", "--output", default=None,
                        help="Output .docx path (default: same name as input)")
    parser.add_argument("--lang", default="vi",
                        help="OCR language for scanned pages: vi, en, ch. Default: vi")
    parser.add_argument("--dpi", type=int, default=300,
                        help="DPI for scanned page rendering. Default: 300")
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print("Error: input must be a .pdf file", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or str(pdf_path.with_suffix(".docx"))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    convert(str(pdf_path), output_path, lang=args.lang, dpi=args.dpi)


if __name__ == "__main__":
    main()
