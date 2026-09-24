import { useEffect, useState } from 'react'
import { api, type MethodsSummary } from '../api'

/* Four proposed methods, each tested against doing it without. The verdict on each card is derived from
   the numbers by fixed thresholds in the backend, not written by hand; where a result rests on an invented
   model the card says so in plain sight rather than behind a link. */

const VERDICT_TEXT: Record<string, string> = { helps: 'Helps', marginal: 'Marginal', 'trade-off': 'Trade-off', 'no gain': 'No gain' }
const fmt = (n: number) => Math.round(n).toLocaleString()
const hrs = (paxMin: number) => `${fmt(paxMin / 60)}`

function Pill({ v }: { v?: string }) {
  if (!v) return <span className="mv mv-wait">measuring…</span>
  return <span className={`mv mv-${v.replace(' ', '-')}`}>{VERDICT_TEXT[v] ?? v}</span>
}

function Card({ title, verdict, headline, children, caveat, how }: {
  title: string; verdict?: string; headline: React.ReactNode; children?: React.ReactNode; caveat?: string; how?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mcard">
      <div className="mc-head"><h3>{title}</h3><Pill v={verdict} /></div>
      <div className="mc-headline">{headline}</div>
      {children}
      {caveat && <div className="mc-caveat">{caveat}</div>}
      {how && <><button className="link" onClick={() => setOpen(o => !o)}>{open ? 'hide' : 'how measured'}</button>
        {open && <div className="cmp-how">{how}</div>}</>}
    </div>
  )
}

