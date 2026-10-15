"""Per-page routing: digital text, scanned image, or scanned image with a text layer."""
import time
from typing import Optional

from .fonts import garbage_ratio, is_legacy_vn_font


def classify_page(page) -> str:
    """'text' | 'searchable' (image + invisible OCR layer) | 'scan'."""
    import pymupdf

    visible, invisible, legacy = [], 0, 0
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                n = len(s["text"].strip())
                if not n:
                    continue
                cf = s.get("char_flags")
                if s.get("alpha", 255) == 0 or (cf is not None and not cf & (16 | 32)):
                    invisible += n
                else:
                    visible.append(s["text"])
                    if is_legacy_vn_font(s["font"]):
                        legacy += n

    area = page.rect.get_area() or 1.0
    cover = max((((pymupdf.Rect(i["bbox"]) & page.rect).get_area() / area) for i in page.get_image_info()),
                default=0.0)

    vis_text = "".join(visible)
    n_vis = len(vis_text.strip())
    # Text that cannot be decoded (missing ToUnicode, TCVN3/VNI fonts) still
    # renders correctly, so such pages are read back with OCR.
    broken = n_vis >= 20 and (garbage_ratio(vis_text) >= 0.15 or legacy >= 0.5 * n_vis)
    if n_vis >= 20 and not broken:
        return "text"
    if invisible >= 20 and cover >= 0.5:
        return "searchable"
    if broken:
        return "scan"
    # Little or no text: a page-sized picture is a scan/photo of a page;
    # smaller pictures (diagrams, screenshots) are kept as images.
    return "scan" if cover >= 0.4 else "text"


def _upright(doc, index: int):
    """Return the page without /Rotate, so text reads upright in Word.

    Text coordinates are reported in the unrotated page space; scanned pages
    get their orientation fixed from the image content later on.
    """
    page = doc[index]
    if page.rotation == 0:
        return page, None
    import pymupdf
    tmp = pymupdf.open()
    tmp.insert_pdf(doc, from_page=index, to_page=index)
    tmp[0].set_rotation(0)
    return tmp[0], tmp


def convert(pdf_path: str, output_path: str, lang: str = "vi", dpi: int = 300,
            log: Optional[callable] = print):
    import pymupdf
    from .docx_builder import DocxBuilder
    from .layout import build_page_layout
    from .text_pdf_engine import extract_text_page

    log = log or (lambda *_: None)
    doc = pymupdf.open(pdf_path)
    if doc.needs_pass:
        raise ValueError("PDF được bảo vệ bằng mật khẩu.")
    total = len(doc)
    log(f"Opening PDF — {total} page(s)")

    builder = DocxBuilder()
    for i in range(total):
        t0 = time.time()
        page, tmp = _upright(doc, i)
        kind = classify_page(page)
        if kind == "text":
            ir = extract_text_page(page)
        else:
            from .ocr_engine import extract_scanned_page
            ir = extract_scanned_page(page, lang=lang, dpi=dpi, use_text_layer=(kind == "searchable"))
        lay = build_page_layout(ir)
        builder.add_page(lay, first=(i == 0))
        n = len(ir["lines"]) + sum(len(c["lines"]) for t in ir["tables"] for c in t["cells"])
        log(f"  Page {i + 1}/{total} [{kind}] — {n} lines, {len(ir['tables'])} tables, "
            f"{len(ir['images'])} images ({time.time() - t0:.1f}s)")
        if tmp is not None:
            tmp.close()

    builder.save(output_path)
    log(f"Saved → {output_path}")
