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

Mỗi trang PDF được phân loại và xử lý riêng, nên PDF hỗn hợp (văn bản + scan) cũng được hỗ trợ:

| Loại trang | Cách xử lý |
|-----------|------------|
| **PDF văn bản** | Đọc trực tiếp từng ký tự qua PyMuPDF: giữ font gốc, cỡ chữ, đậm/nghiêng/gạch chân, màu, chỉ số trên |
| **PDF scan / ảnh chụp** | Tự xoay trang (90°/180°), chống nghiêng, OCR bằng EasyOCR; ước lượng cỡ chữ, đậm, nghiêng, màu chữ từ ảnh |
| **PDF scan đã OCR sẵn** (có lớp chữ ẩn) | Dùng lớp chữ có sẵn, kiểu chữ lấy từ ảnh |
| **Text hỏng mã hóa / font TCVN3, VNI** | Render rồi OCR lại để ra Unicode chuẩn |

Giữ bố cục:

- **Khổ giấy từng trang** — mỗi trang PDF là một section Word với đúng kích thước, hướng (dọc/ngang) và lề
- **Vị trí dọc chính xác** — giãn dòng và khoảng cách đoạn tính từ toạ độ thật, số trang Word khớp PDF
- **Ngắt dòng như bản gốc** — đo độ rộng tự nhiên của dòng để Word xuống dòng đúng chỗ
- **Bố cục nhiều cột** — header 2 cột của văn bản hành chính, khối "Nơi nhận / Chữ ký"… dựng bằng bảng không viền
- **Bảng** — nhận diện bảng có kẻ (cả PDF văn bản lẫn scan), giữ ô gộp, độ rộng cột, chiều cao hàng, màu nền ô
- **Tab, gạch đầu dòng, mục lục** — tab stop đúng vị trí, dấu chấm dẫn (`........ 12`), thụt lề treo
- **Hình ảnh, con dấu, chữ ký** — đặt nổi đúng vị trí; con dấu/chữ ký từ bản scan được tách nền trong suốt
- **Đường kẻ, khung, nền màu** — đường kẻ ngang thành viền đoạn; khung/hình vẽ vector giữ nguyên dạng ảnh

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
│   ├── pdf_processor.py    # Phân loại từng trang và điều phối
│   ├── text_pdf_engine.py  # Trích xuất PDF văn bản (PyMuPDF)
│   ├── ocr_engine.py       # PDF scan: xoay/chống nghiêng, bảng, OCR, kiểu chữ, con dấu
│   ├── layout.py           # Dựng bố cục: đoạn, cột, căn lề, thụt lề, tab, khoảng cách
│   ├── docx_builder.py     # Xuất .docx (section theo trang, bảng, ảnh nổi)
│   └── fonts.py            # Chuẩn hoá tên font PDF → font Word, sửa lỗi mã hoá tiếng Việt
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

### Backend

```bash
conda create -n doccon python=3.10
conda activate doccon
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
