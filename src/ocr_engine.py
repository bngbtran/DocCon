"""Scanned page (raster) → page IR, same structure as text_pdf_engine.

Pipeline: orientation + deskew → ruling lines / tables → text boxes (EasyOCR
or the PDF's invisible OCR layer) → per-box style (size, bold, italic, colour)
→ lines, table cells, figures (stamps, signatures, photos) in PDF points.
"""
import io
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .fonts import clean_text, garbage_ratio

_LANG_MAP = {
    "vi": ["vi", "en"],
    "en": ["en"],
    "ch": ["ch_sim", "en"],
    "chinese_cht": ["ch_tra", "en"],
    "japan": ["ja", "en"],
    "korean": ["ko", "en"],
    "ar": ["ar"],
    "fr": ["fr", "en"],
    "de": ["de", "en"],
    "es": ["es", "en"],
}

_READERS: Dict[str, object] = {}
_COMMON_SIZES = [8, 9, 10, 10.5, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 48, 60, 72]
_METRIC = {}


def get_reader(lang: str):
    """EasyOCR readers are expensive to build; keep one per language."""
    if lang not in _READERS:
        import os
        import easyocr
        import torch
        torch.set_num_threads(max(1, os.cpu_count() or 1))
        _READERS[lang] = easyocr.Reader(_LANG_MAP.get(lang, ["en"]), gpu=False, verbose=False)
    return _READERS[lang]


def extract_scanned_page(page, lang: str = "vi", dpi: int = 300, use_text_layer: bool = False) -> dict:
    pw, ph = page.rect.width, page.rect.height
    pix = page.get_pixmap(dpi=dpi)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()
    sx, sy = pw / img.shape[1], ph / img.shape[0]

    words_px = _text_layer_boxes(page, img.shape, dpi) if use_text_layer else None
    if words_px is None:
        img = _fix_orientation(img, lang)
        if (img.shape[1] > img.shape[0]) != (pw > ph):  # turned by 90°: page turns too
            pw, ph = ph, pw
            sx, sy = pw / img.shape[1], ph / img.shape[0]
    angle = _estimate_skew(img)
    if abs(angle) > 0.08:
        img, M = _rotate(img, angle)
        if words_px:
            words_px = [_transform_box(w, M) for w in words_px]

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    ink = _binarize(gray)
    # Stamps and signatures (coloured ink) must not produce rules or dashes.
    sat = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)[:, :, 1]
    dark = ink & ~cv2.dilate(((sat > 70) * 255).astype(np.uint8), np.ones((5, 5), np.uint8))
    h_mask, v_mask = _rule_masks(dark)
    rules = h_mask | v_mask
    tables = _detect_tables(h_mask, v_mask, img.shape)

    if words_px is None:
        boxes = _ocr_boxes(img, lang, dpi, v_mask, rules, tables, ink)
    else:
        boxes = words_px
    photos = _photo_regions(gray, tables)
    boxes = [bx for bx in _filter_boxes(boxes, img, ink) if not _inside_any(bx, photos)]
    if words_px is None:  # an existing text layer is already complete
        boxes += _recover_dashes(dark, boxes, rules)
    _style_boxes(boxes, img, ink & ~cv2.dilate(rules, np.ones((3, 3), np.uint8)), dpi)
    for bx in boxes:
        bx["cell"] = _cell_of(bx, tables)

    hrules = _horizontal_rules(h_mask, tables, boxes, img.shape)
    groups = _boxes_to_lines(boxes)
    images = _figures(img, ink, boxes, rules, tables, photos)
    return _to_points(groups, tables, images, hrules, pw, ph, sx, sy)


# ── geometry helpers ───────────────────────────────────────────────────────

def _rotate(img: np.ndarray, angle: float):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    return out, M


