"""Digital (born-PDF) page → page IR (lines, tables, images, rules) in PDF points."""
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from .fonts import clean_text, split_font

_LEADER_CHARS = set(".…·")
_TAB_GAP_EM = 1.2
_BULLET_HEAD = re.compile(r"^([•●▪■◦○◆◇►▸✓✔\-–—+*o]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)]|[IVXivx]{1,4}[.)])$")


def extract_text_page(page, use_invisible: bool = False) -> dict:
    import pymupdf

    pw, ph = page.rect.width, page.rect.height
    flags = (pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES) | pymupdf.TEXT_MEDIABOX_CLIP
    raw = page.get_text("rawdict", flags=flags)

    frags: List[dict] = []
    rotated: List[List[float]] = []
    for block in raw["blocks"]:
        for ln in block.get("lines", []):
            dx, dy = ln["dir"]
            if abs(dy) > 0.05 or dx <= 0:
                if any(c["c"].strip() for s in ln["spans"] for c in s["chars"]):
                    rotated.append(list(ln["bbox"]))
                continue
            frag = _collect_chars(ln, use_invisible)
            if frag:
                frags.append(frag)
    try:
        found_tables = page.find_tables().tables
    except Exception:
        found_tables = []
    cell_boxes = [c for tb in found_tables for c in tb.cells if c]
    frags = _merge_fragments(frags, cell_boxes)
    space_w = _space_widths(frags)
    lines = [l for l in (_finish_line(f, space_w) for f in frags) if l]

    drawings = _safe_drawings(page)
    tables = _extract_tables(found_tables, lines, drawings)
    t_boxes = [t["bbox"] for t in tables]

    hlines, gfx_paths = _classify_drawings(drawings, lines, t_boxes, pw, ph)
    images = _extract_images(page, lines, gfx_paths, rotated)

    return {
        "width": pw,
        "height": ph,
        "lines": lines,
        "tables": tables,
        "images": images,
        "hlines": hlines,
    }


# ── text lines ─────────────────────────────────────────────────────────────

def _style_of(span: dict) -> dict:
    family, bold, italic = split_font(span["font"], span["flags"])
    cf = span.get("char_flags", 0)
    return {
        "font": family,
        "size": round(span["size"] * 2) / 2,
        "bold": bold or bool(cf & 8),
        "italic": italic,
        "underline": bool(cf & 2),
        "strike": bool(cf & 1),
        "color": span.get("color", 0) or 0,
        "super": bool(span["flags"] & 1),
        "mono": bool(span["flags"] & 8),
        "serif": bool(span["flags"] & 4),
    }


def _visible(span: dict) -> bool:
    if span.get("alpha", 255) == 0:
        return False
    cf = span.get("char_flags")
    return cf is None or bool(cf & (16 | 32))


def _collect_chars(ln: dict, use_invisible: bool) -> Optional[dict]:
    chars: List[Tuple[str, float, float, dict]] = []
    baselines, sizes = [], []
    for span in ln["spans"]:
        if not use_invisible and not _visible(span):
            continue
        st = _style_of(span)
        for ch in span["chars"]:
            c = clean_text(ch["c"])
            if not c:
                continue
            x0, _, x1, _ = ch["bbox"]
            chars.append((c, x0, x1, st))
            if c.strip():
                baselines.append(ch["origin"][1])
                sizes.append(st["size"])
    if not baselines:
        return None
    xs = [(x0, x1) for c, x0, x1, _ in chars if c.strip()]
    return {"chars": chars, "baselines": baselines, "sizes": sizes,
            "bbox": [min(a for a, _ in xs), ln["bbox"][1], max(b for _, b in xs), ln["bbox"][3]]}


def _cell_index(bbox, cell_boxes) -> int:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    for i, b in enumerate(cell_boxes):
        if b[0] - 1 <= cx <= b[2] + 1 and b[1] - 1 <= cy <= b[3] + 1:
            return i
    return -1


