import { useEffect, useRef, useState } from 'react'

/* Small shared pieces of motion and charting. Everything animates once on arrival and respects
   prefers-reduced-motion (the count-up jumps straight to the value, the bars simply appear). */

const reduced = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** A number that counts up to its value when it first appears or changes. */
export function useCountUp(target: number, ms = 800): number {
  const [v, setV] = useState(reduced() ? target : 0)
  const from = useRef(0)
  useEffect(() => {
    if (reduced()) { setV(target); return }
    const a = from.current
    const t0 = performance.now()
    let raf = 0
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms)
      const e = 1 - Math.pow(1 - k, 3)
      setV(a + (target - a) * e)
      if (k < 1) raf = requestAnimationFrame(step); else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}

export function Num({ v, dp = 0, suffix = '' }: { v: number; dp?: number; suffix?: string }) {
  const x = useCountUp(v)
  return <>{x.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}{suffix}</>
}

const TWIN_LABEL: Record<string, string> = {
  HOLD: 'Hold everything', DIVERT: 'Divert long-distance, hold locals', DIVERT_SINGLE: 'Divert + locals single-line',
}

/** The digital twin's answer for one closure: extra passenger-hours of delay under each response. */
export function TwinBars({ hours, best, compact = false }: {
  hours: Record<'HOLD' | 'DIVERT' | 'DIVERT_SINGLE', number>; best?: string; compact?: boolean
}) {
  const keys = ['HOLD', 'DIVERT', 'DIVERT_SINGLE'] as const
  const max = Math.max(1, ...keys.map(k => hours[k]))
  return (
    <div className={`twin-bars ${compact ? 'compact' : ''}`}>
      {keys.map((k, i) => (
        <div key={k} className={`tb-row ${best === k ? 'best' : ''}`}>
          <span className="tb-l">{TWIN_LABEL[k]}</span>
          <div className="tb-t"><i style={{ width: `${Math.max(2, (hours[k] / max) * 100)}%`, animationDelay: `${i * 90}ms` }} /></div>
          <span className="tb-v">{hours[k].toLocaleString()} h</span>
        </div>
      ))}
    </div>
  )
}
