"""Page IR → flow layout (paragraphs, column regions, tables, pictures, rules).

All coordinates are PDF points measured from the page's top-left corner.
Every produced item carries `top`/`bottom` in the same vertical model the
DOCX builder uses, so spacing in Word reproduces the PDF positions.
"""
import re
from typing import List, Optional

import numpy as np

# Height of a single-spaced line as a multiple of font size (Word metrics).
_LINE_FACTOR = {
    "Times New Roman": 1.15, "Arial": 1.15, "Calibri": 1.22, "Calibri Light": 1.22,
    "Cambria": 1.17, "Aptos": 1.2, "Courier New": 1.133, "Verdana": 1.215,
    "Tahoma": 1.207, "Segoe UI": 1.33, "Georgia": 1.136, "Consolas": 1.17,
}
# Distance from the baseline to the bottom of an exact-height line, in em.
DESCENT = 0.25

_BULLET = re.compile(r"^\s*([•●▪■◦○◆◇►▸✓✔\-–—+*]|o(?=\s)|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)]|[IVXivx]{1,4}[.)])\s")


def line_factor(font: str) -> float:
    return _LINE_FACTOR.get(font, 1.17)


def build_page_layout(page: dict) -> dict:
    pw, ph = page["width"], page["height"]
    lines = page["lines"]
    tables = page["tables"]

    text_boxes = [l["bbox"] for l in lines] + [t["bbox"] for t in tables]
    floats, inline_imgs = [], []
    for im in page["images"]:
        if im.get("float") or any(_overlap_frac(tb, im["bbox"]) > 0.15 for tb in text_boxes):
            floats.append(im)
        else:
            inline_imgs.append(im)

    atoms = [_atom("line", l["bbox"], l) for l in lines]
    atoms += [_atom("table", t["bbox"], t) for t in tables]
    atoms += [_atom("image", im["bbox"], im) for im in inline_imgs]
    atoms += [_atom("hline", [h["x1"], h["y"] - 0.5, h["x2"], h["y"] + 0.5], h) for h in page["hlines"]]

    if not atoms:
        return {"width": pw, "height": ph,
                "margins": {"left": 72, "right": 72, "top": 72, "bottom": 72},
                "items": [], "floats": floats}

    x0 = min(a["bbox"][0] for a in atoms)
    x1 = max(a["bbox"][2] for a in atoms)
    x0 = max(0.0, min(x0, pw - 72))
    x1 = min(pw, max(x1, x0 + 72))
    items = layout_region(atoms, x0, x1)

    bottom = max(it["bottom"] for it in items) if items else ph - 72
    return {
        "width": pw,
        "height": ph,
        "margins": {
            "left": x0,
            "right": max(0.0, pw - x1),
            "top": max(0.0, items[0]["top"]) if items else 72,
            "bottom": max(0.0, min(ph - bottom - 2, 28.0)),
        },
        "items": items,
        "floats": floats,
    }


def _atom(kind: str, bbox, obj) -> dict:
    return {"kind": kind, "bbox": list(bbox), "obj": obj}


