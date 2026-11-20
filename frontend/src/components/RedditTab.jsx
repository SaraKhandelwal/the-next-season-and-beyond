import React, { useMemo, useState } from 'react'
import { Empty } from './RivalTab.jsx'

const FILTERS = ['All', 'Player & Signature Product Coverage', 'Athlete Style & Streetwear Coverage', 'Limited-Release Coverage', 'Retro & City Design Coverage']
const input = 'rounded-md border border-line bg-white px-3 py-1.5 text-sm text-ink focus:border-[#704957] focus:outline-none'

export default function RedditTab({ data }) {
  const [cls, setCls] = useState('All')
  const [sub, setSub] = useState('All')
  const [q, setQ] = useState('')

  const subs = useMemo(() => [...new Set(data.posts.map((p) => p.subreddit))].sort(), [data.posts])
  const shown = useMemo(() => data.posts.filter((p) =>
    (cls === 'All' || p.classification === cls) &&
    (sub === 'All' || p.subreddit === sub) &&
    (!q || `${p.title} ${p.selftext}`.toLowerCase().includes(q.toLowerCase()))), [data.posts, cls, sub, q])

  if (data.posts.length === 0) return <Empty text="No merchandise news headlines yet. Click “Refresh Data”." />

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((c) => (
            <button key={c} onClick={() => setCls(c)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                cls === c ? 'border-[#704957] bg-[#704957] text-white' : 'border-line text-gray-600 hover:border-gray-400'}`}>
              {c}{c !== 'All' && <span className="ml-1 opacity-60">{data.counts[c] ?? 0}</span>}
            </button>
          ))}
          <select value={sub} onChange={(e) => setSub(e.target.value)} className={`ml-auto ${input}`}>
            <option value="All">All sources</option>
            {subs.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search headlines…" className={input} />
        </div>
        <p className="text-sm text-gray-500">{shown.length} of {data.posts.length} merchandise news headlines</p>

        <ul className="space-y-4">
          {shown.map((p) => (
            <li key={p.id} className="rounded-lg border border-line bg-white p-5">
              <a href={p.url} target="_blank" rel="noreferrer" className="font-semibold text-ink hover:text-[#704957] hover:underline">{p.title}</a>
              {p.selftext && <p className="mt-1.5 line-clamp-2 text-sm text-gray-600">{p.selftext}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                <span className="font-semibold text-ink">{p.classification}</span>
                <span>{p.subreddit}</span>
                {p.created_utc && <span>{new Date(p.created_utc * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</span>}
                <span>Found by {p.score} research quer{p.score === 1 ? 'y' : 'ies'}</span>
              </div>
            </li>
          ))}
          {shown.length === 0 && <Empty text="No headlines match these filters." />}
        </ul>
      </div>

      <aside>
        <div className="rounded-lg border border-line bg-white p-6">
          <h3 className="text-base font-bold text-ink">Media Coverage Themes</h3>
          <p className="mb-5 text-sm text-gray-500">Share of matched Google News headlines, not fan demand</p>
          <ul className="space-y-4">
            {data.themes.slice(0, 8).map((t) => (
              <li key={t.theme}>
                <div className="flex justify-between text-sm"><span className="text-ink">{t.theme}</span><span className="font-semibold text-[#704957]">{t.share_pct}%</span></div>
                <div className="mt-1.5 h-1 rounded-full bg-line"><div className="h-full rounded-full bg-[#704957]" style={{ width: `${Math.min(100, t.share_pct)}%` }} /></div>
              </li>
            ))}
            {data.themes.length === 0 && <li className="text-sm text-gray-500">No themes detected yet.</li>}
          </ul>
        </div>
      </aside>
    </div>
  )
}
