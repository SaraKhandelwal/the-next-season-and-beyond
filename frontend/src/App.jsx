import React, { useCallback, useEffect, useRef, useState } from 'react'
import Header from './components/Header.jsx'
import ExecBrief from './components/ExecBrief.jsx'
import RivalTab from './components/RivalTab.jsx'
import RedditTab from './components/RedditTab.jsx'
import CultureTab from './components/CultureTab.jsx'
import SkuTab from './components/SkuTab.jsx'
import { api } from './api.js'

const TABS = [
  ['rival', 'Compare Public Storefronts'],
  ['reddit', 'Merchandise Media Attention'],
  ['culture', 'Fashion News & Indy Weather'],
  ['sku', 'Public Product Library'],
]

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  const [tab, setTab] = useState('rival')
  const [refreshKey, setRefreshKey] = useState(0)
  const esRef = useRef(null)

  const load = useCallback(async () => {
    try { setData(await api.overview()); setError(null); setRefreshKey((k) => k + 1) }
    catch (e) { setError(e.message) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => () => esRef.current?.close(), [])

  function attach() {
    esRef.current?.close()
    const es = new EventSource('/api/refresh/stream')
    esRef.current = es
    es.onmessage = (e) => {
      const s = JSON.parse(e.data)
      setProgress(s)
      if (!s.running) { es.close(); load() }
    }
    es.onerror = () => {
      es.close()
      setProgress((p) => ({ ...(p || {}), running: false, error: 'Lost connection to the progress stream.' }))
    }
  }

  async function refresh() {
    setProgress({ running: true, step: 'Starting live sync…', pct: 2, elapsed: 0 })
    try {
      const res = await api.startRefresh()
      if (!res.ok && res.status !== 409) throw new Error(`Refresh request failed (${res.status})`)
      attach()
    } catch (e) {
      setProgress({ running: false, error: e.message })
    }
  }

  return (
    <div className="min-h-screen bg-white">
      <Header progress={progress} onRefresh={refresh} lastRun={data?.last_run} isStatic={data?.__static} capturedAt={data?.__captured_at} />
      <main className="mx-auto max-w-7xl space-y-12 px-6 py-10">
        {error && <div className="rounded-lg border border-line p-4 text-sm text-gray-600">Could not load data: {error}</div>}
        {data && data.pse_sku_count === 0 && !progress?.running && (
          <div className="rounded-lg border border-dashed border-line p-10 text-center">
            <p className="text-lg font-semibold text-ink">No data yet</p>
            <p className="mt-1 text-sm text-gray-500">No public storefront snapshot has been collected yet. On GitHub Pages, run the scheduled GitHub Actions refresh workflow.</p>
          </div>
        )}
        {data && <ExecBrief cards={data.brief} />}

        <div className="space-y-8">
          <nav className="flex flex-wrap gap-x-2 border-b border-line">
            {TABS.map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`-mb-px border-b-2 px-4 py-3 text-sm font-semibold transition ${
                  tab === k ? 'border-[#704957] text-[#704957]' : 'border-transparent text-gray-500 hover:text-ink'}`}>
                {label}
              </button>
            ))}
          </nav>

          {data && tab === 'rival' && <RivalTab data={data.assortment} />}
          {data && tab === 'reddit' && <RedditTab data={data.reddit} />}
          {data && tab === 'culture' && <CultureTab data={data.culture} />}
          {tab === 'sku' && <SkuTab refreshKey={refreshKey} />}
        </div>
      </main>
    </div>
  )
}
