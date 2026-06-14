from pathlib import Path
from typing import List

from pdf2image import convert_from_path
from PIL import Image


def pdf_to_images(pdf_path: str, dpi: int = 300) -> List[Image.Image]:
    """Convert each PDF page to a PIL Image."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    images = convert_from_path(str(path), dpi=dpi)
    return images
