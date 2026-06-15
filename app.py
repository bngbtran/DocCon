"""HF Spaces entry point — FastAPI + Gradio SDK."""
import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

import gradio as gr
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from main import convert as do_convert

# ── Gradio UI (required by HF Spaces sdk: gradio) ─────────────────────────────
with gr.Blocks(title="DocCon") as demo:
    gr.Markdown("## DocCon — PDF to Word")
    gr.Markdown("Gửi **POST /convert** kèm file PDF để chuyển đổi sang Word.")

# ── FastAPI backend ────────────────────────────────────────────────────────────
_api = FastAPI(title="DocCon API", version="1.0.0")

_api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@_api.get("/health")
def health():
    return {"status": "ok"}


@_api.post("/convert")
async def convert_endpoint(
    file: UploadFile = File(...),
    lang: str = Form(default="vi"),
    dpi: int = Form(default=300),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file PDF.")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="File rỗng.")

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, "input.pdf")
        out_path = os.path.join(tmpdir, "output.docx")
        with open(in_path, "wb") as f:
            f.write(pdf_bytes)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, _sync_convert, in_path, out_path, lang, dpi
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        docx_bytes = Path(out_path).read_bytes()

    stem = Path(file.filename).stem
    out_name = f"{stem}.docx"
    encoded = quote(out_name, safe="")
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{out_name}"; '
                f"filename*=UTF-8''{encoded}"
            )
        },
    )


def _sync_convert(in_path: str, out_path: str, lang: str, dpi: int) -> None:
    do_convert(in_path, out_path, lang=lang, dpi=dpi)


# ── Mount Gradio at root, export combined ASGI app ────────────────────────────
app = gr.mount_gradio_app(_api, demo, path="/")
