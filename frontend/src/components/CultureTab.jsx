import React from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import SizePills from './SizePills.jsx'
import { Empty } from './RivalTab.jsx'
import { chartText, fmtTime, gridStroke, money, tooltipStyle } from '../api.js'

const LEVEL = {
  critical: ['border-[#704957] bg-[#704957] text-white', 'Critical'],
  elevated: ['border-[#704957] text-[#704957]', 'Elevated'],
  watch: ['border-line text-gray-600', 'Watch'],
  none: ['border-line text-gray-600', 'No cold snap'],
  unknown: ['border-line text-gray-400', 'No data'],
}

function Stat({ label, value, sub }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-[#704957]">{value}</p>
      {sub && <p className="text-xs text-gray-500">{sub}</p>}
    </div>
  )
}

export default function CultureTab({ data }) {
  const { weather, readiness: r, news, momentum } = data
  const [badge, label] = LEVEL[r.level]
  const chart = weather.map((d) => ({ ...d, day: new Date(d.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' }) }))

  return (
    <div className="grid gap-8 lg:grid-cols-[1.3fr_1fr]">
      <div className="space-y-8">
        <section className="rounded-lg border border-line bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-base font-bold text-ink">Indianapolis 14-Day Forecast</h3>
              <p className="text-sm text-gray-500">A cold day is a low under {r.threshold_f}°F</p>
            </div>
            <span className={`rounded border px-3 py-1 text-xs font-semibold ${badge}`}>Review status: {label}</span>
          </div>
          {weather.length === 0 ? <div className="mt-5"><Empty text="No forecast yet. Click “Refresh Data”." /></div> : (
            <div className="mt-5 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chart} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                  <CartesianGrid stroke={gridStroke} vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: chartText, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis unit="°" tick={{ fill: chartText, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip {...tooltipStyle} formatter={(v, n) => [`${v}°F`, n]} />
                  <ReferenceLine y={r.threshold_f} stroke="#704957" strokeDasharray="5 4"
                    label={{ value: `${r.threshold_f}°F`, fill: '#6B7280', fontSize: 11, position: 'insideTopRight' }} />
                  <Area dataKey="high_f" name="High" stroke="#9CA3AF" fill="rgba(156,163,175,0.12)" strokeWidth={2} />
                  <Line dataKey="low_f" name="Low" stroke="#704957" strokeWidth={2.5}
                    dot={(p) => <circle key={p.index} cx={p.cx} cy={p.cy} r={p.payload.low_f < r.threshold_f ? 5 : 3} fill="#704957" stroke="none" />} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="rounded-lg border border-line bg-white p-6">
          <h3 className="text-base font-bold text-ink">Fleece &amp; Outerwear Readiness</h3>
          <p className="mb-6 text-sm text-gray-500">Hoodies, crews, fleece and jackets with M or L publicly listed as unavailable</p>
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <Stat label="M/L unavailable" value={r.stockout_pct == null ? '—' : `${r.stockout_pct}%`} sub={`${r.skus_out} of ${r.skus_tracked} styles`} />
            <Stat label="Cold days" value={r.cold_days} sub={`of ${weather.length} forecast`} />
            <Stat label="Coldest low" value={r.coldest ? `${Math.round(r.coldest.low_f)}°F` : '—'} sub={r.coldest?.date} />
            <Stat label="First cold day" value={r.first_cold_day ? r.first_cold_day.slice(5) : '—'} />
          </div>
          <ul className="mt-6 divide-y divide-line">
            {r.out_of_stock.map((p) => (
              <li key={p.url} className="flex items-center gap-3 py-3">
                {p.image_url ? <img src={p.image_url} alt="" loading="lazy" className="h-10 w-10 rounded object-cover" /> : <div className="h-10 w-10 rounded bg-gray-100" />}
                <a href={p.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-sm text-ink hover:text-[#704957] hover:underline">{p.title}</a>
                <span className="text-xs text-gray-500">{money(p.price)}</span>
                <SizePills sizes={p.sizes} />
              </li>
            ))}
            {r.out_of_stock.length === 0 && <li className="py-3 text-sm text-gray-500">No M/L unavailability observed in this collected sample.</li>}
          </ul>
        </section>
      </div>

      <section className="rounded-lg border border-line bg-white">
        <div className="border-b border-line px-6 py-5">
          <h3 className="text-base font-bold text-ink">Tunnel-Fit &amp; Merch Press</h3>
          <p className="text-sm text-gray-500">Last 30 days · {momentum.last_7d} stories this week</p>
        </div>
        <ul className="max-h-[820px] divide-y divide-line overflow-y-auto">
          {news.map((n) => (
            <li key={n.link} className="px-6 py-4">
              <a href={n.link} target="_blank" rel="noreferrer" className="text-sm font-medium text-ink hover:text-[#704957] hover:underline">{n.title}</a>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
                {n.source && <span>{n.source}</span>}
                {n.published_at && <span>· {fmtTime(n.published_at)}</span>}
                {n.tags.map((t) => <span key={t} className="rounded border border-line px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">{t}</span>)}
              </div>
            </li>
          ))}
          {news.length === 0 && <li className="p-6"><Empty text="No headlines yet. Click “Refresh Data”." /></li>}
        </ul>
      </section>
    </div>
  )
}
