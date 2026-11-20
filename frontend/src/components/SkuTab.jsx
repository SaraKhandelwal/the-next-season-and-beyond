import React, { useEffect, useState } from 'react'
import SizePills from './SizePills.jsx'
import { Empty } from './RivalTab.jsx'
import { api, money } from '../api.js'

export default function SkuTab({ refreshKey }) {
  const [q, setQ] = useState('')
  const [team, setTeam] = useState('All')
  const [category, setCategory] = useState('All')
  const [coreOnly, setCoreOnly] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    const t = setTimeout(() => {
      api.skus(q, team, category).then((r) => { setRes(r); setErr(null) }).catch((e) => setErr(e.message))
    }, 200)
    return () => clearTimeout(t)
  }, [q, team, category, refreshKey])

  if (err) return <div className="rounded-lg border border-line p-4 text-sm text-gray-600">Could not load SKUs: {err}</div>
  if (!res) return <p className="text-sm text-gray-500">Loading…</p>
  if (res.total === 0) return <Empty text="No public storefront products observed yet. Click “Refresh Data”." />

  const items = res.items.filter((p) => !coreOnly || p.core_stockout)
  const sel = 'rounded-md border border-line bg-white px-3 py-2 text-sm text-ink focus:border-[#704957] focus:outline-none'
  return (
    <section className="rounded-lg border border-line bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-line p-5">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, vendor, type…"
          className="min-w-[220px] flex-1 rounded-md border border-line bg-white px-3 py-2 text-sm text-ink placeholder-gray-400 focus:border-[#704957] focus:outline-none" />
        <select value={team} onChange={(e) => setTeam(e.target.value)} className={sel}>
          <option value="All">All teams</option>
          {res.teams.map((t) => <option key={t}>{t}</option>)}
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} className={sel}>
          <option value="All">All categories</option>
          {res.categories.map((c) => <option key={c}>{c}</option>)}
        </select>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-600">
          <input type="checkbox" checked={coreOnly} onChange={(e) => setCoreOnly(e.target.checked)} className="accent-[#704957]" />
          M/L listed unavailable only
        </label>
        <span className="text-xs text-gray-500">{items.length} of {res.total}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-left">
          <thead>
            <tr className="text-[11px] uppercase tracking-wider text-gray-400">
              {['', 'Product', 'Team', 'Category', 'Price', 'Sizes', 'Store'].map((h) => <th key={h} className="px-4 py-2">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.shopify_id} className="border-t border-line hover:bg-gray-50">
                <td className="px-4 py-2">
                  {p.image_url ? <img src={p.image_url} alt="" loading="lazy" className="h-12 w-12 rounded object-cover" /> : <div className="h-12 w-12 rounded bg-gray-100" />}
                </td>
                <td className="max-w-sm px-4 py-2">
                  <p className="line-clamp-2 text-sm font-medium text-ink">{p.title}</p>
                  <p className="text-[11px] text-gray-500">{p.vendor}{p.core_stockout && <span className="ml-2 rounded border border-line px-1.5 py-0.5 font-semibold text-gray-600">M/L unavailable</span>}</p>
                </td>
                <td className="px-4 py-2 text-sm text-gray-600">{p.team}</td>
                <td className="px-4 py-2 text-sm text-gray-600">{p.category}</td>
                <td className="px-4 py-2 text-sm font-semibold tabular-nums text-ink">{money(p.retail_price)}</td>
                <td className="px-4 py-2"><SizePills sizes={p.sizes} /></td>
                <td className="px-4 py-2">
                  <a href={p.product_url} target="_blank" rel="noreferrer" className="text-sm font-medium text-[#704957] hover:underline">Open ↗</a>
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-500">No SKUs match.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}