export default function Methods() {
  const [d, setD] = useState<MethodsSummary | null>(null)
  useEffect(() => {
    let alive = true
    const poll = () => api.methodsSummary().then(r => {
      if (!alive) return
      setD(r)
      if (r.status === 'running') setTimeout(poll, 4000)
    }).catch(() => undefined)
    void poll()
    return () => { alive = false }
  }, [])

  const R = d?.results
  const p = R?.predictive, tw = R?.twin, bd = R?.bundling, bf = R?.buffers
  const p8 = p?.predictive.find(x => Math.abs(x.p_detect - 0.8) < 1e-6)

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="ba-hero">
        <h1>Four proposed methods, tested</h1>
        <div className="sub">Each is measured against doing it without. Where a result rests on an invented model, the card says so.</div>
        {d?.status === 'running' && <div className="mc-run"><span className="spinner-sm" />Running the experiments — the slower ones take a minute or two.</div>}
        {d?.status === 'error' && <div className="mc-run bad">Could not finish: {d.error}</div>}
      </div>

      <div className="mgrid">
        <Card title="Predictive blocks (early warning)" verdict={p?.verdict}
              headline={p && p8 ? <>Emergencies <b>{p.reactive.emergencies} → {p8.emergencies}</b> of {p.failures} failures</> : 'running…'}
              caveat={p?.caveat} how={p?.how}>
          {p && p8 && (
            <>
              <div className="tiles mini">
                <div className="tile"><div className="v">{fmt(p.reactive.train_min)} → {fmt(p8.train_min)}</div><div className="k">train-minutes lost</div></div>
                <div className="tile"><div className="v">{hrs(p.reactive.pax_delay_min)} → {hrs(p8.pax_delay_min)}</div><div className="k">passenger-hours delayed</div></div>
                <div className="tile"><div className="v">{p8.prevented}/{p.failures}</div><div className="k">failures prevented</div></div>
                <div className="tile"><div className="v">{p.reactive.peak_jobs} → {p8.peak_jobs}</div><div className="k">jobs started in a peak</div></div>
              </div>
              <table className="mtable">
                <thead><tr><th>If warning works for</th><th className="num">Emergencies</th><th className="num">Train-min</th><th className="num">Prevented</th></tr></thead>
                <tbody>{p.predictive.map(r => (
                  <tr key={r.p_detect}><td>{Math.round(r.p_detect * 100)}% of failures</td><td className="num">{r.emergencies}</td>
                    <td className="num">{fmt(r.train_min)}</td><td className="num">{r.prevented}</td></tr>))}</tbody>
              </table>
            </>
          )}
        </Card>

        <Card title="Digital twin: best response to a closure" verdict={tw?.verdict}
              headline={tw ? <>The best response <b>changes with the moment</b></> : 'running…'}
              caveat={tw?.caveat} how={tw?.how}>
          {tw && (
            <table className="mtable">
              <thead><tr><th>Closure</th><th className="num">Hold</th><th className="num">Divert</th><th className="num">+ single-line</th></tr></thead>
              <tbody>{tw.cases.map(c => (
                <tr key={c.label}>
                  <td>{c.label}</td>
                  {(['HOLD', 'DIVERT', 'DIVERT_SINGLE'] as const).map(k => (
                    <td key={k} className={`num ${c.best === k ? 'best' : ''}`}>{hrs(c.policies[k].pax_min)}</td>))}
                </tr>))}</tbody>
            </table>
          )}
          {tw && <div className="hint">Extra passenger-hours of delay over the next 12 h (lower is better, best in green). A train more than 90 min late counts as cancelled and stops counting.</div>}
        </Card>

        <Card title="Multi-department bundling" verdict={bd?.verdict}
              headline={bd ? <>Protected blocks <b>{bd.blocks_before} → {bd.blocks_after}</b> over {bd.instances} weeks</> : 'running…'}
              caveat={bd?.caveat} how={bd?.how}>
          {bd && (
            <>
              <div className="tiles mini">
                <div className="tile"><div className="v">{bd.merges}</div><div className="k">extra shared blocks found</div></div>
                <div className="tile"><div className="v">{bd.held_before} → {bd.held_after}</div><div className="k">track-hours held closed</div></div>
                <div className="tile"><div className="v" style={{ color: bd.all_legal ? 'var(--fit)' : 'var(--stopstart)' }}>{bd.all_legal ? 'all legal' : 'violation'}</div><div className="k">referee on every result</div></div>
              </div>
              <div className="hint">The solver already rewards shared blocks and takes most of what is there; a second pass finds little more.</div>
            </>
          )}
        </Card>

        <Card title="Adaptive buffers (crew history)" verdict={bf?.verdict}
              headline={bf ? <>Blocks clear on time <b>{Math.round(bf.flat.mean * 100)}% → {Math.round(bf.adaptive.mean * 100)}%</b></> : 'running…'}
              caveat={bf?.caveat} how={bf?.how}>
          {bf && (
            <>
              <div className="tiles mini">
                <div className="tile"><div className="v">{bf.flat.expected_overruns} → {bf.adaptive.expected_overruns}</div><div className="k">expected overruns a week</div></div>
                <div className="tile"><div className="v">{bf.flat.placed} → {bf.adaptive.placed}</div><div className="k">jobs placed</div><div className="note">the cost of the room</div></div>
                <div className="tile"><div className="v">{bf.flat.reserved_hours} → {bf.adaptive.reserved_hours}</div><div className="k">hours of block reserved</div></div>
              </div>
              <table className="mtable">
                <thead><tr><th>Crew, weather</th><th className="num">Learned</th><th className="num">True</th></tr></thead>
                <tbody>{bf.learned.map(r => (
                  <tr key={`${r.department}${r.rain}`}><td>{r.department.replace('S_AND_T', 'S&T')}, {r.rain ? 'rain' : 'dry'}</td>
                    <td className="num">×{r.learned_mean.toFixed(2)}</td><td className="num">×{r.true_mean.toFixed(2)}</td></tr>))}</tbody>
              </table>
            </>
          )}
        </Card>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Not built</h2></div>
        <div className="panel-body">
          <ul className="limits">
            <li><b>Computer vision on drone or camera video.</b> No footage or sensor data exists here, so detection is an assumed rate (varied above), not a model. The scheduling half is real.</li>
            <li><b>Real crew logs.</b> Adaptive buffers learn from a synthetic history; real works-management logs would replace it one for one.</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
