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

---

## Tính năng

- **PDF văn bản** — trích xuất trực tiếp qua PyMuPDF, giữ nguyên font, cỡ chữ, in đậm, in nghiêng
- **PDF scan** — OCR tự động bằng EasyOCR (hỗ trợ tiếng Việt và tiếng Anh)
- **Bố cục 2 cột** — nhận diện và tái tạo đúng cấu trúc đa cột (tài liệu hành chính, văn bản nhà nước)
- **Đường kẻ ngang** — phát hiện và chèn đường kẻ phân cách tương ứng trong Word
- **Thụt lề & căn lề** — giữ nguyên căn trái/phải/giữa và thụt đầu dòng

---

## Cấu trúc dự án

```
DocCon/
├── api.py                  # FastAPI server
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

## Cài đặt

### Yêu cầu

- Python 3.10+
- Conda (khuyến nghị)
- Node.js 18+
- Poppler (cho pdf2image)

### Backend

```bash
# Tạo môi trường conda
conda create -n msa python=3.10
conda activate msa

# Cài poppler
conda install -c conda-forge poppler

# Cài dependencies Python
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

---

## Chạy ứng dụng

**Terminal 1 — Backend:**
```bash
conda activate msa
uvicorn api:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Truy cập: [http://localhost:5173](http://localhost:5173)

---

## API

### `POST /convert`

Chuyển đổi file PDF sang Word.

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
