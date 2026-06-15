from typing import List, Tuple, Optional
import numpy as np

_FONT_MAP = {
    "timesnewroman": "Times New Roman",
    "times": "Times New Roman",
    "arial": "Arial",
    "helvetica": "Arial",
    "symbol": "Symbol",
    "courier": "Courier New",
    "cour": "Courier New",
    "calibri": "Calibri",
    "cambria": "Cambria",
    "verdana": "Verdana",
    "georgia": "Georgia",
    "tahoma": "Tahoma",
    "wingdings": "Wingdings",
}


def _word_font(pdf_name: str) -> str:
    key = pdf_name.lower().replace("-", "").replace(" ", "")
    for pat, wname in _FONT_MAP.items():
        if pat in key:
            return wname
    cleaned = (
        pdf_name.replace("-BoldMT", "")
        .replace("-BoldItalicMT", "")
        .replace("-ItalicMT", "")
        .replace("MT", "")
        .replace("PS", "")
        .replace("-", " ")
        .strip()
    )
    return cleaned or pdf_name


class TextPDFEngine:
    def analyze_page(self, page) -> Tuple[List[dict], dict]:
        data = page.get_text("dict")
        raw_blocks = [b for b in data["blocks"] if b["type"] == 0]
        pw, ph = page.rect.width, page.rect.height

        if not raw_blocks:
            return [], _empty_page_info(pw, ph)

        left_m, right_edge = self._page_geometry(raw_blocks)
        text_w = right_edge - left_m
        body_size = self._body_size(raw_blocks)

        gaps = [
            b2["bbox"][1] - b1["bbox"][3]
            for b1, b2 in zip(raw_blocks, raw_blocks[1:])
            if b2["bbox"][1] - b1["bbox"][3] > 0
        ]
        space_after = float(np.median(gaps)) if gaps else 14.0

        blocks: List[dict] = []
        for raw in raw_blocks:
            b = self._process_block(raw, pw, left_m, text_w, body_size, space_after)
            if b:
                blocks.append(b)

        rows = self._group_rows(blocks)

        items: List[dict] = []
        for row in rows:
            cells = self._split_into_cells(row)
            if len(cells) == 1:
                for b in cells[0]:
                    bb = dict(b)
                    bb["item_type"] = "paragraph"
                    items.append(bb)
            else:
                items.append(
                    {
                        "item_type": "columns",
                        "cells": cells,
                        "page_width_pt": pw,
                        "left_margin_pt": left_m,
                        "right_margin_pt": pw - right_edge,
                    }
                )

        hlines = self._get_hlines(page)
        items = _merge_by_y(items, hlines)

        top_m = raw_blocks[0]["bbox"][1]
        actual_bot = ph - raw_blocks[-1]["bbox"][3]
        bot_m = top_m if actual_bot > ph * 0.3 else actual_bot

        page_info: dict = {
            "page_width_pt": pw,
            "page_height_pt": ph,
            "left_margin_pt": left_m,
            "right_margin_pt": pw - right_edge,
            "top_margin_pt": top_m,
            "bottom_margin_pt": bot_m,
        }
        return items, page_info

    def _process_block(
        self, raw, pw, left_m, text_w, body_size, space_after
    ) -> Optional[dict]:
        spans_out, has_bullet, content_x = self._flatten(raw, left_m)
        if not spans_out:
            return None

        full_text = "".join(s["text"] for s in spans_out).strip()
        if not full_text:
            return None

        bbox = list(raw["bbox"])
        max_size = max(s["size"] for s in spans_out)

        bx1, bx2 = bbox[0], bbox[2]
        bcx = (bx1 + bx2) / 2
        block_w = bx2 - bx1
        is_narrow_centered = abs(bcx - pw / 2) < pw * 0.06 and block_w < text_w * 0.6

        non_last = raw["lines"][:-1]
        has_full_lines = (
            any(
                max((s["bbox"][2] for s in ln["spans"] if s["text"].strip()), default=0)
                > left_m + text_w - 4
                for ln in non_last
            )
            if non_last
            else False
        )

        if is_narrow_centered:
            alignment = "center"
        elif has_full_lines or len(raw["lines"]) > 1:
            alignment = "justify"
        else:
            alignment = "justify"

        indent_first_line = 0.0
        if not has_bullet and len(raw["lines"]) >= 2:

            def _min_x(spans):
                xs = [s["bbox"][0] for s in spans if s["text"].strip()]
                return min(xs) if xs else None

            first_x = _min_x(raw["lines"][0]["spans"])
            rest_xs = [_min_x(ln["spans"]) for ln in raw["lines"][1:] if ln["spans"]]
            rest_xs = [x for x in rest_xs if x is not None]
            if first_x and rest_xs:
                rest_x = float(np.median(rest_xs))
                diff = first_x - rest_x
                if diff > 6:
                    indent_first_line = diff

        if max_size >= body_size * 1.15:
            label = "title" if max_size >= body_size * 1.4 else "section_title"
        elif has_bullet:
            label = "list"
        else:
            label = "text"

        indent_left = content_x - left_m if has_bullet else 0.0
        indent_hanging = indent_left

        return {
            "block_label": label,
            "block_bbox": bbox,
            "block_content": full_text,
            "block_spans": spans_out,
            "block_lines": self._flatten_lines(raw, left_m),
            "has_bullet": has_bullet,
            "alignment": alignment,
            "indent_left_pt": indent_left,
            "indent_hanging_pt": indent_hanging,
            "indent_first_line_pt": indent_first_line,
            "space_after_pt": space_after,
        }

    def _group_rows(self, blocks: List[dict]) -> List[List[dict]]:
        if not blocks:
            return []

        sorted_blocks = sorted(blocks, key=lambda b: b["block_bbox"][1])
        rows: List[List[dict]] = []
        current: List[dict] = [sorted_blocks[0]]

        for block in sorted_blocks[1:]:
            b_y1, b_y2 = block["block_bbox"][1], block["block_bbox"][3]
            row_y1 = min(b["block_bbox"][1] for b in current)
            row_y2 = max(b["block_bbox"][3] for b in current)

            overlap = max(0.0, min(b_y2, row_y2) - max(b_y1, row_y1))
            min_h = min(b_y2 - b_y1, row_y2 - row_y1)

            if min_h > 0 and overlap / min_h > 0.4:
                current.append(block)
            else:
                rows.append(sorted(current, key=lambda b: b["block_bbox"][0]))
                current = [block]

        rows.append(sorted(current, key=lambda b: b["block_bbox"][0]))
        return rows

    def _split_into_cells(self, row: List[dict]) -> List[List[dict]]:
        if len(row) <= 1:
            return [row]

        sorted_row = sorted(row, key=lambda b: b["block_bbox"][0])
        cells: List[List[dict]] = [[sorted_row[0]]]

        for block in sorted_row[1:]:
            bx1, bx2 = block["block_bbox"][0], block["block_bbox"][2]
            bw = max(1.0, bx2 - bx1)
            merged = False
            for cell in cells:
                cell_x1 = min(b["block_bbox"][0] for b in cell)
                cell_x2 = max(b["block_bbox"][2] for b in cell)
                overlap = max(0.0, min(bx2, cell_x2) - max(bx1, cell_x1))
                cell_w = max(1.0, cell_x2 - cell_x1)
                if overlap / min(bw, cell_w) > 0.3:
                    cell.append(block)
                    merged = True
                    break
            if not merged:
                cells.append([block])

        for cell in cells:
            cell.sort(key=lambda b: b["block_bbox"][1])

        cells.sort(key=lambda cell: min(b["block_bbox"][0] for b in cell))
        return cells

    def _flatten(self, block_raw, left_m) -> Tuple[List[dict], bool, float]:
        has_bullet = False
        content_x = left_m + 18.0
        all_spans: List[dict] = []
        skip_next_space = False

        for line in block_raw["lines"]:
            line_spans = []
            for s in line["spans"]:
                t = s["text"]
                if t.strip() == "•":
                    has_bullet = True
                    skip_next_space = True
                    continue
                if skip_next_space and t.strip() == "":
                    skip_next_space = False
                    continue
                skip_next_space = False
                if has_bullet and content_x == left_m + 18.0 and t.strip():
                    content_x = s["bbox"][0]
                line_spans.append(
                    {
                        "text": t,
                        "font": _word_font(s["font"]),
                        "bold": bool(s["flags"] & (1 << 4)),
                        "italic": bool(s["flags"] & (1 << 1)),
                        "size": s["size"],
                        "color": s["color"],
                    }
                )
            if not line_spans:
                continue
            if all_spans:
                prev = all_spans[-1]["text"]
                nxt = line_spans[0]["text"]
                if prev and not prev[-1].isspace() and nxt and not nxt[0].isspace():
                    all_spans[-1] = {**all_spans[-1], "text": prev + " "}
            all_spans.extend(line_spans)

        merged: List[dict] = []
        for s in all_spans:
            if (
                merged
                and merged[-1]["bold"] == s["bold"]
                and merged[-1]["italic"] == s["italic"]
                and merged[-1]["size"] == s["size"]
                and merged[-1]["font"] == s["font"]
                and merged[-1]["color"] == s["color"]
            ):
                merged[-1] = {**merged[-1], "text": merged[-1]["text"] + s["text"]}
            else:
                merged.append(dict(s))

        return merged, has_bullet, content_x

    def _flatten_lines(self, block_raw, left_m) -> List[List[dict]]:
        lines_out: List[List[dict]] = []
        for line in block_raw["lines"]:
            line_spans: List[dict] = []
            skip_next = False
            for s in line["spans"]:
                t = s["text"]
                if t.strip() == "•":
                    skip_next = True
                    continue
                if skip_next and t.strip() == "":
                    skip_next = False
                    continue
                skip_next = False
                line_spans.append(
                    {
                        "text": t,
                        "font": _word_font(s["font"]),
                        "bold": bool(s["flags"] & (1 << 4)),
                        "italic": bool(s["flags"] & (1 << 1)),
                        "size": s["size"],
                        "color": s["color"],
                    }
                )
            if not line_spans:
                continue
            merged: List[dict] = []
            for sp in line_spans:
                if (
                    merged
                    and merged[-1]["bold"] == sp["bold"]
                    and merged[-1]["italic"] == sp["italic"]
                    and merged[-1]["size"] == sp["size"]
                    and merged[-1]["font"] == sp["font"]
                    and merged[-1]["color"] == sp["color"]
                ):
                    merged[-1] = {**merged[-1], "text": merged[-1]["text"] + sp["text"]}
                else:
                    merged.append(dict(sp))
            if any(sp["text"].strip() for sp in merged):
                lines_out.append(merged)
        return lines_out

    def _get_hlines(self, page) -> List[dict]:
        pw = page.rect.width
        hlines: List[dict] = []
        try:
            for path in page.get_drawings():
                rect = path.get("rect")
                if not rect:
                    continue
                h = abs(rect[3] - rect[1])
                w = abs(rect[2] - rect[0])
                if h < 3 and w > pw * 0.08:
                    hlines.append(
                        {
                            "item_type": "hline",
                            "y": (rect[1] + rect[3]) / 2,
                            "x1": rect[0],
                            "x2": rect[2],
                            "thickness_pt": max(0.5, h),
                        }
                    )
        except Exception:
            pass
        return sorted(hlines, key=lambda l: l["y"])

    def _page_geometry(self, raw_blocks) -> Tuple[float, float]:
        x1s, x2s = [], []
        for b in raw_blocks:
            for line in b["lines"]:
                for s in line["spans"]:
                    t = s["text"].strip()
                    if t and t != "•":
                        x1s.append(s["bbox"][0])
                        x2s.append(s["bbox"][2])
        if not x1s:
            return 72.0, 523.0
        return float(np.percentile(x1s, 10)), float(np.percentile(x2s, 90))

    def _body_size(self, raw_blocks) -> float:
        sizes = []
        for b in raw_blocks:
            for line in b["lines"]:
                for s in line["spans"]:
                    if s["text"].strip() and s["text"].strip() != "•":
                        sizes.append(s["size"])
        return float(np.median(sizes)) if sizes else 12.0


def _empty_page_info(pw, ph) -> dict:
    return {
        "page_width_pt": pw,
        "page_height_pt": ph,
        "left_margin_pt": 72,
        "right_margin_pt": 72,
        "top_margin_pt": 72,
        "bottom_margin_pt": 72,
    }


def _item_y(item: dict) -> float:
    itype = item.get("item_type")
    if itype == "paragraph":
        return item["block_bbox"][1]
    elif itype == "columns":
        return min(b["block_bbox"][1] for cell in item["cells"] for b in cell)
    elif itype == "hline":
        return item["y"]
    return 0.0


def _merge_by_y(items: List[dict], hlines: List[dict]) -> List[dict]:
    return sorted(items + hlines, key=_item_y)