def _overlap_frac(a, b) -> float:
    """Intersection area as a fraction of box `a`."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


# ── region analysis ────────────────────────────────────────────────────────

def layout_region(atoms: List[dict], x0: float, x1: float, depth: int = 0) -> List[dict]:
    rows = _group_rows(atoms)
    sizes = [a["obj"]["size"] for a in atoms if a["kind"] == "line"]
    body = float(np.median(sizes)) if sizes else 11.0
    col_gap = max(14.0, 1.5 * body)
    rows = [_merge_row_lines(r, col_gap) for r in rows]

    items: List[dict] = []
    flow: List[dict] = []
    i = 0
    while i < len(rows):
        gutters = _gutters(rows[i], col_gap) if depth < 4 else []
        if not gutters:
            flow.extend(rows[i])
            i += 1
            continue
        region = [rows[i]]
        bottom = max(a["bbox"][3] for a in rows[i])
        j = i + 1
        while j < len(rows):
            r = rows[j]
            top = min(a["bbox"][1] for a in r)
            if top - bottom > max(2.5 * body * 1.2, 24.0):
                break
            survived = [g for g in (_shrink(g, r) for g in gutters) if g]
            if not survived:
                break
            gutters = survived
            region.append(r)
            bottom = max(bottom, max(a["bbox"][3] for a in r))
            j += 1
        if flow:
            items.extend(_flow_items(flow, x0, x1))
            flow = []
        items.append(_columns_item([a for r in region for a in r], gutters, x0, x1, depth))
        i = j
    if flow:
        items.extend(_flow_items(flow, x0, x1))
    return items


def _group_rows(atoms: List[dict]) -> List[List[dict]]:
    rows: List[List[dict]] = []
    span = None
    for a in sorted(atoms, key=lambda a: (a["bbox"][1], a["bbox"][0])):
        y0, y1 = a["bbox"][1], a["bbox"][3]
        h = max(1.0, y1 - y0)
        if span is not None:
            ov = min(y1, span[1]) - max(y0, span[0])
            if ov > 0.3 * min(h, max(1.0, span[1] - span[0])):
                rows[-1].append(a)
                span = (min(span[0], y0), max(span[1], y1))
                continue
        rows.append([a])
        span = (y0, y1)
    return [sorted(r, key=lambda a: a["bbox"][0]) for r in rows]


def _merge_row_lines(row: List[dict], col_gap: float) -> List[dict]:
    """Join text fragments of one visual line that are closer than a gutter."""
    out: List[dict] = []
    for a in row:
        prev = out[-1] if out else None
        if (prev and a["kind"] == "line" and prev["kind"] == "line"
                and a["bbox"][0] - prev["bbox"][2] < col_gap
                and abs(a["obj"]["baseline"] - prev["obj"]["baseline"]) < 0.4 * a["obj"]["size"]):
            out[-1] = _atom("line", [prev["bbox"][0], min(prev["bbox"][1], a["bbox"][1]),
                                     max(prev["bbox"][2], a["bbox"][2]), max(prev["bbox"][3], a["bbox"][3])],
                            join_lines(prev["obj"], a["obj"]))
        else:
            out.append(a)
    return out


def join_lines(a: dict, b: dict) -> dict:
    gap = b["bbox"][0] - a["bbox"][2]
    runs = [dict(r) for r in a["runs"]]
    if gap > max(1.2 * a["size"], 6.0):
        sep = [{"tab": True, "x": b["bbox"][0], "leader": None, "align": "left",
                "seg_end": b["bbox"][2]}]
    else:
        last = next((r for r in reversed(runs) if not r.get("tab")), None)
        sep = []
        if last and not last["text"].endswith(" "):
            last["text"] += " "
    runs += sep + [dict(r) for r in b["runs"]]
    return {
        **a,
        "bbox": [min(a["bbox"][0], b["bbox"][0]), min(a["bbox"][1], b["bbox"][1]),
                 max(a["bbox"][2], b["bbox"][2]), max(a["bbox"][3], b["bbox"][3])],
        "runs": runs,
        "size": max(a["size"], b["size"]),
        "baseline": a["baseline"] if a["size"] >= b["size"] else b["baseline"],
        "nat_end": b.get("nat_end", b["bbox"][2]),
    }


def _intervals(row: List[dict]) -> List[List[float]]:
    iv: List[List[float]] = []
    for a in sorted(row, key=lambda a: a["bbox"][0]):
        if iv and a["bbox"][0] <= iv[-1][1]:
            iv[-1][1] = max(iv[-1][1], a["bbox"][2])
        else:
            iv.append([a["bbox"][0], a["bbox"][2]])
    return iv


def _gutters(row: List[dict], col_gap: float) -> List[tuple]:
    if len(row) < 2:
        return []
    iv = _intervals(row)
    return [(iv[k][1], iv[k + 1][0]) for k in range(len(iv) - 1) if iv[k + 1][0] - iv[k][1] >= col_gap]


def _shrink(g: tuple, row: List[dict]) -> Optional[tuple]:
    """Free part of gutter `g` left after placing `row`; None when blocked."""
    free = [g]
    for a in row:
        nxt = []
        for lo, hi in free:
            ax0, ax1 = a["bbox"][0], a["bbox"][2]
            if ax1 <= lo or ax0 >= hi:
                nxt.append((lo, hi))
                continue
            if ax0 > lo:
                nxt.append((lo, ax0))
            if ax1 < hi:
                nxt.append((ax1, hi))
        free = nxt
    best = max(free, key=lambda p: p[1] - p[0], default=None)
    return best if best and best[1] - best[0] >= 6.0 else None


def _columns_item(atoms: List[dict], gutters: List[tuple], x0: float, x1: float, depth: int) -> dict:
    gutters = sorted(gutters)
    bounds = [x0] + [(lo + hi) / 2 for lo, hi in gutters] + [x1]
    cols: List[List[dict]] = [[] for _ in range(len(bounds) - 1)]
    for a in atoms:
        cx = (a["bbox"][0] + a["bbox"][2]) / 2
        k = max(0, min(len(cols) - 1, int(np.searchsorted(bounds[1:-1], cx))))
        cols[k].append(a)
    col_items = [layout_region(c, bounds[k], bounds[k + 1], depth + 1) if c else [] for k, c in enumerate(cols)]
    top = min(it["top"] for ci in col_items for it in ci)
    bottom = max(it["bottom"] for ci in col_items for it in ci)
    return {"type": "columns", "x0": x0, "x1": x1, "bounds": bounds, "cols": col_items,
            "top": top, "bottom": bottom}


# ── flow (single column) ───────────────────────────────────────────────────

def _flow_items(atoms: List[dict], x0: float, x1: float) -> List[dict]:
    items: List[dict] = []
    para: List[dict] = []

    def flush():
        if para:
            items.extend(make_paragraphs(list(para), x0, x1))
            para.clear()

    for a in sorted(atoms, key=lambda a: (a["bbox"][1], a["bbox"][0])):
        k = a["kind"]
        if k == "line":
            para.append(a["obj"])
            continue
        flush()
        b = a["bbox"]
        if k == "table":
            items.append({"type": "table", "table": a["obj"], "x0": x0, "x1": x1,
                          "top": b[1], "bottom": b[3]})
        elif k == "image":
            items.append({"type": "image", "img": a["obj"], "left": b[0] - x0,
                          "top": b[1], "bottom": b[3]})
        elif k == "hline":
            h = a["obj"]
            items.append({"type": "hline", "left": max(0.0, h["x1"] - x0), "right": max(0.0, x1 - h["x2"]),
                          "w": h["w"], "color": h["color"], "top": h["y"] - 1.0, "bottom": h["y"] + 0.5})
    flush()
    return items


def _text(line: dict) -> str:
    return "".join("\t" if r.get("tab") else r["text"] for r in line["runs"])


def _all_bold(line: dict) -> bool:
    rs = [r for r in line["runs"] if not r.get("tab") and r["text"].strip()]
    return bool(rs) and all(r["bold"] for r in rs)


def _first_word_width(line: dict) -> float:
    for r in line["runs"]:
        if r.get("tab"):
            return 0.0
        t = r["text"].lstrip()
        if t:
            word = t.split(" ")[0]
            n = max(1, len(r["text"]))
            return (r["x1"] - r["x0"]) * len(word) / n
    return 0.0


def _starts_item(line: dict) -> bool:
    return bool(_BULLET.match(_text(line)))


def make_paragraphs(lines: List[dict], x0: float, x1: float) -> List[dict]:
    lines = sorted(lines, key=lambda l: l["baseline"])
    groups: List[List[dict]] = []
    breaks: List[List[bool]] = []
    for ln in lines:
        if groups:
            ok, is_break = _continues(groups[-1], ln, x0, x1)
            if ok:
                groups[-1].append(ln)
                breaks[-1].append(is_break)
                continue
        groups.append([ln])
        breaks.append([])
    return [_paragraph(g, b, x0, x1) for g, b in zip(groups, breaks)]


def _continues(group: List[dict], ln: dict, x0: float, x1: float):
    prev = group[-1]
    size = prev["size"]
    if abs(ln["size"] - size) > 0.15 * size or _starts_item(ln):
        return False, False
    pitch = ln["baseline"] - prev["baseline"]
    if not 0.85 * size <= pitch <= 2.0 * size:
        return False, False
    if len(group) >= 2:
        est = group[1]["baseline"] - group[0]["baseline"]
        if abs(pitch - est) > 0.12 * est:
            return False, False
        if abs(ln["bbox"][0] - group[1]["bbox"][0]) > 2.5:
            return False, False
    if _all_bold(ln) != _all_bold(prev):
        return False, False
    if any(r.get("tab") for r in ln["runs"]):
        return False, False

    # Centered lines (titles, cells) stay separate one-line paragraphs.
    c_prev = (prev["bbox"][0] + prev["bbox"][2]) / 2
    c_ln = (ln["bbox"][0] + ln["bbox"][2]) / 2
    if abs(c_prev - c_ln) <= 2.0 and abs(prev["bbox"][0] - ln["bbox"][0]) > 3.0:
        return False, False

    space = 0.25 * size
    natural = prev["bbox"][2] + space + _first_word_width(ln) > x1 - 1.0
    if natural:
        if len(group) == 1 and abs(ln["bbox"][0] - prev["bbox"][0]) > 40:
            return False, False
        return True, False
    # Hard line break: only inside left-aligned blocks with a shared left edge.
    if abs(ln["bbox"][0] - prev["bbox"][0]) <= 2.0 and abs(prev["bbox"][0] - x0) <= 0.3 * (x1 - x0):
        centered = abs((ln["bbox"][0] + ln["bbox"][2]) / 2 - (prev["bbox"][0] + prev["bbox"][2]) / 2) <= 2.0
        if not centered or abs(ln["bbox"][2] - prev["bbox"][2]) <= 2.0:
            return True, True
    return False, False


def _paragraph(lines: List[dict], breaks: List[bool], x0: float, x1: float) -> dict:
    width = x1 - x0
    first = lines[0]
    size = float(np.median([l["size"] for l in lines]))
    font = _main_font(lines)
    L1 = first["bbox"][0]
    Lc = float(np.median([l["bbox"][0] for l in lines[1:]])) if len(lines) > 1 else L1
    R = max(l["bbox"][2] for l in lines)

    if len(lines) > 1:
        pitch = float(np.median(np.diff([l["baseline"] for l in lines])))
    else:
        pitch = round(line_factor(font) * size * 2) / 2

    align, left, right, first_indent = "left", Lc - x0, 0.0, L1 - Lc
    if len(lines) == 1:
        c = (first["bbox"][0] + first["bbox"][2]) / 2
        mid = (x0 + x1) / 2
        has_tab = any(r.get("tab") for r in first["runs"])
        if not has_tab and L1 - x0 > 6 and abs(c - mid) <= max(3.0, 0.03 * width):
            align, first_indent = "center", 0.0
            shift = 2 * c - x0 - x1
            left, right = (shift, 0.0) if shift > 0 else (0.0, -shift)
        elif not has_tab and x1 - first["bbox"][2] <= 3.0 and L1 - x0 > 0.3 * width:
            align, left, right, first_indent = "right", 0.0, x1 - first["bbox"][2], 0.0
        else:
            right = 0.0
    else:
        body = lines[:-1]
        if all(not b for b in breaks):
            ends = [l["bbox"][2] for l in body]
            if all("nat_end" in l for l in body):
                # Justified PDF text is wider than its natural width.
                justified = all(l["bbox"][2] - l["nat_end"] > 0.8 for l in body if " " in _text(l).strip())
            else:
                justified = len(body) >= 2 and max(ends) - min(ends) <= 2.5
            if justified:
                align = "justify"
            bound = _wrap_bound(lines, x1)
            if bound is None:
                # No single width reproduces the PDF's line breaks: pin them.
                breaks = [True] * len(body)
                bound = max(ends)
            right = x1 - bound

    # Lines that must not wrap get a little slack beyond the column edge.
    if align != "justify" and (len(lines) == 1 or all(breaks)):
        need = max(l["bbox"][0] + 1.03 * (l.get("nat_end", l["bbox"][2]) - l["bbox"][0]) + 1.0 for l in lines)
        if align == "center":
            short = need - (x1 - right)
            if short > 0:
                left, right = left - short, right - short
        elif align == "left":
            right = min(right, x1 - need)

    tabs = _tab_stops(lines, x0, x1)
    top = first["baseline"] - pitch + DESCENT * size
    return {
        "type": "para",
        "lines": lines,
        "breaks": breaks,
        "align": align,
        "left": max(-x0, left),
        "right": right,
        "first": first_indent,
        "pitch": pitch,
        "size": size,
        "font": font,
        "tabs": tabs,
        "top": top,
        "bottom": top + pitch * len(lines),
    }


def _wrap_bound(lines: List[dict], x1: float) -> Optional[float]:
    """Right edge at which Word wraps every line exactly where the PDF did."""
    lo, hi = -1e9, 1e9
    for l, n in zip(lines[:-1], lines[1:]):
        end = l.get("nat_end", l["bbox"][2])
        sp = l.get("space_w", 0.25 * l["size"])
        nxt = n.get("first_w", _first_word_width(n))
        lo = max(lo, end)
        hi = min(hi, end + sp + nxt)
    if lo >= hi - 0.3:
        return None
    if lo + 0.3 <= x1 <= hi - 0.3:
        return x1  # the column edge itself works: keep the natural margin
    return (lo + hi) / 2


def _main_font(lines: List[dict]) -> str:
    weight = {}
    for l in lines:
        for r in l["runs"]:
            if not r.get("tab"):
                weight[r["font"]] = weight.get(r["font"], 0) + len(r["text"])
    return max(weight, key=weight.get) if weight else "Times New Roman"


def _tab_stops(lines: List[dict], x0: float, x1: float) -> List[dict]:
    stops = {}
    for l in lines:
        tabs = [r for r in l["runs"] if r.get("tab")]
        for k, t in enumerate(tabs):
            if t["align"] == "right" or (k == len(tabs) - 1 and t.get("seg_end", 0) >= x1 - 3
                                         and t["x"] - x0 > 0.5 * (x1 - x0)):
                pos = (t.get("seg_end") or t["x"]) - x0
                t["align"] = "right"
                stops[round(pos, 1)] = {"pos": pos, "align": "right", "leader": t.get("leader")}
            else:
                pos = t["x"] - x0
                stops[round(pos, 1)] = {"pos": pos, "align": "left", "leader": t.get("leader")}
    return sorted(stops.values(), key=lambda s: s["pos"])
