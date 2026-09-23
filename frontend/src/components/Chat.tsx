import { useEffect, useRef, useState } from 'react'
import { api, type ChatAnswer } from '../api'

/* The assistant reads live state and answers from it. No language model is involved, which is
   the point: every figure it quotes is read from the same objects the planner and the map use,
   so it cannot invent one. The `trace` line under each answer names what it read. */

interface Turn { role: 'user' | 'bot'; text: string; answer?: ChatAnswer }

const OPENING: Turn = {
  role: 'bot',
  text: "Ask me about the network and I'll answer from the live plan. I'm not a language model — "
    + "every number I give you is read out of the same objects the solver and the map use, so I "
    + "can't make one up. The line under each answer shows what I read.",
}

const STARTERS = [
  'Which sections are not fit?',
  "Why can't S&T work on NRL-BVS?",
  'Show me the department conflicts',
  'How many gaps between trains are there?',
  'How does the RL dispatcher compare with CP-SAT?',
  'How many blocks are planned for Tuesday?',
]

function render(text: string) {
  // Minimal bold support so the backend can emphasise the figures that matter.
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**')
      ? <b key={i}>{p.slice(2, -2)}</b>
      : <span key={i}>{p}</span>)
}

export default function Chat() {
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
      const a = await api.chat(question)
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
      <div className="panel-head">
        <h2>Ask the planner</h2>
        <span className="sub">grounded in live state · no LLM</span>
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
               placeholder="e.g. why can't OWD work at Kurla?" disabled={busy} />
        <button className="action primary" type="submit" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </div>
  )
}
