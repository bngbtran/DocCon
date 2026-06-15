import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Nav  from './Nav.jsx'
import Home from './Home.jsx'

function Footer() {
  return (
    <footer className="footer">
      © 2026 DocCon · Powered by PyMuPDF &amp; EasyOCR
    </footer>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="page">
        <Nav />
        <Routes>
          <Route path="/" element={<Home />} />
        </Routes>
        <Footer />
      </div>
    </BrowserRouter>
  )
}