def _transform_box(b: dict, M) -> dict:
    cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
    nx = M[0, 0] * cx + M[0, 1] * cy + M[0, 2]
    ny = M[1, 0] * cx + M[1, 1] * cy + M[1, 2]
    hw, hh = (b["x1"] - b["x0"]) / 2, (b["y1"] - b["y0"]) / 2
    return {**b, "x0": nx - hw, "x1": nx + hw, "y0": ny - hh, "y1": ny + hh}


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Ink mask (uint8 0/255) robust to uneven illumination."""
    bg = cv2.medianBlur(cv2.resize(gray, None, fx=0.25, fy=0.25), 21)
    bg = cv2.resize(bg, (gray.shape[1], gray.shape[0]))
    norm = cv2.divide(gray, np.maximum(bg, 1), scale=255)
    _, ink = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink


def _projection_score(binary_small: np.ndarray, angle: float) -> float:
    h, w = binary_small.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rot = cv2.warpAffine(binary_small, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    prof = rot.sum(axis=1).astype(np.float64)
    return float(np.var(prof))


def _small_ink(img: np.ndarray, width: int = 1000) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    f = width / gray.shape[1]
    small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    _, b = cv2.threshold(small, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _estimate_skew(img: np.ndarray) -> float:
    b = _small_ink(img)
    if b.sum() < 200:
        return 0.0
    best = max(np.arange(-5, 5.01, 0.25), key=lambda a: _projection_score(b, a))
    best = max(np.arange(best - 0.25, best + 0.26, 0.05), key=lambda a: _projection_score(b, a))
    return float(best)


def _fix_orientation(img: np.ndarray, lang: str) -> np.ndarray:
    """Detect pages scanned sideways or upside down."""
    b = _small_ink(img)
    if b.sum() < 500:
        return img
    s0 = max(_projection_score(b, a) for a in (-2, 0, 2))
    s90 = max(_projection_score(np.ascontiguousarray(np.rot90(b)), a) for a in (-2, 0, 2))
    candidates = [1, 3] if s90 > 1.6 * s0 else [0, 2]
    first = np.ascontiguousarray(np.rot90(img, candidates[0]))
    conf0 = _ocr_confidence(first, lang)
    if conf0 >= 0.55:  # readable as is: no need to try the flipped page
        return first
    other = np.ascontiguousarray(np.rot90(img, candidates[1]))
    return other if _ocr_confidence(other, lang) > conf0 * 1.15 else first


def _ocr_confidence(img: np.ndarray, lang: str) -> float:
    """Recognition confidence on a dense central strip (cheap orientation probe)."""
    h, w = img.shape[:2]
    crop = img[int(h * 0.35):int(h * 0.5), int(w * 0.15):int(w * 0.85)]
    f = min(1.0, 900 / max(1, crop.shape[1]))
    crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    try:
        res = get_reader(lang).readtext(crop, detail=1, paragraph=False)
    except Exception:
        return 0.0
    n = sum(len(r[1]) for r in res)
    return float(sum(r[2] * len(r[1]) for r in res) / n) if n >= 10 else 0.0


# ── text boxes ─────────────────────────────────────────────────────────────

def _ocr_boxes(img: np.ndarray, lang: str, dpi: int, v_mask: np.ndarray, rules: np.ndarray,
               tables: List[dict], ink: np.ndarray) -> List[dict]:
    reader = get_reader(lang)
    h, w = img.shape[:2]
    # Detection at ~140 dpi is as accurate as full resolution and much faster;
    # recognition still reads the full-resolution crops.
    canvas = max(1280, int(max(h, w) * 140 / dpi))
    hl, fl = reader.detect(img, canvas_size=canvas, mag_ratio=1.0, width_ths=0.5)
    hl, fl = list(hl[0]), list(fl[0])
    hl = [p for box in hl for p in _split_at_rules(box, v_mask)]
    hl += _empty_cell_boxes(hl, tables, ink & ~rules)

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    gray[cv2.dilate(rules, np.ones((3, 3), np.uint8)) > 0] = 255
    raw = reader.recognize(gray, horizontal_list=hl, free_list=fl, detail=1, paragraph=False,
                           contrast_ths=0.1, adjust_contrast=0.5)
    out = []
    for bbox, text, conf in raw:
        text = clean_text(unicodedata.normalize("NFC", text)).strip()
        if not text:
            continue
        pts = np.array(bbox, dtype=float)
        out.append({"x0": pts[:, 0].min(), "y0": pts[:, 1].min(), "x1": pts[:, 0].max(),
                    "y1": pts[:, 1].max(), "text": text, "conf": float(conf)})
    return out


def _empty_cell_boxes(hl: List[list], tables: List[dict], ink: np.ndarray) -> List[list]:
    """Table cells with ink but no detected text (short numbers are often missed)."""
    extra = []
    for t in tables:
        xs, ys = t["xs"], t["ys"]
        for c in t["cells"]:
            x0, x1 = xs[c["c"]] + 6, xs[c["c"] + c["cs"]] - 6
            y0, y1 = ys[c["r"]] + 6, ys[c["r"] + c["rs"]] - 6
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            if any(x0 <= (b[0] + b[1]) / 2 <= x1 and y0 <= (b[2] + b[3]) / 2 <= y1 for b in hl):
                continue
            m = ink[y0:y1, x0:x1] > 0
            if m.sum() < 40:
                continue
            yy, xx = np.nonzero(m)
            extra.append([x0 + int(xx.min()) - 4, x0 + int(xx.max()) + 5,
                          y0 + int(yy.min()) - 4, y0 + int(yy.max()) + 5])
    return extra


def _split_at_rules(box, v_mask: np.ndarray) -> List[list]:
    """Cut a detected text box where it crosses a vertical table rule."""
    x0, x1, y0, y1 = (int(v) for v in box)
    H, W = v_mask.shape
    y0c, y1c = max(0, y0), min(H, y1)
    if y1c - y0c < 4 or x1 - x0 < 10:
        return [box]
    band = v_mask[y0c:y1c, max(0, x0):min(W, x1)] > 0
    cuts = _positions(band.mean(axis=0), 0.8)
    pieces, start = [], x0
    for c in cuts:
        cx = max(0, x0) + c
        if cx - start > 6:
            pieces.append([start, cx - 3, y0, y1])
        start = cx + 4
    if x1 - start > 6:
        pieces.append([start, x1, y0, y1])
    return pieces or [box]


def _text_layer_boxes(page, shape, dpi) -> Optional[List[dict]]:
    f = dpi / 72.0
    words = page.get_text("words")
    if sum(len(w[4]) for w in words) < 20 or garbage_ratio("".join(w[4] for w in words)) >= 0.15:
        return None
    out = []
    for x0, y0, x1, y1, t, *_ in words:
        t = clean_text(t).strip()
        if t:
            out.append({"x0": x0 * f, "y0": y0 * f, "x1": x1 * f, "y1": y1 * f, "text": t,
                        "conf": 1.0, "layer": True})
    return out


def _filter_boxes(boxes: List[dict], img: np.ndarray, ink: np.ndarray) -> List[dict]:
    if not boxes:
        return []
    hs = np.array([b["y1"] - b["y0"] for b in boxes])
    med_h = float(np.median(hs))
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    out = []
    for b in boxes:
        if b["conf"] < 0.2:
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in (b["x0"], b["y0"], b["x1"], b["y1"]))
        x0, y0 = max(0, x0), max(0, y0)
        m = ink[y0:y1, x0:x1] > 0
        if m.sum() < 8:
            continue
        sat = hsv[y0:y1, x0:x1, 1][m]
        colored = float(np.mean(sat > 80))
        # Text recognised inside stamps / signatures is noise.
        if not b.get("layer") and ((colored > 0.5 and b["conf"] < 0.9) or (colored > 0.25 and b["conf"] < 0.5)):
            continue
        if (y1 - y0) > 2.5 * med_h and b["conf"] < 0.7:
            continue
        out.append(b)
    return out


def _recover_dashes(ink: np.ndarray, boxes: List[dict], rules: np.ndarray) -> List[dict]:
    """EasyOCR tends to drop '-' (list dashes, "Độc lập - Tự do"); restore them."""
    if not boxes:
        return []
    covered = np.zeros_like(ink)
    for b in boxes:
        cv2.rectangle(covered, (int(b["x0"]) - 1, int(b["y0"]) - 1), (int(b["x1"]) + 1, int(b["y1"]) + 1), 255, -1)
    rest = ink & ~covered & ~cv2.dilate(rules, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
    med_h = float(np.median([b["y1"] - b["y0"] for b in boxes]))
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (w >= 1.7 * h and 2 <= h <= 0.22 * med_h and max(6, 0.12 * med_h) <= w <= 1.3 * med_h and area >= 0.6 * w * h):
            continue
        cy = y + h / 2
        row = [b for b in boxes if b["y0"] + 0.3 * (b["y1"] - b["y0"]) <= cy <= b["y1"] - 0.15 * (b["y1"] - b["y0"])]
        near = [b for b in row if -0.2 * med_h < b["x0"] - (x + w) < 1.5 * med_h
                or -0.2 * med_h < x - b["x1"] < 1.5 * med_h]
        if not near:
            continue
        ref = near[0]
        out.append({"x0": float(x), "x1": float(x + w), "y0": ref["y0"], "y1": ref["y1"],
                    "text": "-", "conf": 1.0, "aux": True})
    return out


def _cell_of(b: dict, tables: List[dict]) -> Optional[Tuple[int, int]]:
    cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
    for ti, t in enumerate(tables):
        xs, ys = t["xs"], t["ys"]
        if not (xs[0] <= cx <= xs[-1] and ys[0] <= cy <= ys[-1]):
            continue
        for ci, c in enumerate(t["cells"]):
            if xs[c["c"]] <= cx <= xs[c["c"] + c["cs"]] and ys[c["r"]] <= cy <= ys[c["r"] + c["rs"]]:
                return ti, ci
    return None


# ── per-box typography ─────────────────────────────────────────────────────

def _core_band(mask: np.ndarray, frac: float = 0.5) -> Tuple[int, int]:
    """Rows of the dense band (x-height for lower case, cap height otherwise).

    The threshold follows the typical (75th percentile) row density, so thin
    horizontal bars (tops of F, T, E) cannot dominate the band.
    """
    prof = mask.sum(axis=1).astype(float)
    nz = prof[prof > 0]
    if len(nz) == 0:
        return 0, mask.shape[0]
    on = prof >= frac * np.percentile(nz, 75)
    best, start, gap = (0, 0), None, 0
    for i, v in enumerate(list(on) + [False, False, False]):
        if v:
            if start is None:
                start = i
            gap = 0
            end = i + 1
            if end - start > best[1] - best[0]:
                best = (start, end)
        elif start is not None:
            gap += 1
            if gap > 2:
                start, gap = None, 0
    return best


def _restore_inner_dashes(b: dict, mask: np.ndarray, top: int, core_bottom: int):
    """Put back '-' glyphs that lie inside a recognised box but were not read."""
    if "-" in b["text"] or "–" in b["text"]:
        return
    em = b["size_px"]
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    comps = sorted((stats[i] for i in range(1, n) if stats[i][4] >= 3), key=lambda st: st[0])
    if not comps:
        return
    width = max(1, mask.shape[1])
    text = b["text"]
    for k, (x, y, w, h, area) in enumerate(comps):
        cy = y + h / 2
        if not (w >= 1.8 * h and h <= 0.13 * em and 0.18 * em <= w <= 0.8 * em
                and core_bottom - 0.45 * em <= cy <= core_bottom - 0.1 * em and area >= 0.55 * w * h):
            continue
        if k == 0:
            text = "- " + text.lstrip()
        else:
            pos = int(round(len(text) * (x + w / 2) / width))
            spaces = [i for i, ch in enumerate(text) if ch == " "]
            if not spaces:
                continue
            at = min(spaces, key=lambda i: abs(i - pos))
            text = text[:at] + " -" + text[at:]
        break
    b["text"] = text


def _stroke_width(mask: np.ndarray) -> float:
    area = float(mask.sum())
    if area < 5:
        return 0.0
    er = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
    boundary = area - float(er.sum())
    return 2.0 * area / max(boundary, 1.0)


def _slant(mask: np.ndarray) -> float:
    """Horizontal shear that makes vertical strokes most upright (≈0.2 for italics)."""
    h, w = mask.shape
    if h < 8 or w < 8:
        return 0.0
    m = mask.astype(np.uint8)
    best, best_s = -1.0, 0.0
    scores = {}
    for s in (-0.1, 0.0, 0.1, 0.2, 0.3):
        M = np.float32([[1, s, -s * h / 2], [0, 1, 0]])
        sh = cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        col = sh.sum(axis=0).astype(float)
        sc = float((col ** 2).sum())
        scores[s] = sc
        if sc > best:
            best, best_s = sc, s
    if best_s >= 0.2 and scores[best_s] > 1.12 * scores[0.0]:
        return best_s
    return 0.0


def _style_boxes(boxes: List[dict], img: np.ndarray, ink: np.ndarray, dpi: int):
    if not boxes:
        return
    H, W = ink.shape
    for b in boxes:
        x0, x1 = max(0, int(b["x0"])), min(W, int(np.ceil(b["x1"])))
        pad = int(0.15 * (b["y1"] - b["y0"]))
        y0, y1 = max(0, int(b["y0"]) - pad), min(H, int(np.ceil(b["y1"])) + pad)
        mask = ink[y0:y1, x0:x1] > 0
        if mask.sum() < 5:
            mask = np.ones((max(1, y1 - y0), max(1, x1 - x0)), bool)
        letters = [ch for ch in b["text"] if ch.isalpha()]
        lower = sum(ch.islower() for ch in letters) / max(1, len(letters))
        # Lower case: dense x-height band. Capitals: thin stems carry the band.
        c0, c1 = _core_band(mask, 0.5 if lower >= 0.5 else 0.22)
        core = max(1, c1 - c0)
        ratio = 0.47 if lower >= 0.5 else 0.70
        b["size_px"] = core / ratio
        box_h = b["y1"] - b["y0"]
        if not 0.45 * box_h <= b["size_px"] <= 1.3 * box_h:
            b["size_px"] = box_h / 1.3  # implausible band: fall back to the box height
        b["size_x"] = b["size_px"] * 72.0 / dpi
        b["baseline"] = y0 + c1
        b["stroke"] = _stroke_width(mask) / max(1.0, b["size_px"])
        if not b.get("aux") and not b.get("layer"):
            _restore_inner_dashes(b, mask, y0, c1)
        b["slant"] = _slant(mask[max(0, c0 - core // 2):c1]) if len(b["text"]) >= 3 else 0.0
        b["color"] = _ink_color(img[y0:y1, x0:x1], mask)

    strokes = [b["stroke"] for b in boxes if len(b["text"]) >= 3 and not b.get("aux")]
    med = float(np.median(strokes)) if strokes else 0.0
    for b in boxes:
        b["bold"] = med > 0 and b["stroke"] > 1.25 * med
        b["italic"] = b["slant"] >= 0.2
    # Short words are too noisy on their own: follow a long word on the same line.
    for b in boxes:
        if len(b["text"].strip(".,;:-")) >= 5 or b.get("aux"):
            continue
        mates = [o for o in boxes if o is not b and len(o["text"]) >= 5
                 and abs(o["baseline"] - b["baseline"]) < 0.4 * b["size_px"]]
        if mates:
            nb = min(mates, key=lambda o: min(abs(o["x0"] - b["x1"]), abs(b["x0"] - o["x1"])))
            b["bold"], b["italic"] = nb["bold"], nb["italic"]
        else:
            b["bold"] = med > 0 and b["stroke"] > 1.45 * med
    # Auxiliary glyphs (restored dashes) take the style of their neighbour.
    real = [o for o in boxes if not o.get("aux")]
    for b in boxes:
        if b.get("aux") and real:
            nb = min(real, key=lambda o: abs(o["y0"] - b["y0"]) * 4
                     + min(abs(o["x0"] - b["x1"]), abs(b["x0"] - o["x1"])))
            for k in ("bold", "italic", "color", "size_x", "size_px", "baseline"):
                b[k] = nb[k]


def _ink_color(crop: np.ndarray, mask: np.ndarray) -> int:
    px = crop[mask]
    if len(px) < 5:
        return 0
    dark = px[px.sum(axis=1) < np.percentile(px.sum(axis=1), 40) + 1]
    r, g, b = (int(v) for v in np.median(dark, axis=0))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 45 or mx < 60:
        return 0
    return (r << 16) | (g << 8) | b


# ── font metrics (to reproduce line breaks in Word) ────────────────────────

def _metric_font(serif: bool, bold: bool, mono: bool):
    import pymupdf
    name = "cour" if mono else ("tibo" if bold else "tiro") if serif else ("hebo" if bold else "helv")
    if name not in _METRIC:
        _METRIC[name] = pymupdf.Font(name)
    return _METRIC[name]


def _strip_marks(text: str) -> str:
    base = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in base if not unicodedata.combining(c))


def _text_width(text: str, size: float, serif: bool, bold: bool, mono: bool) -> float:
    return _metric_font(serif, bold, mono).text_length(_strip_marks(text), fontsize=size)


# ── lines ──────────────────────────────────────────────────────────────────

def _snap(size: float) -> float:
    near = min(_COMMON_SIZES, key=lambda s: abs(s - size))
    return float(near) if abs(near - size) <= 0.06 * size else round(size * 2) / 2


def _page_font(boxes: List[dict]) -> Tuple[bool, bool]:
    """(serif, mono) for the page, judged from character widths."""
    ratios = []
    for b in boxes:
        n = len(b["text"])
        if n >= 6 and b.get("size_px"):
            ratios.append(((b["x1"] - b["x0"]) / n) / max(1e-6, b["size_px"]))
    if len(ratios) >= 5:
        med = float(np.median(ratios))
        iqr = float(np.percentile(ratios, 75) - np.percentile(ratios, 25))
        if 0.55 <= med <= 0.68 and iqr < 0.05:
            return False, True
    return True, False


def _boxes_to_lines(boxes: List[dict]) -> List[dict]:
    """Group boxes into text lines; estimate a consistent size per line."""
    if not boxes:
        return []
    rows: List[List[dict]] = []
    for b in sorted(boxes, key=lambda b: b["baseline"]):
        if rows:
            r = rows[-1]
            base = float(np.median([x["baseline"] for x in r]))
            em = max(b["size_px"], max(x["size_px"] for x in r))
            if abs(b["baseline"] - base) < 0.4 * em:
                r.append(b)
                continue
        rows.append([b])
    # Rows are split per table cell: text never flows across a cell border.
    split_rows = []
    for r in rows:
        by_cell: Dict[object, List[dict]] = {}
        for b in r:
            by_cell.setdefault(b.get("cell"), []).append(b)
        split_rows.extend(by_cell.values())
    rows = split_rows

    lines: List[dict] = []
    for r in rows:
        r.sort(key=lambda b: b["x0"])
        cur = [r[0]]
        for b in r[1:]:
            gap = b["x0"] - cur[-1]["x1"]
            hh = max(cur[-1]["y1"] - cur[-1]["y0"], b["y1"] - b["y0"])
            if gap < 1.2 * hh:
                cur.append(b)
            else:
                lines.append({"boxes": cur})
                cur = [b]
        lines.append({"boxes": cur})
    for ln in lines:
        ln["cell"] = ln["boxes"][0].get("cell")
    return lines


def _finish_lines(lines: List[dict], serif: bool, mono: bool, default_font: str, s: float) -> List[dict]:
    """Turn grouped boxes into IR lines (points). `s` = pt per px."""
    # Size from x-height, refined by matching the text width with font metrics.
    for ln in lines:
        bs = ln["boxes"]
        main = [b for b in bs if not b.get("aux")] or bs
        text = " ".join(b["text"] for b in bs)
        width_pt = (bs[-1]["x1"] - bs[0]["x0"]) * s
        unit = _text_width(text, 1.0, serif, all(b["bold"] for b in main), mono)
        sx = float(np.median([b["size_x"] for b in main]))
        sw = width_pt / unit if unit > 0 else sx
        ln["text"] = text
        ln["long"] = len(text) >= 6
        ln["est"] = sw if ln["long"] and 0.6 <= sw / sx <= 1.6 else sx

    # Cluster the estimates; justified lines are stretched, so the lower
    # part of each cluster is the true (unstretched) size.
    longs = sorted((l for l in lines if l["long"]), key=lambda l: l["est"])
    clusters: List[List[dict]] = []
    for ln in longs:
        if clusters and ln["est"] <= clusters[-1][-1]["est"] * 1.06:
            clusters[-1].append(ln)
        else:
            clusters.append([ln])
    reps = []
    for cl in clusters:
        rep = _snap(float(np.percentile([l["est"] for l in cl], 35)))
        reps.append(rep)
        for l in cl:
            l["size"] = rep
    for ln in lines:
        if ln["long"]:
            continue
        near = min(reps, key=lambda r: abs(np.log(r / ln["est"])), default=None)
        ln["size"] = near if near and abs(np.log(near / ln["est"])) < 0.45 else _snap(ln["est"])

    out = []
    for ln in lines:
        size = ln["size"]
        bs = ln["boxes"]
        runs = []
        for i, b in enumerate(bs):
            text = b["text"] + (" " if i < len(bs) - 1 else "")
            run = {"text": text, "font": default_font, "size": size, "bold": b["bold"],
                   "italic": b["italic"], "underline": b.get("underline", False), "strike": False,
                   "color": b["color"], "super": False, "x0": b["x0"] * s, "x1": b["x1"] * s}
            prev = runs[-1] if runs else None
            if prev and all(prev[k] == run[k] for k in ("bold", "italic", "underline", "color")):
                prev["text"] += text
                prev["x1"] = run["x1"]
            else:
                runs.append(run)
        x0 = bs[0]["x0"] * s
        bold = all(b["bold"] for b in bs if not b.get("aux"))
        nat = _text_width(ln["text"], size, serif, bold, mono)
        first_word = ln["text"].split(" ")[0]
        out.append({
            "bbox": [x0, min(b["y0"] for b in bs) * s, bs[-1]["x1"] * s, max(b["y1"] for b in bs) * s],
            "baseline": float(np.median([b["baseline"] for b in bs])) * s,
            "size": size,
            "runs": runs,
            "mono": mono,
            "serif": serif,
            "nat_end": x0 + nat,
            "first_w": _text_width(first_word, size, serif, bold, mono),
            "space_w": _text_width(" ", size, serif, False, mono),
            "cell": ln.get("cell"),
        })
    return out


# ── tables and rules ───────────────────────────────────────────────────────

def _rule_masks(ink: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    H, W = ink.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, W // 40), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, H // 60)))
    h = cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk)
    v = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk)
    # Bridge small breaks in scanned rules.
    h = cv2.dilate(h, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    v = cv2.dilate(v, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    return h, v


def _positions(profile: np.ndarray, thr: float) -> List[int]:
    on = profile > thr
    pos, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            pos.append((i + j - 1) // 2)
            i = j
        else:
            i += 1
    return pos


def _merge_close(vals: List[int], tol: int) -> List[int]:
    out: List[int] = []
    for v in sorted(vals):
        if out and v - out[-1] <= tol:
            out[-1] = (out[-1] + v) // 2
        else:
            out.append(v)
    return out


def _detect_tables(h_mask: np.ndarray, v_mask: np.ndarray, shape) -> List[dict]:
    H, W = shape[:2]
    grid = cv2.dilate(h_mask | v_mask, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(grid, connectivity=8)
    tables = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if w < 0.15 * W or h < 0.03 * H:
            continue
        hs = h_mask[y:y + h, x:x + w]
        vs = v_mask[y:y + h, x:x + w]
        ys = _merge_close(_positions(hs.sum(axis=1) / 255.0, 0.5 * w), 6)
        if len(ys) < 2:
            continue
        min_row = max(10, min(np.diff(ys)) if len(ys) > 1 else h)
        xs = _merge_close(_positions(vs.sum(axis=0) / 255.0, 0.6 * min_row), 6)
        if len(xs) < 2:
            continue
        if xs[0] > 0.05 * w or xs[-1] < 0.95 * w:
            # Open-sided tables: use the rule extent as outer border.
            xs = _merge_close([0] + xs + [w - 1], 6)
        ys = [y + v for v in ys]
        xs = [x + v for v in xs]
        if (len(xs) - 1) * (len(ys) - 1) < 2:
            continue
        cells = _grid_cells(xs, ys, h_mask, v_mask)
        thick = _rule_thickness(h_mask, xs, ys)
        tables.append({"xs": xs, "ys": ys, "cells": cells, "thick_px": thick})
    return tables


def _rule_thickness(h_mask, xs, ys) -> float:
    mid = (xs[0] + xs[1]) // 2
    col = h_mask[max(0, ys[0] - 10):ys[0] + 10, mid] > 0
    return float(max(1, col.sum() - 8))  # minus the dilation bridge


def _grid_cells(xs, ys, h_mask, v_mask) -> List[dict]:
    R, C = len(ys) - 1, len(xs) - 1
    parent = list(range(R * C))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    for r in range(R):
        for c in range(C):
            y0, y1 = ys[r] + 3, ys[r + 1] - 3
            x0, x1 = xs[c] + 3, xs[c + 1] - 3
            if c + 1 < C:
                band = v_mask[y0:y1, max(0, xs[c + 1] - 4):xs[c + 1] + 5].max(axis=1) if y1 > y0 else np.array([255])
                if np.mean(band > 0) < 0.6:
                    union(r * C + c, r * C + c + 1)
            if r + 1 < R:
                band = h_mask[max(0, ys[r + 1] - 4):ys[r + 1] + 5, x0:x1].max(axis=0) if x1 > x0 else np.array([255])
                if np.mean(band > 0) < 0.6:
                    union(r * C + c, (r + 1) * C + c)
    groups: Dict[int, List[Tuple[int, int]]] = {}
    for r in range(R):
        for c in range(C):
            groups.setdefault(find(r * C + c), []).append((r, c))
    cells, used = [], set()
    for members in groups.values():
        r0 = min(m[0] for m in members)
        r1 = max(m[0] for m in members)
        c0 = min(m[1] for m in members)
        c1 = max(m[1] for m in members)
        rect = {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
        if rect & used:
            # Non-rectangular merge: fall back to individual cells.
            for r, c in members:
                if (r, c) not in used:
                    cells.append({"r": r, "c": c, "rs": 1, "cs": 1})
                    used.add((r, c))
            continue
        used |= rect
        cells.append({"r": r0, "c": c0, "rs": r1 - r0 + 1, "cs": c1 - c0 + 1})
    return cells


def _horizontal_rules(h_mask, tables, boxes, shape) -> List[dict]:
    H, W = shape[:2]
    n, _, stats, _ = cv2.connectedComponentsWithStats(h_mask, connectivity=8)
    rules = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if w < 0.06 * W or h > 0.01 * H:
            continue
        if any(t["xs"][0] - 8 <= x and x + w <= t["xs"][-1] + 8 and t["ys"][0] - 8 <= y <= t["ys"][-1] + 8
               for t in tables):
            continue
        yc = y + h / 2
        # Underline of a text box?
        under = [b for b in boxes if b["baseline"] - 2 <= yc <= b["baseline"] + 0.22 * b["size_px"]
                 and min(b["x1"], x + w) - max(b["x0"], x) > 0.5 * (b["x1"] - b["x0"])]
        if under:
            for b in under:
                b["underline"] = True
            continue
        crowded = any(b["baseline"] - 0.75 * b["size_px"] < yc < b["baseline"] + 0.25 * b["size_px"]
                      and b["x0"] < x + w and b["x1"] > x for b in boxes)
        if not crowded:
            rules.append({"x1": x, "x2": x + w, "y": yc, "h": max(1, h - 8)})
    return rules


# ── figures ────────────────────────────────────────────────────────────────

def _photo_regions(gray: np.ndarray, tables: List[dict]) -> List[List[int]]:
    """Photos / screenshots: large, densely inked, textured areas.

    Text inside them stays part of the picture instead of being re-typed.
    """
    H, W = gray.shape
    f = 0.25
    small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    nonbg = (small < 215).astype(np.float32)
    dense = (cv2.blur(nonbg, (25, 25)) > 0.45).astype(np.uint8)
    dense = cv2.morphologyEx(dense, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(dense, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, _ = (int(v / f) for v in stats[i])
        if w < 0.15 * W or h < 0.06 * H:
            continue
        region = gray[y:y + h, x:x + w]
        if float(region.std()) < 30:
            continue  # flat shading (table header fills, coloured boxes)
        if any(t["xs"][0] - 10 <= x and x + w <= t["xs"][-1] + 10 and t["ys"][0] - 10 <= y
               and y + h <= t["ys"][-1] + 10 for t in tables):
            continue
        out.append([x, y, x + w, y + h])
    return out


def _inside_any(b: dict, regions: List[List[int]]) -> bool:
    cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)


def _figures(img, ink, boxes, rules, tables, photos) -> List[dict]:
    H, W = ink.shape
    out = []
    for x0, y0, x1, y1 in photos:
        buf = io.BytesIO()
        Image.fromarray(img[y0:y1, x0:x1]).save(buf, "PNG", optimize=True)
        out.append({"bbox_px": [x0, y0, x1, y1], "png": buf.getvalue(), "behind": True, "float": False})
    text_mask = np.zeros_like(ink)
    for x0, y0, x1, y1 in photos:
        cv2.rectangle(text_mask, (x0, y0), (x1, y1), 255, -1)
    for b in boxes:
        pad = int(0.15 * (b["y1"] - b["y0"]))
        cv2.rectangle(text_mask, (int(b["x0"]) - pad, int(b["y0"]) - pad),
                      (int(b["x1"]) + pad, int(b["y1"]) + pad), 255, -1)
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    colored = ((hsv[:, :, 1] > 70) & (hsv[:, :, 2] < 235)).astype(np.uint8) * 255
    rules_d = cv2.dilate(rules, np.ones((5, 5), np.uint8))
    other = cv2.bitwise_and(ink, cv2.bitwise_not(text_mask))
    other = cv2.bitwise_and(other, cv2.bitwise_not(rules_d))
    fig = cv2.bitwise_or(other, colored)
    fig = cv2.morphologyEx(fig, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    for x0, y0, x1, y1 in photos:
        fig[y0:y1, x0:x1] = 0
    text_h = float(np.median([b["y1"] - b["y0"] for b in boxes])) if boxes else 0.02 * H
    k = max(9, W // 80)
    blob = cv2.dilate(fig, np.ones((k, k), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(blob, connectivity=8)
    min_side = 0.025 * W
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        x, y = x + k // 2, y + k // 2
        w, h = max(1, w - k), max(1, h - k)
        if w < min_side and h < min_side:
            continue
        # Small uncoloured blobs right next to text are leftover glyphs, not pictures.
        blob_ink = fig[y:y + h, x:x + w] > 0
        tinted = (colored[y:y + h, x:x + w] > 0)[blob_ink].mean() > 0.3 if blob_ink.any() else False
        if not tinted and h < 2.5 * text_h and any(
                min(y + h, b["y1"]) - max(y, b["y0"]) > 0.3 * min(h, b["y1"] - b["y0"])
                and (abs(x - b["x1"]) < text_h or abs(b["x0"] - (x + w)) < text_h)
                for b in boxes):
            continue
        pixels = int((fig[y:y + h, x:x + w] > 0).sum())
        if pixels < 0.002 * w * h * 10 or pixels < 150:
            continue
        crop = img[y:y + h, x:x + w]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        photo = float(np.mean(gray < 200)) > 0.35
        if photo:
            rgba = np.dstack([crop, np.full(gray.shape, 255, np.uint8)])
        else:
            alpha = np.clip((245 - gray.astype(np.int32)) * 4, 0, 255).astype(np.uint8)
            sat = hsv[y:y + h, x:x + w, 1]
            in_text = text_mask[y:y + h, x:x + w] > 0
            alpha[in_text & (sat <= 70)] = 0  # text pixels are re-typed, not pictured
            alpha[(rules_d[y:y + h, x:x + w] > 0) & (sat <= 70)] = 0
            rgba = np.dstack([crop, alpha])
            if (alpha > 0).sum() < 100:
                continue
        buf = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
        out.append({"bbox_px": [x, y, x + w, y + h], "png": buf.getvalue(),
                    "behind": photo, "float": not photo})
    return out


# ── assemble IR ────────────────────────────────────────────────────────────

def _to_points(groups, tables, images, hrules, pw, ph, sx, sy) -> dict:
    s = (sx + sy) / 2
    boxes_all = [b for g in groups for b in g["boxes"]]
    serif, mono = _page_font([b for b in boxes_all if not b.get("aux")]) if boxes_all else (True, False)
    default_font = "Courier New" if mono else ("Times New Roman" if serif else "Arial")
    lines = _finish_lines(groups, serif, mono, default_font, s)

    ir_tables = []
    for t in tables:
        xs = [v * s for v in t["xs"]]
        ys = [v * s for v in t["ys"]]
        cells = []
        for c in t["cells"]:
            bb = [xs[c["c"]], ys[c["r"]], xs[c["c"] + c["cs"]], ys[c["r"] + c["rs"]]]
            cells.append({**c, "bbox": bb, "lines": [], "fill": None})
        ti = len(ir_tables)
        for ln in list(lines):
            if ln["cell"] and ln["cell"][0] == ti:
                cells[ln["cell"][1]]["lines"].append(ln)
                lines.remove(ln)
        ir_tables.append({"bbox": [xs[0], ys[0], xs[-1], ys[-1]], "xs": xs, "ys": ys, "cells": cells,
                          "border_pt": max(0.5, min(3.0, t["thick_px"] * s))})

    ir_images = []
    for im in images:
        b = [v * s for v in im["bbox_px"]]
        ir_images.append({"bbox": b, "png": im["png"], "behind": im["behind"], "float": im["float"]})

    hl = [{"x1": r["x1"] * s, "x2": r["x2"] * s, "y": r["y"] * s, "w": max(0.5, r["h"] * s),
           "color": "000000"} for r in hrules]
    return {"width": pw, "height": ph, "lines": lines, "tables": ir_tables,
            "images": ir_images, "hlines": hl}
