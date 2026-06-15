"""Entry point for Hugging Face Spaces (Gradio SDK wrapper around FastAPI)."""
import gradio as gr
from api import app as fastapi_app

with gr.Blocks(title="DocCon API") as demo:
    gr.Markdown("## DocCon — PDF to Word")
    gr.Markdown("Gửi `POST /convert` kèm file PDF để chuyển đổi sang Word.")

app = gr.mount_gradio_app(fastapi_app, demo, path="/ui")
