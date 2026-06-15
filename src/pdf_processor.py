from pathlib import Path
from typing import List

from PIL import Image


def pdf_to_images(pdf_path: str, dpi: int = 300) -> List[Image.Image]:
    import fitz
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    doc = fitz.open(str(path))
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    return images
