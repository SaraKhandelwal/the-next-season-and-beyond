/** GitHub Pages reads a versioned static research snapshot. Local dev uses FastAPI when available. */
export const money = (n) => n == null ? 'Not listed' : Number(n).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
export const fmtTime = (s) => s ? new Date(s).toLocaleString('en-US', {dateStyle:'medium',timeStyle:'short'}) : 'Not yet collected'
const inStaticHosting = typeof window !== 'undefined' && window.location.hostname.endsWith('github.io')
export const isStatic = inStaticHosting
const snapshotUrl = `${import.meta.env.BASE_URL || '/'}snapshot.json`
async function json(res){if(!res.ok)throw new Error(`HTTP ${res.status}`);return res.json()}
async function loadSnapshot(){return fetch(snapshotUrl,{cache:'no-store'}).then(json)}
export const api = {
  overview: async()=>{
    if(isStatic){const x=await loadSnapshot();return {...x.overview,__static:true,__captured_at:x.captured_at,__data_available:x.data_available}}
    try {return await fetch('/api/overview',{signal:AbortSignal.timeout(1800)}).then(json)}
    catch {const x=await loadSnapshot();return {...x.overview,__static:true,__captured_at:x.captured_at,__data_available:x.data_available}}
  },
  skus: async(q='',team='All',category='All')=>{
    if(isStatic){const s=(await loadSnapshot()).skus||{items:[],total:0,categories:[],teams:[]};const rows=s.items.filter(p=>(team==='All'||p.team===team)&&(category==='All'||p.category===category)&&`${p.title} ${p.vendor} ${p.category}`.toLowerCase().includes(q.toLowerCase()));return {...s,items:rows,total:s.items.length}}
    return fetch(`/api/skus?q=${encodeURIComponent(q)}&team=${encodeURIComponent(team)}&category=${encodeURIComponent(category)}`).then(json)
  },
  startRefresh:()=>isStatic?Promise.reject(Error('Refreshing runs in GitHub Actions, not on GitHub Pages.')):fetch('/api/refresh',{method:'POST'}),
}
export const chartText='#6B7280', gridStroke='#E5E7EB'
export const tooltipStyle={contentStyle:{background:'#FFFFFF',border:'1px solid #E5E7EB',borderRadius:8,color:'#111827',fontSize:12},labelStyle:{color:'#111827',fontWeight:600}}
export const STORE_COLORS=['#704957','#A3A3A3','#54565A','#D1D5DB','#85888B']
