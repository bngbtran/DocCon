import { Link } from 'react-router-dom'

export default function Nav() {
  return (
    <nav className="nav">
      <div className="nav-inner">
        <Link to="/" className="nav-logo" style={{ textDecoration: 'none' }}>
          <img src="/logo.png" alt="DocCon" className="nav-logo-img" />
          <span className="nav-logo-name">DocCon</span>
        </Link>
        <div className="nav-right">
          <span className="nav-credit">Phát triển bởi: <a href="mailto:tranbnb.2004@gmail.com" className="nav-credit-link">TranBNB</a></span>
        </div>
      </div>
    </nav>
  )
}
