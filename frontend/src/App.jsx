import { useEffect, useState } from 'react'
import './style.css'

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export default function App() {
  const [username, setUsername] = useState('printer')
  const [password, setPassword] = useState('print123456')
  const [token, setToken] = useState(localStorage.getItem('print_token') || '')
  const [role, setRole] = useState(localStorage.getItem('print_role') || '')
  const [rows, setRows] = useState([])
  const [tol, setTol] = useState(null)
  const [sheet, setSheet] = useState('插页-02')
  const [cyan, setCyan] = useState('0.12')
  const [magenta, setMagenta] = useState('0.02')
  const [newTol, setNewTol] = useState('')
  const [tolReason, setTolReason] = useState('')
  const [error, setError] = useState('')

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function load() {
    const [jobs, tolerance] = await Promise.all([api('/api/jobs'), api('/api/tolerance')])
    setRows(jobs)
    setTol(tolerance)
  }

  useEffect(() => {
    if (!token) return
    load()
    const timer = setInterval(load, 1000)
    return () => clearInterval(timer)
  }, [token])

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    localStorage.setItem('print_token', data.access_token)
    localStorage.setItem('print_role', data.role)
    setToken(data.access_token)
    setRole(data.role)
  }

  async function send() {
    setError('')
    try {
      await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({
          sheet,
          cyan_mm: Number(cyan),
          magenta_mm: Number(magenta),
        }),
      })
    } catch (err) {
      setError(err.message)
    }
  }

  async function changeTolerance() {
    setError('')
    const value = Number(newTol)
    if (!(value > 0)) {
      setError('允差需为正数（毫米）')
      return
    }
    try {
      await api('/api/tolerance', {
        method: 'POST',
        body: JSON.stringify({ tolerance_mm: value, reason: tolReason }),
      })
      setNewTol('')
      setTolReason('')
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  function leave() {
    localStorage.clear()
    setToken('')
    setRole('')
  }

  if (!token) {
    return (
      <main>
        <h1>印刷套准复核台</h1>
        <p>提交后接口只入队。另一进程领走偏差并写结论，页面轮询到结论出现。</p>
        <input value={username} onChange={(e) => setUsername(e.target.value)} />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <button onClick={enter}>登录</button>
        <p>printer / print123456 可送复核与维护允差；checker / check123456 只看</p>
      </main>
    )
  }

  return (
    <main>
      <h1>印刷套准复核台 <button onClick={leave}>退出</button></h1>
      <div className="layout">
        <section className="sheet-table">
          {role === 'writer' && (
            <p>
              <input value={sheet} onChange={(e) => setSheet(e.target.value)} />
              <input value={cyan} onChange={(e) => setCyan(e.target.value)} />
              <input value={magenta} onChange={(e) => setMagenta(e.target.value)} />
              <button onClick={send}>送复核</button>
            </p>
          )}
          {error && <p className="error">{error}</p>}
          <table>
            <thead>
              <tr><th>印张</th><th>青(mm)</th><th>品(mm)</th><th>状态</th><th>结论</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.sheet}</td>
                  <td>{row.cyan_mm}</td>
                  <td>{row.magenta_mm}</td>
                  <td>{row.status}</td>
                  <td
                    className={row.verdict === '套准' ? 'verdict-ok' : row.verdict === '套不准' ? 'verdict-bad' : ''}
                    title={row.reason}
                  >
                    {row.verdict || '等待'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <aside className="sidebar">
          <h2>青品允差档</h2>
          {tol?.current && (
            <>
              <div className="current-tol">
                {tol.current.tolerance_mm}
                <small> 毫米（现行）</small>
              </div>
              <p className="tol-note">
                独立领取进程在领走任务的瞬间读取此刻允差，并把该档记在任务上：
                青、品偏差绝对值都不大于它才写“套准”，否则写“套不准”。
                正在领取中的任务继续沿用领取瞬间记下的允差；改档只影响尚未领取的新队。
              </p>
              {role === 'writer' ? (
                <div className="tol-form">
                  <input
                    className="num"
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="新允差(毫米)"
                    value={newTol}
                    onChange={(e) => setNewTol(e.target.value)}
                  />
                  <input
                    placeholder="改档说明（可选）"
                    value={tolReason}
                    onChange={(e) => setTolReason(e.target.value)}
                  />
                  <button onClick={changeTolerance}>改档</button>
                </div>
              ) : (
                <p className="readonly-hint">只读账号：可见允差与改档记录，不能改档，也不能送复核。</p>
              )}
              <h2 style={{ marginTop: 14 }}>最近改档记录</h2>
              <ul className="revisions">
                {tol.revisions.map((rev) => (
                  <li key={rev.id}>
                    <span className="rev-val">{rev.tolerance_mm} 毫米</span>
                    {' — '}
                    <span className="rev-meta">
                      {rev.changed_by} · {fmtTime(rev.changed_at)}
                      {rev.reason ? ` · ${rev.reason}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </div>
    </main>
  )
}
