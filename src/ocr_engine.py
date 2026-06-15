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


class LayoutOCR:
    def __init__(self, lang: str = "vi", **_):
        import easyocr

        langs = _LANG_MAP.get(lang, ["en"])
        self.reader = easyocr.Reader(langs, gpu=False, verbose=False)

    def analyze(self, image: Image.Image) -> List[dict]:
        img_array = np.array(image.convert("RGB"))
        raw = self.reader.readtext(img_array, detail=1, paragraph=False)
        return self._to_blocks(raw, img_array.shape)

    def _to_blocks(self, raw, img_shape) -> List[dict]:
        img_h, img_w = img_shape[:2]

        items = []
        for entry in raw:
            bbox, text = entry[0], entry[1]
            conf = entry[2] if len(entry) > 2 else 1.0
            if conf < 0.25 or not text.strip():
                continue
            pts = np.array(bbox, dtype=float)
            x1, y1 = int(pts[:, 0].min()), int(pts[:, 1].min())
            x2, y2 = int(pts[:, 0].max()), int(pts[:, 1].max())
            items.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "yc": (y1 + y2) / 2,
                    "h": max(1, y2 - y1),
                    "text": text.strip(),
                }
            )

        if not items:
            return []

        avg_h = float(np.median([i["h"] for i in items]))

        items.sort(key=lambda i: (i["yc"], i["x1"]))
        rows: List[List[dict]] = []
        cur_row: List[dict] = [items[0]]
        for item in items[1:]:
            if abs(item["yc"] - cur_row[0]["yc"]) < avg_h * 0.5:
                cur_row.append(item)
            else:
                rows.append(sorted(cur_row, key=lambda i: i["x1"]))
                cur_row = [item]
        rows.append(sorted(cur_row, key=lambda i: i["x1"]))

        lines = []
        for row in rows:
            x1 = min(i["x1"] for i in row)
            y1 = min(i["y1"] for i in row)
            x2 = max(i["x2"] for i in row)
            y2 = max(i["y2"] for i in row)
            text = " ".join(i["text"] for i in row)
            lines.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "h": y2 - y1,
                    "cx": (x1 + x2) / 2,
                    "text": text.strip(),
                }
            )

        PARA_GAP = max(20, avg_h * 0.4)
        para_groups: List[List[dict]] = []
        cur_para: List[dict] = [lines[0]]
        for line in lines[1:]:
            gap = line["y1"] - cur_para[-1]["y2"]
            if gap > PARA_GAP:
                para_groups.append(cur_para)
                cur_para = [line]
            else:
                cur_para.append(line)
        para_groups.append(cur_para)

        all_x1 = [l["x1"] for l in lines]
        left_margin = float(np.percentile(all_x1, 10))
        page_cx = img_w / 2
        indent_thresh = avg_h * 0.7

        blocks: List[dict] = []
        for para in para_groups:
            text = " ".join(l["text"] for l in para).strip()
            if not text:
                continue
            x1 = min(l["x1"] for l in para)
            y1 = min(l["y1"] for l in para)
            x2 = max(l["x2"] for l in para)
            y2 = max(l["y2"] for l in para)

            first_x1 = para[0]["x1"]
            para_cx = (x1 + x2) / 2
            para_w = x2 - x1
            is_centered = (
                abs(para_cx - page_cx) < img_w * 0.08 and para_w < img_w * 0.45
            )

            if is_centered and len(para) <= 2 and len(text) <= 120:
                label = "title"
            elif first_x1 > left_margin + indent_thresh:
                label = "list"
            else:
                label = "text"

            blocks.append(
                {
                    "block_label": label,
                    "block_bbox": [x1, y1, x2, y2],
                    "block_content": text,
                }
            )

        return blocks
