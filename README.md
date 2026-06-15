---
title: DocCon
emoji: 📄
colorFrom: red
colorTo: red
sdk: docker
pinned: false
---

# DocCon — PDF to Word Converter

Chuyển đổi file PDF sang Word (.docx) với độ chính xác cao, giữ nguyên định dạng gốc.  
Hỗ trợ cả PDF văn bản thông thường lẫn PDF scan (ảnh chụp).

**Live:** [tranbnb-doccon.vercel.app](https://tranbnb-doccon.vercel.app)

---

## Tính năng

- **PDF văn bản** — trích xuất trực tiếp qua PyMuPDF, giữ nguyên font, cỡ chữ, in đậm, in nghiêng
- **PDF scan** — OCR tự động bằng EasyOCR (hỗ trợ tiếng Việt và tiếng Anh)
- **Bố cục 2 cột** — nhận diện và tái tạo đúng cấu trúc đa cột (tài liệu hành chính, văn bản nhà nước)
- **Đường kẻ ngang** — phát hiện và chèn đường kẻ phân cách tương ứng trong Word
- **Thụt lề & căn lề** — giữ nguyên căn trái/phải/giữa và thụt đầu dòng

---

## Triển khai

| Thành phần | Nền tảng | URL |
|-----------|----------|-----|
| Frontend | Vercel | [tranbnb-doccon.vercel.app](https://tranbnb-doccon.vercel.app) |
| Backend | Hugging Face Spaces (Docker) | [bngbtran-doccon.hf.space](https://bngbtran-doccon.hf.space) |

---

## Cấu trúc dự án

```
DocCon/
├── api.py                  # FastAPI server
├── Dockerfile              # HF Spaces Docker entry point
├── requirements.txt
├── src/
│   ├── text_pdf_engine.py  # Phân tích PDF văn bản (PyMuPDF)
│   ├── ocr_engine.py       # OCR cho PDF scan (EasyOCR)
│   ├── pdf_processor.py    # Điều phối: chọn engine phù hợp
│   ├── docx_builder.py     # Tạo file .docx từ kết quả phân tích
│   └── utils.py
└── frontend/
    ├── src/
    │   ├── App.jsx         # Router shell
    │   ├── Nav.jsx         # Thanh điều hướng
    │   ├── Home.jsx        # Trang chuyển đổi
    │   └── App.css         # Stylesheet
    ├── public/
    │   └── logo.png
    └── index.html
```

---

## Chạy local

### Yêu cầu

- Python 3.10+, Conda
- Node.js 18+
- Poppler

### Backend

```bash
conda create -n doccon python=3.10
conda activate doccon
conda install -c conda-forge poppler
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Truy cập: [http://localhost:5173](http://localhost:5173)

---

## API

### `POST /convert`

| Tham số | Kiểu | Mô tả |
|---------|------|-------|
| `file` | `File` | File PDF cần chuyển đổi |
| `lang` | `string` | Ngôn ngữ OCR: `vi` (mặc định) hoặc `en` |
| `dpi` | `int` | Độ phân giải OCR cho PDF scan (mặc định: `300`) |

**Response:** file `.docx` (binary)

### `GET /health`

Kiểm tra trạng thái server.

---

## Tech Stack

| Thành phần | Công nghệ |
|-----------|-----------|
| Frontend | React 18 + Vite |
| Backend | FastAPI + Uvicorn |
| PDF (văn bản) | PyMuPDF |
| PDF (scan) | EasyOCR + PyTorch |
| Xuất Word | python-docx |

---

## Phát triển bởi

**TranBNB** — [tranbnb.2004@gmail.com](mailto:tranbnb.2004@gmail.com)
