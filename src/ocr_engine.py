import re
import numpy as np
from PIL import Image
from typing import List

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

_NUMBERED = re.compile(r"^\s*(\d+[\.\)]\s|[•\-–—]\s*)")


class LayoutOCR:
    def __init__(self, lang: str = "vi", **_):
        import easyocr
        langs = _LANG_MAP.get(lang, ["en"])
        self.reader = easyocr.Reader(langs, gpu=False, verbose=False)

    def analyze(self, image: Image.Image) -> List[dict]:
        img_array = np.array(image.convert("RGB"))
        raw = self.reader.readtext(img_array, detail=1, paragraph=False)
        return self._to_blocks(raw, img_array)

    def _to_blocks(self, raw, img_array: np.ndarray) -> List[dict]:
        img_h, img_w = img_array.shape[:2]

        items = []
        for entry in raw:
            bbox, text = entry[0], entry[1]
            conf = entry[2] if len(entry) > 2 else 1.0
            if conf < 0.25 or not text.strip():
                continue
            pts = np.array(bbox, dtype=float)
            x1, y1 = int(pts[:, 0].min()), int(pts[:, 1].min())
            x2, y2 = int(pts[:, 0].max()), int(pts[:, 1].max())
            items.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "yc": (y1 + y2) / 2,
                "h":  max(1, y2 - y1),
                "text": text.strip(),
            })

        if not items:
            return []

        avg_h = float(np.median([i["h"] for i in items]))

        items.sort(key=lambda i: (i["yc"], i["x1"]))
        rows: List[List[dict]] = []
        cur_row = [items[0]]
        for item in items[1:]:
            if abs(item["yc"] - cur_row[0]["yc"]) < avg_h * 0.5:
                cur_row.append(item)
            else:
                rows.append(sorted(cur_row, key=lambda i: i["x1"]))
                cur_row = [item]
        rows.append(sorted(cur_row, key=lambda i: i["x1"]))

        all_x1 = []
        lines = []
        for row in rows:
            x1 = min(i["x1"] for i in row)
            y1 = min(i["y1"] for i in row)
            x2 = max(i["x2"] for i in row)
            y2 = max(i["y2"] for i in row)
            text = " ".join(i["text"] for i in row)
            all_x1.append(x1)
            lines.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "h": max(1, y2 - y1),
                "text": text.strip(),
                "bold": self._is_bold(img_array, x1, y1, x2, y2),
            })

        left_margin = float(np.percentile(all_x1, 10))

        for line in lines:
            line["alignment"] = self._alignment(line, img_w, left_margin)

        PARA_GAP = max(20, avg_h * 0.6)
        para_groups: List[List[dict]] = []
        cur_para = [lines[0]]
        for line in lines[1:]:
            gap = line["y1"] - cur_para[-1]["y2"]
            new_align = line["alignment"] != cur_para[0]["alignment"]
            if gap > PARA_GAP or new_align or cur_para[0]["alignment"] == "center":
                para_groups.append(cur_para)
                cur_para = [line]
            else:
                cur_para.append(line)
        para_groups.append(cur_para)

        blocks: List[dict] = []
        for para in para_groups:
            text = " ".join(l["text"] for l in para).strip()
            if not text:
                continue
            x1 = min(l["x1"] for l in para)
            y1 = min(l["y1"] for l in para)
            x2 = max(l["x2"] for l in para)
            y2 = max(l["y2"] for l in para)
            alignment = para[0]["alignment"]
            is_bold   = any(l["bold"] for l in para)

            max_h = max(l["h"] for l in para)
            h_ratio = max_h / avg_h
            if h_ratio > 1.35:
                font_size = 16
            elif h_ratio > 1.12:
                font_size = 14
            else:
                font_size = 13

            if alignment == "center":
                label = "title" if is_bold else "section_title"
            elif _NUMBERED.match(para[0]["text"]):
                label = "list"
            else:
                label = "text"

            blocks.append({
                "block_label":     label,
                "block_bbox":      [x1, y1, x2, y2],
                "block_content":   text,
                "block_alignment": alignment,
                "block_bold":      is_bold,
                "block_font":      "Times New Roman",
                "block_size":      font_size,
            })

        return blocks

    def _alignment(self, line: dict, img_w: int, left_margin: float) -> str:
        x1, x2, cx = line["x1"], line["x2"], (line["x1"] + line["x2"]) / 2
        page_cx = img_w / 2
        w = x2 - x1

        if abs(cx - page_cx) < img_w * 0.09 and w < img_w * 0.75:
            return "center"
        if x1 > page_cx * 0.9 and x2 > img_w * 0.75:
            return "right"
        return "left"

    def _is_bold(self, img: np.ndarray, x1: int, y1: int,
                 x2: int, y2: int, threshold: float = 0.38) -> bool:
        h, w = img.shape[:2]
        x1c, y1c = max(0, x1), max(0, y1)
        x2c, y2c = min(w, x2), min(h, y2)
        if x2c <= x1c or y2c <= y1c:
            return False
        region = img[y1c:y2c, x1c:x2c].astype(np.float32)
        gray = 0.299 * region[:, :, 0] + 0.587 * region[:, :, 1] + 0.114 * region[:, :, 2]
        return float(np.mean(gray < 128)) > threshold