def _merge_fragments(frags: List[dict], cell_boxes) -> List[dict]:
    """Merge text pieces of one visual line (e.g. numbers typed over blanks)."""
    frags = sorted(frags, key=lambda f: (f["bbox"][1], f["bbox"][0]))
    for f in frags:
        f["cell"] = _cell_index(f["bbox"], cell_boxes)
    out: List[dict] = []
    for f in frags:
        size = max(f["sizes"])
        for g in out:
            if g["cell"] != f["cell"]:
                continue
            a, b = f["bbox"], g["bbox"]
            ov_y = min(a[3], b[3]) - max(a[1], b[1])
            if ov_y < 0.5 * min(a[3] - a[1], b[3] - b[1]):
                continue
            gap = max(a[0], b[0]) - min(a[2], b[2])
            if gap > max(size, 6.0):
                continue
            solid = [(x0, x1) for c, x0, x1, _ in f["chars"] + g["chars"] if c.strip()]

            def covered(x0, x1):
                return any(min(x1, s1) - max(x0, s0) > 0.3 * (x1 - x0) for s0, s1 in solid)

            chars = [ch for ch in f["chars"] + g["chars"] if ch[0].strip() or not covered(ch[1], ch[2])]
            g["chars"] = sorted(chars, key=lambda ch: (ch[1] + ch[2]) / 2)
            g["baselines"] += f["baselines"]
            g["sizes"] += f["sizes"]
            g["bbox"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
            break
        else:
            out.append(f)
    return out


def _space_widths(frags: List[dict]) -> Dict[tuple, float]:
    """Unstretched space advance per (font, size): low percentile of observed spaces."""
    seen: Dict[tuple, List[float]] = {}
    for f in frags:
        for c, x0, x1, st in f["chars"]:
            if c == " " and x1 > x0:
                seen.setdefault((st["font"], st["size"]), []).append(x1 - x0)
    return {k: float(np.percentile(v, 15)) for k, v in seen.items()}


def _natural_widths(items, space_w: Dict[tuple, float]) -> Tuple[float, float]:
    """(natural end x of the line, natural width of its first word).

    Justified PDF text has stretched spaces; Word measures unstretched ones.
    Only the part after the last tab can stretch, so measure from its start.
    """
    first, in_first = 0.0, True
    seg_start, total = None, 0.0
    for it in items:
        if it[0] == "T":
            in_first = False
            seg_start, total = None, 0.0
            if len(it) > 3:  # right-aligned tab: text ends at the stop
                seg_start, total = it[1], 0.0
            continue
        _, c, x0, x1, st = it
        if seg_start is None:
            seg_start = x0
        if c == " ":
            in_first = False
            total += space_w.get((st["font"], st["size"]), 0.25 * st["size"])
        else:
            total += x1 - x0
            if in_first:
                first += x1 - x0
    return (seg_start or 0.0) + total, first


def _finish_line(frag: dict, space_w: Dict[tuple, float]) -> Optional[dict]:
    chars = list(frag["chars"])
    while chars and not chars[0][0].strip():
        chars.pop(0)
    while chars and not chars[-1][0].strip():
        chars.pop()
    if not chars:
        return None
    sizes = frag["sizes"]
    size = float(max(set(sizes), key=sizes.count))
    # Fonts without a usable family (Word symbol subsets…) borrow the line's font.
    fams = [st["font"] for _, _, _, st in chars if st["font"] and st["font"] not in ("Symbol", "Wingdings")]
    main_font = max(set(fams), key=fams.count) if fams else "Times New Roman"
    for i, (c, x0, x1, st) in enumerate(chars):
        if not st["font"] or (st["font"] == "Symbol" and not 0xF000 <= ord(c[0]) <= 0xF0FF):
            chars[i] = (c, x0, x1, {**st, "font": main_font})

    for i, (c, x0, x1, st) in enumerate(chars):
        if st["super"] and st["size"] >= 0.85 * size:
            chars[i] = (c, x0, x1, {**st, "super": False})
    items = _tokenize(chars, size)
    runs = _to_runs(items)
    if not any(r.get("text", "").strip() for r in runs):
        return None
    styles = [st for c, _, _, st in chars if c.strip()]
    nat_end, first_w = _natural_widths(items, space_w)
    sp = [v for (f, z), v in space_w.items() if z == size]
    return {
        "nat_end": nat_end,
        "first_w": first_w,
        "space_w": sp[0] if sp else 0.25 * size,
        "bbox": frag["bbox"],
        "baseline": float(np.median(frag["baselines"])),
        "size": size,
        "runs": runs,
        "mono": sum(s["mono"] for s in styles) > len(styles) / 2,
        "serif": sum(s["serif"] for s in styles) > len(styles) / 2,
    }


def _tokenize(chars, size) -> List[tuple]:
    """Insert tab markers for wide gaps and dot leaders; drop surrounding spaces."""
    items: List[tuple] = []
    prev_x1 = None
    thr = max(_TAB_GAP_EM * size, 6.0)
    head, head_done, checked = "", False, False
    for c, x0, x1, st in chars:
        if not c.strip():
            head_done = head_done or bool(head)
            items.append(("C", c, x0, x1, st))
            continue
        # The gap after a leading bullet/number ("•", "o", "1.", "a)") is a tab.
        bullet_gap = False
        if head_done and not checked:
            checked = True
            bullet_gap = bool(_BULLET_HEAD.match(head)) and x0 - prev_x1 > 0.5 * size
        if prev_x1 is not None and (x0 - prev_x1 > thr or bullet_gap):
            while items and items[-1][0] == "C" and not items[-1][1].strip():
                items.pop()
            items.append(("T", x0, None))
            head_done = checked = True
        if not head_done:
            head += c
        items.append(("C", c, x0, x1, st))
        prev_x1 = x1

    # Dot leaders: "Heading ........ 12" → "Heading<TAB leader=dot>12".
    i = 0
    while i < len(items):
        if items[i][0] == "C" and items[i][1] in _LEADER_CHARS:
            j = i
            while j < len(items) and items[j][0] == "C" and (items[j][1] in _LEADER_CHARS or not items[j][1].strip()):
                j += 1
            n_dots = sum(1 for k in range(i, j) if items[k][1] in _LEADER_CHARS)
            rest = [it for it in items[j:] if it[0] == "C" and it[1].strip()]
            if n_dots >= 5 and rest:
                k = j
                while k < len(items) and items[k][0] == "T":
                    k += 1
                end = max(it[3] for it in rest)
                s = i
                while s > 0 and items[s - 1][0] == "C" and not items[s - 1][1].strip():
                    s -= 1
                items[s:k] = [("T", end, "dot", "right")]
                i = s + 1
                continue
            i = j
        else:
            i += 1
    return items


def _to_runs(items) -> List[dict]:
    runs: List[dict] = []
    for it in items:
        if it[0] == "T":
            runs.append({"tab": True, "x": it[1], "leader": it[2] if len(it) > 2 else None,
                         "align": it[3] if len(it) > 3 else "left"})
            continue
        _, c, x0, x1, st = it
        last = runs[-1] if runs else None
        if last and not last.get("tab") and _same_style(last, st):
            last["text"] += c
            last["x1"] = x1
        else:
            r = {k: v for k, v in st.items() if k not in ("mono", "serif")}
            r.update(text=c, x0=x0, x1=x1)
            runs.append(r)
    # A tab stop sits where the following text starts.
    for i, r in enumerate(runs):
        if r.get("tab") and r["align"] == "left":
            nxt = next((n for n in runs[i + 1:] if not n.get("tab")), None)
            if nxt:
                r["x"] = nxt["x0"]
                r["seg_end"] = max(n["x1"] for n in runs[i + 1:] if not n.get("tab"))
    return runs


def _same_style(run: dict, st: dict) -> bool:
    return all(run[k] == st[k] for k in ("font", "size", "bold", "italic", "underline", "strike", "color", "super"))


# ── tables ─────────────────────────────────────────────────────────────────

def _cluster(vals: List[float], tol: float = 2.0) -> List[float]:
    out: List[float] = []
    for v in sorted(vals):
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def _nearest(vals: List[float], v: float) -> int:
    return int(np.argmin([abs(x - v) for x in vals]))


def _extract_tables(found, lines: List[dict], drawings: List[dict]) -> List[dict]:
    tables = []
    for tb in found:
        boxes = [c for c in tb.cells if c]
        if not boxes or tb.row_count * tb.col_count < 2:
            continue
        xs = _cluster([b[0] for b in boxes] + [b[2] for b in boxes])
        ys = _cluster([b[1] for b in boxes] + [b[3] for b in boxes])
        if len(xs) < 2 or len(ys) < 2:
            continue
        cells = []
        for b in boxes:
            c0, c1 = _nearest(xs, b[0]), _nearest(xs, b[2])
            r0, r1 = _nearest(ys, b[1]), _nearest(ys, b[3])
            if c1 <= c0 or r1 <= r0:
                continue
            cells.append({"r": r0, "c": c0, "rs": r1 - r0, "cs": c1 - c0,
                          "bbox": list(b), "lines": [], "fill": _cell_fill(b, drawings)})
        if not cells:
            continue
        bbox = [xs[0], ys[0], xs[-1], ys[-1]]
        for ln in list(lines):
            cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
            cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
            for cell in cells:
                b = cell["bbox"]
                if b[0] - 1 <= cx <= b[2] + 1 and b[1] - 1 <= cy <= b[3] + 1:
                    cell["lines"].append(ln)
                    lines.remove(ln)
                    break
        tables.append({"bbox": bbox, "xs": xs, "ys": ys, "cells": cells,
                       "border_pt": _border_width(bbox, drawings)})
    return tables


def _rgb_hex(rgb) -> Optional[str]:
    if not rgb:
        return None
    r, g, b = (int(round(v * 255)) for v in rgb[:3])
    return f"{r:02X}{g:02X}{b:02X}"


def _is_white(rgb) -> bool:
    return rgb is not None and all(v >= 0.97 for v in rgb[:3])


def _cell_fill(b, drawings) -> Optional[str]:
    area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
    for d in drawings:
        fill = d.get("fill")
        if not fill or _is_white(fill):
            continue
        r = d["rect"]
        ix = max(0.0, min(r[2], b[2]) - max(r[0], b[0]))
        iy = max(0.0, min(r[3], b[3]) - max(r[1], b[1]))
        if ix * iy >= 0.6 * area and (r[2] - r[0]) * (r[3] - r[1]) <= 1.5 * area:
            return _rgb_hex(fill)
    return None


def _border_width(bbox, drawings) -> float:
    ws = []
    for d in drawings:
        r = d["rect"]
        if r[0] >= bbox[0] - 2 and r[2] <= bbox[2] + 2 and r[1] >= bbox[1] - 2 and r[3] <= bbox[3] + 2:
            if d.get("width"):
                ws.append(d["width"])
            thin = min(r[2] - r[0], r[3] - r[1])
            if d.get("fill") and 0 < thin < 3:
                ws.append(thin)
    return float(np.median(ws)) if ws else 0.5


# ── vector graphics ────────────────────────────────────────────────────────

def _safe_drawings(page) -> List[dict]:
    try:
        return page.get_drawings()
    except Exception:
        return []


def _inside(r, box, pad=1.5) -> bool:
    return r[0] >= box[0] - pad and r[1] >= box[1] - pad and r[2] <= box[2] + pad and r[3] <= box[3] + pad


def _classify_drawings(drawings, lines, t_boxes, pw, ph):
    hlines: List[dict] = []
    paths: List[dict] = []
    for d in drawings:
        r = list(d["rect"])
        if any(_inside(r, tb) for tb in t_boxes):
            continue
        fill, color = d.get("fill"), d.get("color")
        if fill is not None and _is_white(fill) and (color is None or _is_white(color)):
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if w > pw * 0.98 and h > ph * 0.98 and fill is not None and _is_white(fill):
            continue
        if h <= 2.5 and w >= 8:
            if _mark_underline(r, lines):
                continue
            thick = max(h, d.get("width") or 0.5)
            hlines.append({"x1": r[0], "x2": r[2], "y": (r[1] + r[3]) / 2,
                           "w": thick, "color": _rgb_hex(color or fill) or "000000",
                           "rect": r})
            continue
        paths.append(d)

    # Rules that share a row with text are drawn as graphics, not paragraph borders.
    kept = []
    for hl in hlines:
        y = hl["y"]
        crowded = any(
            ln["bbox"][1] - 1 < y < ln["bbox"][3] + 1 and ln["bbox"][0] < hl["x2"] and ln["bbox"][2] > hl["x1"]
            for ln in lines
        )
        if crowded:
            paths.append({"rect": hl["rect"], "items": [("l",)], "fill": None})
        else:
            kept.append(hl)
    return kept, paths


def _mark_underline(r, lines) -> bool:
    y = (r[1] + r[3]) / 2
    for ln in lines:
        if not (ln["baseline"] - 1 <= y <= ln["baseline"] + 0.35 * ln["size"]):
            continue
        hit = False
        for run in ln["runs"]:
            if run.get("tab") or not run["text"].strip():
                continue
            ov = min(run["x1"], r[2]) - max(run["x0"], r[0])
            if ov > 0.5 * (run["x1"] - run["x0"]):
                run["underline"] = True
                hit = True
        if hit:
            return True
    return False


def _union_boxes(rects: List[List[float]], pad: float) -> List[Tuple[List[float], List[int]]]:
    groups = [([r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad], [i]) for i, r in enumerate(rects)]
    merged = True
    while merged:
        merged = False
        out: List[Tuple[List[float], List[int]]] = []
        for box, idx in groups:
            for o in out:
                ob = o[0]
                if box[0] <= ob[2] and box[2] >= ob[0] and box[1] <= ob[3] and box[3] >= ob[1]:
                    ob[0], ob[1] = min(ob[0], box[0]), min(ob[1], box[1])
                    ob[2], ob[3] = max(ob[2], box[2]), max(ob[3], box[3])
                    o[1].extend(idx)
                    merged = True
                    break
            else:
                out.append((list(box), list(idx)))
        groups = out
    return [([b[0] + pad, b[1] + pad, b[2] - pad, b[3] - pad], idx) for b, idx in groups]


def _is_rect_path(d: dict) -> bool:
    ops = [it[0] for it in d.get("items", [])]
    return bool(ops) and all(o in ("re", "qu") for o in ops)


class _Renderer:
    """Renders page crops either as-is or with all text removed (graphics layer)."""

    def __init__(self, page):
        self.page = page
        self._gfx = None

    def gfx_page(self):
        if self._gfx is None:
            import pymupdf
            doc = pymupdf.open()
            doc.insert_pdf(self.page.parent, from_page=self.page.number, to_page=self.page.number)
            p = doc[0]
            p.add_redact_annot(p.rect)
            p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                               graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                               text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            self._gfx = (doc, p)
        return self._gfx[1]

    def png(self, bbox, with_text: bool, dpi: int = 200) -> Optional[bytes]:
        import pymupdf
        clip = pymupdf.Rect(bbox) & self.page.rect
        if clip.is_empty or clip.width < 1 or clip.height < 1:
            return None
        page = self.page if with_text else self.gfx_page()
        try:
            pix = page.get_pixmap(clip=clip, dpi=dpi, alpha=not with_text)
            return pix.tobytes("png")
        except Exception:
            return None


def _extract_images(page, lines, paths, rotated) -> List[dict]:
    pw, ph = page.rect.width, page.rect.height
    rend = _Renderer(page)
    out: List[dict] = []

    for info in _safe_image_info(page):
        b = list(info["bbox"])
        b = [max(0, b[0]), max(0, b[1]), min(pw, b[2]), min(ph, b[3])]
        w, h = b[2] - b[0], b[3] - b[1]
        if w < 6 or h < 6:
            continue
        native = info.get("width", 0) / max(w / 72, 1e-3)
        dpi = int(min(220, max(110, native)))
        png = rend.png(b, with_text=False, dpi=dpi)
        if png:
            out.append({"bbox": b, "png": png, "behind": True})

    # Vector graphics: boxes/shading stay behind real text; drawings with
    # their own labels (charts, diagrams) become pictures including the text.
    rects = [list(d["rect"]) for d in paths]
    for box, idx in _union_boxes(rects, pad=3.0):
        group = [paths[i] for i in idx]
        w, h = box[2] - box[0], box[3] - box[1]
        if w < 3 and h < 3:
            continue
        inner = [ln for ln in lines if _inside(ln["bbox"], box, pad=2)]
        figure = not all(_is_rect_path(d) for d in group) and len(group) >= 4 and inner
        if figure:
            for ln in inner:
                lines.remove(ln)
            png = rend.png(box, with_text=True)
            if png:
                out.append({"bbox": box, "png": png, "behind": False, "figure": True})
        else:
            png = rend.png(box, with_text=False)
            if png:
                out.append({"bbox": box, "png": png, "behind": True, "float": True})

    for b in rotated:
        png = rend.png(b, with_text=True)
        if png:
            out.append({"bbox": b, "png": png, "behind": False, "float": True})
    return out


def _safe_image_info(page) -> List[dict]:
    try:
        return page.get_image_info()
    except Exception:
        return []
