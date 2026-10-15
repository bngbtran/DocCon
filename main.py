import argparse
import sys
from pathlib import Path


def convert(pdf_path: str, output_path: str, lang: str = "vi", dpi: int = 300):
    from src.pdf_processor import convert as _convert
    _convert(pdf_path, output_path, lang=lang, dpi=dpi)


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
