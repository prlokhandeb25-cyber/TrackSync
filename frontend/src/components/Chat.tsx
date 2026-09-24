import { useEffect, useRef, useState } from 'react'
import { api, type ChatAnswer } from '../api'
import type { FocusReq } from './NetworkMap'
import ChatVisualView from './ChatVisual'

/* The assistant reads live state and answers from it. No language model is involved, which is
   the point: every figure it quotes is read from the same objects the planner and the map use,
   so it cannot invent one. The `trace` line under each answer names what it read. */

export function MitraIcon() {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="6" y="4" width="20" height="21" rx="6" fill="#fff" />
      <rect x="9" y="8" width="14" height="8" rx="2.5" fill="#0e2a47" />
      <circle cx="13" cy="12" r="1.7" fill="#7dd3fc" />
      <circle cx="19" cy="12" r="1.7" fill="#7dd3fc" />
      <path d="M13 19.2c1.7 1.6 4.3 1.6 6 0" stroke="#e8912d" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="11" cy="22" r="1.3" fill="#f59e0b" />
      <circle cx="21" cy="22" r="1.3" fill="#f59e0b" />
      <path d="M9 27l-2 2.5M23 27l2 2.5" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      <path d="M16 4V1.5" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      <circle cx="16" cy="1.6" r="1.5" fill="#f59e0b" />
    </svg>
  )
}

interface Turn { role: 'user' | 'bot'; text: string; answer?: ChatAnswer }

const OPENING: Turn = {
  role: 'bot',
  text: "Namaste! I'm RailMitra. I know every feature here — planning, sudden tasks, early warnings, the digital twin, "
    + "rerouting, job grouping — and I can run any of them on a copy of the schedule and show you the result. "
    + "No language model, and nothing I try changes the real plan. Ask *what can you do?* to start.",
}

const STARTERS = [
  'What can you do?',
  'What if we act on early warnings at 50% risk?',
  'What is the best response if Dadar to Matunga is closed at 9am?',
  'How are trains rerouted around a block?',
  'What if a critical S&T fault at Kurla right now?',
  'Compare the two ways of grouping jobs',
]

function render(raw: string) {
  // Bold and italic, so the backend can emphasise the figures that matter and footnote its method.
  const text = raw.replace(/^- /gm, '•  ')
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') && p.length > 4
      ? <b key={i}>{p.slice(2, -2)}</b>
      : p.startsWith('*') && p.endsWith('*') && p.length > 2
        ? <i key={i} className="muted">{p.slice(1, -1)}</i>
        : <span key={i}>{p}</span>)
}

export default function Chat({ atS = 0, onShow }: {
  atS?: number
  onShow?: (section: string, startS?: number, extra?: Partial<FocusReq>) => void
}) {
  const [turns, setTurns] = useState<Turn[]>([OPENING])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns])

  const ask = async (text: string) => {
    const question = text.trim()
    if (!question || busy) return
    setTurns(t => [...t, { role: 'user', text: question }])
    setQ('')
    setBusy(true)
    try {
      const a = await api.chat(question, atS)
      setTurns(t => [...t, { role: 'bot', text: a.text, answer: a }])
    } catch {
      setTurns(t => [...t, { role: 'bot', text: 'I could not reach the planner just then.' }])
    } finally {
      setBusy(false)
    }
  }

  const last = turns[turns.length - 1]
  const suggestions = last?.role === 'bot' && last.answer?.suggestions?.length
    ? last.answer.suggestions
    : turns.length <= 1 ? STARTERS : []

  return (
    <div className="panel chat">
      <div className="panel-head mitra-head">
        <div className="mitra-avatar"><MitraIcon /></div>
        <div>
          <h2>RailMitra</h2>
          <span className="sub" style={{ marginLeft: 0, textAlign: 'left', display: 'block' }}>
            live analysis · no LLM
          </span>
        </div>
      </div>

      <div className="chat-log" ref={logRef}>
        {turns.map((t, i) => (
          t.role === 'user'
            ? <div key={i} className="msg user">{t.text}</div>
            : (
              <div key={i} className="msg bot">
                <div className="bubble">
                  {render(t.text)}
                  {t.answer?.visual ? <ChatVisualView v={t.answer.visual} /> : null}
                  {(t.answer?.visuals ?? []).map((vv, k) => <ChatVisualView key={k} v={vv} />)}
                  {t.answer?.facts?.length ? (
                    <div className="chips">
                      {t.answer.facts.map((f, k) => (
                        <span key={k} className="chip">{f.k} <b>{f.v}</b></span>
                      ))}
                    </div>
                  ) : null}
                  {t.answer?.action?.section && onShow ? (
                    <button className="action chat-go" onClick={() => onShow(t.answer!.action!.section!, t.answer!.action!.start_s, {
                      label: 'What-if slot', id: undefined })}>{t.answer.action.label} →</button>
                  ) : null}
                  {t.answer?.trace?.length ? (
                    <div className="trace">read: {t.answer.trace.join(' · ')}</div>
                  ) : null}
                </div>
              </div>
            )
        ))}
        {busy && <div className="msg bot"><div className="bubble muted">working it out on a copy of the schedule…</div></div>}
      </div>

      {suggestions.length > 0 && (
        <div className="suggests">
          {suggestions.slice(0, 4).map(s => (
            <button key={s} onClick={() => ask(s)}>{s}</button>
          ))}
        </div>
      )}

      <form className="chat-input" onSubmit={e => { e.preventDefault(); ask(q) }}>
        <input value={q} onChange={e => setQ(e.target.value)}
               placeholder="Ask, or try a what-if…" disabled={busy} />
        <button className="action primary" type="submit" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </div>
  )
}
