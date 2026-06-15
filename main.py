import argparse
import sys
import time
from pathlib import Path


def _has_text(pdf_path: str, sample_pages: int = 3, min_chars: int = 50) -> bool:
    import fitz

    doc = fitz.open(pdf_path)
    total = 0
    for i in range(min(sample_pages, len(doc))):
        total += len(doc[i].get_text().strip())
    return total >= min_chars


def _convert_text_pdf(pdf_path: str, output_path: str):
    import fitz
    from src.text_pdf_engine import TextPDFEngine
    from src.docx_builder import DocxBuilder

    print("[1/3] Opening PDF (text mode)...")
    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"      {total} page(s) found.")

    engine = TextPDFEngine()
    builder = DocxBuilder()

    print("[2/3] Extracting layout and text...")
    for i, page in enumerate(doc):
        print(f"      Page {i + 1}/{total}...", end=" ", flush=True)
        t0 = time.time()
        blocks, page_info = engine.analyze_page(page)
        elapsed = time.time() - t0
        print(f"done ({len(blocks)} blocks, {elapsed:.2f}s)")
        builder.set_page_margins(page_info)
        builder.process_blocks(blocks, None)
        if i < total - 1:
            builder.add_page_break()

    print(f"[3/3] Saving → {output_path}")
    builder.save(output_path)
    print("Done.")


def _convert_scanned_pdf(pdf_path: str, output_path: str, lang: str, dpi: int):
    from src.pdf_processor import pdf_to_images
    from src.ocr_engine import LayoutOCR
    from src.docx_builder import DocxBuilder

    print(f"[1/4] Loading OCR engine (lang={lang})...")
    ocr = LayoutOCR(lang=lang)

    print(f"[2/4] Rendering PDF pages (dpi={dpi})...")
    images = pdf_to_images(pdf_path, dpi=dpi)
    total = len(images)
    print(f"      {total} page(s) found.")

    builder = DocxBuilder()

    print("[3/4] Analyzing layout and extracting text...")
    for i, image in enumerate(images):
        print(f"      Page {i + 1}/{total}...", end=" ", flush=True)
        t0 = time.time()
        blocks = ocr.analyze(image)
        elapsed = time.time() - t0
        print(f"done ({len(blocks)} blocks, {elapsed:.1f}s)")
        builder.process_blocks(blocks, image)
        if i < total - 1:
            builder.add_page_break()

    print(f"[4/4] Saving → {output_path}")
    builder.save(output_path)
    print("Done.")


def convert(pdf_path: str, output_path: str, lang: str, dpi: int):
    if _has_text(pdf_path):
        print("[Auto-detect] Text-based PDF → using direct extraction")
        _convert_text_pdf(pdf_path, output_path)
    else:
        print("[Auto-detect] Scanned PDF → using EasyOCR")
        _convert_scanned_pdf(pdf_path, output_path, lang, dpi)


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to editable Word (.docx)")
    parser.add_argument("input", help="Path to input PDF file")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output .docx path (default: same name as input)",
    )
    parser.add_argument(
        "--lang",
        default="vi",
        help="OCR language for scanned PDFs: vi, en, ch. Default: vi",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI for scanned PDF rendering. Default: 300",
    )
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
