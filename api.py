"""FastAPI server — wraps the PDF→Word conversion logic as an HTTP endpoint."""
import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from main import convert

app = FastAPI(title="DocCon API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/convert")
async def convert_endpoint(
    file: UploadFile = File(...),
    lang: str = Form(default="vi"),
    dpi: int = Form(default=300),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file PDF.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="File rỗng.")

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path  = os.path.join(tmpdir, "input.pdf")
        out_path = os.path.join(tmpdir, "output.docx")

        with open(in_path, "wb") as f:
            f.write(pdf_bytes)

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, _run_convert, in_path, out_path, lang, dpi
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        with open(out_path, "rb") as f:
            docx_bytes = f.read()

    stem = Path(file.filename).stem
    out_name = f"{stem}.docx"
    encoded  = quote(out_name, safe="")

    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{out_name}\"; "
                f"filename*=UTF-8''{encoded}"
            )
        },
    )


def _run_convert(in_path: str, out_path: str, lang: str, dpi: int):
    convert(in_path, out_path, lang=lang, dpi=dpi)
