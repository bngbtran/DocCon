import io
from html.parser import HTMLParser
from typing import List

from PIL import Image


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: List[List[str]] = []
        self._row: List[str] = []
        self._cell: str = ""
        self._in_cell: bool = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = ""

    def handle_endtag(self, tag):
        if tag == "tr":
            if self._row:
                self.rows.append(self._row)
        elif tag in ("td", "th"):
            self._row.append(self._cell.strip())
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._cell += data


def html_to_table(html: str) -> List[List[str]]:
    parser = _HTMLTableParser()
    parser.feed(html)
    return parser.rows


def pil_to_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def crop_image(image: Image.Image, bbox: List[float]) -> Image.Image:
    x1, y1, x2, y2 = (int(v) for v in bbox)
    return image.crop((x1, y1, x2, y2))
