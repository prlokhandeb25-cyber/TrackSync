import { useEffect, useRef, useState } from 'react'
import { api, type ChatAnswer } from '../api'
import type { FocusReq } from './NetworkMap'

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
  text: "Namaste! I'm RailMitra. Ask me what would happen — a job, a closure, two kinds of work sharing a "
    + "place — and I run the real gap finder, rule engine and passenger model on a copy of the schedule. "
    + "No language model, and nothing I try changes the plan. The line under each answer shows what I read.",
}

const STARTERS = [
  'What if a 60 minute PWI job at Dadar to Matunga?',
  'What if Dadar to Matunga is closed at 14:00 for an hour?',
  'Can OHE insulator work and tamping happen together at Kurla?',
  'Best time for a 45 minute S&T job at Thane',
  'How busy is Thane at 9am?',
  "Why can't S&T work on NRL-BVS?",
]

function render(text: string) {
  // Minimal bold support so the backend can emphasise the figures that matter.
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <b key={i}>{p.slice(2, -2)}</b>
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
        {busy && <div className="msg bot"><div className="bubble muted">thinking…</div></div>}
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
