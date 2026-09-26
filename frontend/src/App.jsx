import { useEffect, useState } from 'react'
import './styles.css'

export default function App() {
  const [username, setUsername] = useState('printer')
  const [password, setPassword] = useState('print123456')
  const [token, setToken] = useState(localStorage.getItem('print_token') || '')
  const [role, setRole] = useState(localStorage.getItem('print_role') || '')
  const [view, setView] = useState('jobs')

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

  function leave() {
    localStorage.clear()
    setToken('')
    setRole('')
    setView('jobs')
  }

  if (!token) {
    return (
      <main className="login">
        <h1>印刷套准复核台</h1>
        <p>提交后接口只入队。另一进程领走偏差并写结论，页面轮询到结论出现。</p>
        <input value={username} onChange={(e) => setUsername(e.target.value)} />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <button onClick={enter}>登录</button>
        <p>printer / print123456 可送复核、改允差；checker / check123456 只看</p>
      </main>
    )
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <h2>复核台</h2>
        <nav>
          <button className={view === 'jobs' ? 'active' : ''} onClick={() => setView('jobs')}>
            复核队列
          </button>
          <button className={view === 'tolerance' ? 'active' : ''} onClick={() => setView('tolerance')}>
            允差档
          </button>
        </nav>
        <div className="sidebar-foot">
          <span>{role === 'writer' ? '印刷员 printer' : '只读 checker'}</span>
          <button onClick={leave}>退出</button>
        </div>
      </aside>
      <main className="content">
        {view === 'jobs' ? <JobsView api={api} role={role} /> : <ToleranceView api={api} role={role} />}
      </main>
    </div>
  )
}

function JobsView({ api, role }) {
  const [rows, setRows] = useState([])
  const [sheet, setSheet] = useState('插页-02')
  const [cyan, setCyan] = useState('0.12')
  const [magenta, setMagenta] = useState('0.02')
  const [error, setError] = useState('')

  async function load() {
    setRows(await api('/api/jobs'))
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 1000)
    return () => clearInterval(timer)
  }, [])

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

  return (
    <>
      <h1>复核队列</h1>
      {role === 'writer' && (
        <p className="send-bar">
          <input value={sheet} onChange={(e) => setSheet(e.target.value)} />
          <input value={cyan} onChange={(e) => setCyan(e.target.value)} />
          <input value={magenta} onChange={(e) => setMagenta(e.target.value)} />
          <button onClick={send}>送复核</button>
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr><th>印张</th><th>青（毫米）</th><th>品（毫米）</th><th>状态</th><th>结论</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.sheet}</td>
              <td>{row.cyan_mm}</td>
              <td>{row.magenta_mm}</td>
              <td>{row.status}</td>
              <td className={row.verdict === '套准' ? 'ok' : row.verdict === '套不准' ? 'bad' : ''}>
                {row.verdict || '等待'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function ToleranceView({ api, role }) {
  const [current, setCurrent] = useState(null)
  const [history, setHistory] = useState([])
  const [value, setValue] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function load() {
    const [cur, hist] = await Promise.all([api('/api/tolerance'), api('/api/tolerance/history')])
    setCurrent(cur)
    setHistory(hist)
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 1000)
    return () => clearInterval(timer)
  }, [])

  async function save() {
    setMessage('')
    setError('')
    try {
      const cur = await api('/api/tolerance', {
        method: 'PUT',
        body: JSON.stringify({ tolerance_mm: Number(value) }),
      })
      setCurrent(cur)
      setValue('')
      setMessage('已改档，新档作用于改档之后领取的任务')
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <h1>允差档</h1>
      <section className="card">
        <h3>现行允差</h3>
        {current && (
          <p className="current">
            <strong>{current.tolerance_mm}</strong> 毫米
            <span className="meta">
              最近改档：{current.updated_by} · {new Date(current.updated_at).toLocaleString('zh-CN')}
            </span>
          </p>
        )}
        <p className="hint">
          判定规则：独立领取进程在领取一条任务的瞬间读取此刻允差，并把该允差记在这条任务上；
          青、品两色偏差的绝对值都不大于记下的允差才写“套准”，否则写“套不准”。
          改档只影响改档之后被领取的新队；正在领取中、已写结论的任务继续使用领取瞬间记下的允差，结论不变。
        </p>
        {role === 'writer' ? (
          <p className="send-bar">
            <input
              type="number"
              step="0.01"
              min="0"
              placeholder="新允差（毫米）"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button onClick={save}>改档</button>
          </p>
        ) : (
          <p className="hint">只读账号可查看允差与结论，不能改档，也不能送队。</p>
        )}
        {message && <p className="ok-text">{message}</p>}
        {error && <p className="error">{error}</p>}
      </section>
      <section className="card">
        <h3>最近改档记录</h3>
        <table>
          <thead>
            <tr><th>允差（毫米）</th><th>改档人</th><th>时间</th></tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id}>
                <td>{h.tolerance_mm}</td>
                <td>{h.changed_by}</td>
                <td>{new Date(h.changed_at).toLocaleString('zh-CN')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
