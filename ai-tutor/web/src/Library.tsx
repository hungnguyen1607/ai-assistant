import { useEffect, useMemo, useState } from 'react'
import { api, type Problem, type ProblemSummary } from './api'
import { Markdown } from './Markdown'

const SELECTED_KEY = (course: string) => `tutor-problem-${course}`

export function Library({
  course,
  refreshKey,
  active,
  onAsk,
}: {
  course: string
  refreshKey: number
  active: boolean
  onAsk: (text: string) => void
}) {
  const [list, setList] = useState<ProblemSummary[]>([])
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const saved = localStorage.getItem(SELECTED_KEY(course))
    return saved ? Number(saved) : null
  })
  const [problem, setProblem] = useState<Problem | null>(null)

  useEffect(() => {
    api.problems(course).then(setList).catch(() => setList([]))
  }, [course, refreshKey])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return list
    return list.filter((p) =>
      `${p.section} #${p.number} ${p.section}.${p.number} ${p.title} ${p.answer}`.toLowerCase().includes(q),
    )
  }, [list, query])

  useEffect(() => {
    if (!filtered.length) return
    if (selectedId === null || !list.some((p) => p.id === selectedId)) setSelectedId(filtered[0].id)
  }, [filtered, list, selectedId])

  useEffect(() => {
    if (selectedId === null) return setProblem(null)
    localStorage.setItem(SELECTED_KEY(course), String(selectedId))
    api.problem(selectedId).then(setProblem).catch(() => setProblem(null))
  }, [selectedId, course, refreshKey])

  const index = filtered.findIndex((p) => p.id === selectedId)
  const go = (delta: number) => {
    const next = filtered[index + delta]
    if (next) setSelectedId(next.id)
  }

  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowRight' || e.key === 'j') go(1)
      if (e.key === 'ArrowLeft' || e.key === 'k') go(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  async function remove() {
    if (!problem || !confirm(`Delete ${problem.section} #${problem.number} from the library? (The .md file stays.)`)) return
    await api.deleteProblem(problem.id)
    setSelectedId(filtered[index + 1]?.id ?? filtered[index - 1]?.id ?? null)
    setList((l) => l.filter((p) => p.id !== problem.id))
  }

  const grouped = useMemo(() => {
    const out: { chapter: string; sections: { section: string; items: ProblemSummary[] }[] }[] = []
    for (const p of filtered) {
      let ch = out.find((c) => c.chapter === p.chapter)
      if (!ch) out.push((ch = { chapter: p.chapter, sections: [] }))
      let sec = ch.sections.find((s) => s.section === p.section)
      if (!sec) ch.sections.push((sec = { section: p.section, items: [] }))
      sec.items.push(p)
    }
    return out
  }, [filtered])

  return (
    <div className="flex h-full min-w-0 flex-1">
      <div className="line-right w-72 shrink-0 overflow-y-auto px-3 py-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search: 2.2, #6, ln"
          style={{ width: '100%', boxSizing: 'border-box' }}
        />
        <div>
          <small>
            {filtered.length} of {list.length} problems
          </small>
        </div>
        {list.length === 0 && <p>Nothing saved yet. Ask the tutor to solve some textbook problems.</p>}
        {grouped.map((ch) => (
          <div key={ch.chapter}>
            <p style={{ marginBottom: 0 }}>
              <b>{/^\d+$/.test(ch.chapter) ? `Chapter ${ch.chapter}` : ch.chapter}</b>
            </p>
            {ch.sections.map((sec) => (
              <div key={sec.section}>
                <div>Section {sec.section}</div>
                <ul className="plain">
                  {sec.items.map((p) => (
                    <li key={p.id}>
                      {p.id === selectedId ? (
                        <b>
                          #{p.number} {p.title}
                        </b>
                      ) : (
                        <button className="link" onClick={() => setSelectedId(p.id)}>
                          #{p.number} {p.title}
                        </button>
                      )}
                      {p.verified && ' ✓'}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="min-w-0 flex-1 overflow-y-auto px-6">
        {problem ? (
          <div className="max-w-3xl">
            <p>
              <small>
                {course.toUpperCase()} · Section {problem.section} · Problem {problem.number}
              </small>
            </p>
            <h2>{problem.title}</h2>
            <p>
              <button onClick={() => go(-1)} disabled={index <= 0}>
                ← Prev
              </button>{' '}
              <button onClick={() => go(1)} disabled={index === -1 || index >= filtered.length - 1}>
                Next →
              </button>{' '}
              <small>(or use the arrow keys)</small>
            </p>
            <p>
              {problem.verified ? 'Verified with SymPy ✓' : 'Not machine-verified'}
              {problem.source && <> · Source: {problem.source}</>}
            </p>

            {problem.statement !== problem.title && (
              <>
                <h3>Problem</h3>
                <Markdown>{problem.statement}</Markdown>
              </>
            )}

            {problem.answer && (
              <>
                <h3>Answer</h3>
                <p>
                  <code>{problem.answer}</code>
                </p>
              </>
            )}

            <h3>Solution</h3>
            <Markdown>{problem.solution}</Markdown>

            <hr />
            <p>
              <button onClick={() => onAsk(`Explain ${problem.section} #${problem.number} step by step`)}>
                Explain this in chat
              </button>{' '}
              <button onClick={() => onAsk(`Give me a similar problem to ${problem.section} #${problem.number} to try myself`)}>
                Give me a similar one
              </button>{' '}
              <button onClick={remove}>Delete</button>
            </p>
          </div>
        ) : (
          <p>Pick a problem on the left.</p>
        )}
      </div>
    </div>
  )
}
