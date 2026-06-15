import { useState, useCallback, useRef } from 'react'

const LANGS = [
  { value: 'vi', flag: 'vn', label: 'Tiếng Việt' },
  { value: 'en', flag: 'gb', label: 'English' },
]

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const FEATURES = [
  'Giữ nguyên font, cỡ chữ, in đậm, in nghiêng, bảng biểu',
  'Nhận diện ảnh nhúng, bố cục 2 cột, đường kẻ, thụt lề',
  'Hỗ trợ tiếng Việt, scan PDF với OCR tự động',
]

const PDF_TYPES = [
  {
    label: 'PDF văn bản',
    desc: 'Giữ nguyên font, bảng biểu, ảnh nhúng',
  },
  {
    label: 'PDF scan / ảnh',
    desc: 'OCR tự động, người dùng cần chỉnh sửa lại font, bảng biểu, ảnh nhúng',
  },
  {
    label: 'PDF hỗn hợp',
    desc: 'Phát hiện từng trang, người dùng cần tinh chỉnh lại font, bảng biểu, ảnh nhúng',
  },
]

export default function Home() {
  const [file, setFile]         = useState(null)
  const [lang, setLang]         = useState('vi')
  const [phase, setPhase]       = useState('idle')
  const [error, setError]       = useState('')
  const [dragging, setDragging] = useState(false)
  const [dlUrl, setDlUrl]       = useState(null)
  const [dlName, setDlName]     = useState('')
  const [elapsed, setElapsed]   = useState(0)
  const timerRef = useRef(null)
  const inputRef = useRef(null)

  const pickFile = useCallback((f) => {
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      setError('Chỉ hỗ trợ file PDF.')
      setPhase('error')
      return
    }
    setFile(f); setPhase('idle'); setError(''); setDlUrl(null)
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault(); setDragging(false)
    pickFile(e.dataTransfer.files[0])
  }, [pickFile])

  const reset = () => {
    setFile(null); setPhase('idle')
    setDlUrl(null); setError('')
    clearInterval(timerRef.current); setElapsed(0)
  }

  const convert = async () => {
    if (!file || phase === 'converting') return
    setPhase('converting'); setElapsed(0)
    timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
    const form = new FormData()
    form.append('file', file); form.append('lang', lang); form.append('dpi', '300')
    try {
      const base = import.meta.env.VITE_API_URL ?? ''
      const res = await fetch(`${base}/convert`, { method: 'POST', body: form })
      if (!res.ok) {
        const j = await res.json().catch(() => null)
        throw new Error(j?.detail ?? `Lỗi máy chủ (HTTP ${res.status})`)
      }
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const name = file.name.replace(/\.pdf$/i, '.docx')
      setDlUrl(url); setDlName(name); setPhase('done')
    } catch (err) {
      setError(err.message); setPhase('error')
    } finally {
      clearInterval(timerRef.current)
    }
  }

  const busy = phase === 'converting'

  return (
    <main className="main">
      <div className="container">

        <div className="left">
          <h1 className="title">Chuyển đổi<br />PDF sang Word</h1>
          <p className="subtitle">
            Chuyển tài liệu PDF sang file Word có thể chỉnh sửa.
            Hỗ trợ <strong>PDF văn bản</strong>, <strong>PDF scan</strong> và <strong>PDF có ảnh nhúng</strong>.
          </p>
          <ul className="features">
            {FEATURES.map((f, i) => (
              <li key={i} className="feature-item">
                <span className="feature-check">
                  <svg viewBox="0 0 20 20" fill="currentColor" width="20" height="20">
                    <circle cx="10" cy="10" r="10" className="check-circle" />
                    <path d="M6 10l3 3 5-5" stroke="#fff" strokeWidth="1.8"
                      strokeLinecap="round" strokeLinejoin="round" fill="none" />
                  </svg>
                </span>
                {f}
              </li>
            ))}
          </ul>

          <div className="support-block">
            <p className="support-heading">Hỗ trợ tất cả loại PDF</p>
            <div className="support-grid">
              {PDF_TYPES.map(({ label, desc }) => (
                <div key={label} className="support-card">
                  <svg className="support-check" viewBox="0 0 20 20" fill="none" width="17" height="17">
                    <circle cx="10" cy="10" r="10" fill="#10b981" />
                    <path d="M6 10l3 3 5-5" stroke="#fff" strokeWidth="1.8"
                      strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <div>
                    <p className="support-label">{label}</p>
                    <p className="support-desc">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="right">
          <div className="card">

            <div
              className={[
                'zone',
                dragging      ? 'zone--drag'  : '',
                file          ? 'zone--filled' : '',
                phase==='done'? 'zone--done'   : '',
              ].join(' ')}
              onDrop={onDrop}
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onClick={() => !file && inputRef.current?.click()}
              role="button" tabIndex={0}
              onKeyDown={e => e.key === 'Enter' && !file && inputRef.current?.click()}
            >
              <input ref={inputRef} type="file" accept=".pdf" hidden
                onChange={e => pickFile(e.target.files[0])} />

              {phase === 'done' ? (
                <div className="zone-success">
                  <div className="success-icon">
                    <svg viewBox="0 0 24 24" fill="none" width="36" height="36">
                      <circle cx="12" cy="12" r="12" fill="#9F0712" />
                      <path d="M7 12l4 4 6-6" stroke="#fff" strokeWidth="2"
                        strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <p className="zone-success-title">Hoàn tất!</p>
                  <p className="zone-success-name">{dlName}</p>
                </div>
              ) : file ? (
                <div className="file-row">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
                    stroke="#9F0712" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  <div className="file-meta">
                    <span className="file-name">{file.name}</span>
                    <span className="file-size">{formatSize(file.size)}</span>
                  </div>
                  <button className="file-remove" onClick={e => { e.stopPropagation(); reset() }}
                    aria-label="Xoá">✕</button>
                </div>
              ) : (
                <div className="zone-prompt">
                  <div className="zone-icon">
                    <svg viewBox="0 0 80 64" fill="none" width="80" height="64">
                      <rect x="8" y="16" width="44" height="40" rx="4" fill="#fff"
                        stroke="#e5e7eb" strokeWidth="1.5" />
                      <rect x="16" y="8" width="44" height="40" rx="4" fill="#fff"
                        stroke="#e5e7eb" strokeWidth="1.5" />
                      <rect x="24" y="0" width="44" height="40" rx="4" fill="#fff"
                        stroke="#ddd" strokeWidth="1.5" />
                      <text x="30" y="25" fontSize="11" fontWeight="700"
                        fill="#9F0712" fontFamily="sans-serif">PDF</text>
                      <circle cx="62" cy="50" r="12" fill="#9F0712" />
                      <path d="M62 44v12M56 50l6-6 6 6" stroke="#fff"
                        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                  <p className="zone-title">Thả tập tin PDF vào đây</p>
                </div>
              )}
            </div>

            {!file && phase !== 'done' && (
              <div className="or-divider"><span />HOẶC<span /></div>
            )}

            {phase !== 'done' && (
              <div className="lang-row">
                <span className="lang-label">Ngôn ngữ tài liệu:</span>
                <div className="lang-pills">
                  {LANGS.map(({ value, flag, label }) => (
                    <button key={value}
                      className={`lang-pill ${lang === value ? 'lang-pill--on' : ''}`}
                      onClick={() => setLang(value)}>
                      <span className={`fi fi-${flag}`} style={{ borderRadius: 2 }} />
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {phase !== 'done' ? (
              <button
                className={`btn-primary ${busy ? 'btn-primary--busy' : ''}`}
                disabled={busy}
                onClick={file ? convert : () => inputRef.current?.click()}
              >
                {busy ? (
                  <><span className="spinner" />Đang chuyển đổi{elapsed > 0 ? ` · ${elapsed}s` : '…'}</>
                ) : file ? 'Chuyển đổi sang Word →' : 'Tải lên để chuyển đổi'}
              </button>
            ) : (
              <div className="done-actions">
                <a className="btn-primary" href={dlUrl} download={dlName}>
                  ⬇ Tải xuống {dlName}
                </a>
                <button className="btn-secondary" onClick={reset}>
                  Chuyển file khác
                </button>
              </div>
            )}

            {!file && phase !== 'done' && (
              <p className="zone-note">
                Hỗ trợ PDF văn bản và PDF scan · Tối đa 100 MB
              </p>
            )}

            {phase === 'error' && (
              <div className="error-box">⚠ {error}</div>
            )}
          </div>
        </div>

      </div>
    </main>
  )
}
