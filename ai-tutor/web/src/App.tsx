import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  type Course,
  type Outline,
  type OutlineWeek,
  type PatternSummary,
  type SolutionContent,
  type SolutionFile,
} from './api'
import { Chat } from './Chat'
import { Markdown } from './Markdown'

const SESSION_KEY = (course: string) => `tutor-session-${course}`

async function sessionFor(course: string): Promise<string> {
  const saved = localStorage.getItem(SESSION_KEY(course))
  if (saved) {
    try {
      await api.session(saved)
      return saved
    } catch {
      // server restarted; sessions live in memory
    }
  }
  const { session_id } = await api.newSession(course)
  localStorage.setItem(SESSION_KEY(course), session_id)
  return session_id
}

const isoDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const parse = (iso: string) => new Date(`${iso}T12:00:00`)
const addDays = (iso: string, n: number) => {
  const d = parse(iso)
  d.setDate(d.getDate() + n)
  return isoDate(d)
}
const daysBetween = (a: string, b: string) => Math.round((parse(b).getTime() - parse(a).getTime()) / 86400000)
const fmt = (iso: string) => parse(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

const weekKeys = (w: OutlineWeek) => (w.parts?.length ? w.parts.map((p) => `${w.week}:${p.section}`) : [`w${w.week}`])

/** First Monday of September (fall) or January (winter); editable in the sidebar. */
function defaultTermStart() {
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth() >= 7 ? 8 : 0, 1, 12)
  while (d.getDay() !== 1) d.setDate(d.getDate() + 1)
  return isoDate(d)
}

export default function App() {
  const [courses, setCourses] = useState<Course[]>([])
  const [course, setCourse] = useState(() => localStorage.getItem('tutor-course') ?? '')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [solutions, setSolutions] = useState<SolutionFile[]>([])
  const [openFile, setOpenFile] = useState<SolutionContent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [outline, setOutline] = useState<Outline | null>(null)
  const [outlineError, setOutlineError] = useState<string | null>(null)
  const [done, setDone] = useState<string[]>([])
  const [prefill, setPrefill] = useState<{ text: string; send?: boolean } | null>(null)
  const [termStart, setTermStart] = useState('')
  const [patternList, setPatternList] = useState<PatternSummary[]>([])
  const [seeding, setSeeding] = useState(false)
  const [patternFilled, setPatternFilled] = useState(false)

  useEffect(() => {
    api
      .courses()
      .then((cs) => {
        setCourses(cs)
        setCourse((c) => (cs.some((x) => x.id === c) ? c : (cs.find((x) => x.files > 0) ?? cs[0])?.id ?? ''))
      })
      .catch((e) => setError(`Can't reach the tutor server: ${e.message}`))
  }, [])

  const refreshSolutions = useCallback(() => {
    if (course) api.solutions(course).then(setSolutions).catch(() => {})
  }, [course])

  const refreshPatterns = useCallback(() => {
    if (course) api.patterns(course).then(setPatternList).catch(() => setPatternList([]))
  }, [course])

  useEffect(() => {
    if (!course) return
    localStorage.setItem('tutor-course', course)
    setSessionId(null)
    setOpenFile(null)
    refreshSolutions()
    refreshPatterns()
    setPrefill(null)
    setOutline(null)
    setOutlineError(null)
    api
      .outline(course)
      .then((o) => {
        setOutline(o)
        setTermStart(localStorage.getItem(`tutor-start-${course}`) || o.term_start || defaultTermStart())
      })
      .catch((e) => setOutlineError(e.message))
    setDone(JSON.parse(localStorage.getItem(`tutor-done2-${course}`) ?? '[]'))
    sessionFor(course)
      .then(setSessionId)
      .catch((e) => setError(e.message))
  }, [course, refreshSolutions, refreshPatterns])

  const openSolution = (path: string) => api.solution(course, path).then(setOpenFile)

  const openPattern = (slug: string) =>
    api.pattern(course, slug).then((p) => {
      setOpenFile({ name: p.name, path: `pattern:${p.slug}`, content: p.content })
      setPatternFilled(p.filled)
    })

  const reopen = (path: string) =>
    path.startsWith('pattern:') ? openPattern(path.slice(8)) : openSolution(path)

  const seedPatterns = () => {
    setSeeding(true)
    api
      .seedPatterns(course)
      .then(refreshPatterns)
      .catch((e) => setError(e.message))
      .finally(() => setSeeding(false))
  }

  const ask = (text: string) => setPrefill({ text, send: true })

  const openPath = useRef<string | null>(null)
  useEffect(() => {
    openPath.current = openFile?.path ?? null
  }, [openFile])

  const onToolDone = useCallback(
    (name: string) => {
      if (name !== 'write_solution_file' && name !== 'save_problem' && name !== 'save_pattern') return
      refreshSolutions()
      refreshPatterns()
      const path = openPath.current
      if (!path) return
      if (path.startsWith('pattern:'))
        api.pattern(course, path.slice(8)).then((p) => {
          setOpenFile({ name: p.name, path, content: p.content })
          setPatternFilled(p.filled)
        })
      else api.solution(course, path).then(setOpenFile)
    },
    [course, refreshSolutions, refreshPatterns],
  )

  const toggleDone = (week: string) => {
    const next = done.includes(week) ? done.filter((w) => w !== week) : [...done, week]
    setDone(next)
    localStorage.setItem(`tutor-done2-${course}`, JSON.stringify(next))
  }

  const allKeys = (outline?.weeks ?? []).filter((w) => w.week !== 'break').flatMap(weekKeys)
  const doneCount = allKeys.filter((k) => done.includes(k)).length
  const today = isoDate(new Date())
  const currentIdx = termStart ? Math.floor(daysBetween(termStart, today) / 7) : -1
  const nextExam = (outline?.exams ?? [])
    .filter((e) => /^\d{4}-\d{2}-\d{2}$/.test(e.date) && e.date >= today)
    .map((e) => ({ name: e.name, days: daysBetween(today, e.date) }))
    .sort((a, b) => a.days - b.days)[0]

  const chapters = solutions.reduce<Record<string, SolutionFile[]>>((acc, s) => {
    ;(acc[s.group] ??= []).push(s)
    return acc
  }, {})

  return (
    <div className="flex h-full">
      <div className="line-right w-64 shrink-0 overflow-y-auto px-3">
        <h3>AI Tutor</h3>

        <details>
          <summary>
            <b>Courses</b> ({course.toUpperCase()})
          </summary>
          <ul className="plain">
            {courses.map((c) => (
              <li key={c.id}>
                {c.id === course ? (
                  <b>{c.id.toUpperCase()}</b>
                ) : (
                  <button className="link" onClick={() => setCourse(c.id)}>
                    {c.id.toUpperCase()}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>

        <details>
          <summary>
            <b>Timeline</b>
            {allKeys.length > 0 && ` (${doneCount}/${allKeys.length} sections)`}
            {nextExam && (
              <div>
                <small>
                  {nextExam.name} in {nextExam.days} day{nextExam.days === 1 ? '' : 's'}
                </small>
              </div>
            )}
          </summary>
          {!outline && !outlineError && <small>Reading the outline...</small>}
          {outlineError && <small style={{ color: 'red' }}>{outlineError}</small>}
          {outline?.missing && (
            <small>
              No outline yet. Put a PDF with "outline" in its name in {course}/ and run <code>tutor ingest {course}</code>.
            </small>
          )}
          {outline && outline.weeks.length > 0 && (
            <>
              <small>
                Week 1 starts{' '}
                <input
                  type="date"
                  value={termStart}
                  onChange={(e) => {
                    setTermStart(e.target.value)
                    localStorage.setItem(`tutor-start-${course}`, e.target.value)
                  }}
                />
              </small>
              <ul className="plain" style={{ listStyle: 'none', paddingLeft: 0 }}>
                {outline.weeks.map((w, i) => {
                  const start = addDays(termStart, i * 7)
                  const now = i === currentIdx
                  const late = i < currentIdx && w.week !== 'break' && !weekKeys(w).every((k) => done.includes(k))
                  return (
                    <li
                      key={`${w.week}-${i}`}
                      style={{ margin: '0.35em 0', ...(now ? { background: '#ffffcc', outline: '1px solid #ccc' } : {}) }}
                    >
                      <small>{fmt(start)}</small>
                      {now && (
                        <small>
                          {' '}
                          <b>◀ this week</b>
                        </small>
                      )}
                      <br />
                      {w.week === 'break' ? (
                        <i>{w.topics}</i>
                      ) : (
                        <>
                          <b>
                            W{w.week} {w.topics}
                          </b>
                          {w.parts.length > 0 && (
                            <small>
                              {' '}
                              ({weekKeys(w).filter((k) => done.includes(k)).length}/{w.parts.length})
                            </small>
                          )}
                          {late && <small style={{ color: '#c00' }}> behind</small>}
                          {w.assignment && (
                            <div style={{ marginLeft: '0.5em' }}>
                              <small>Assignment {w.assignment.replace(/^A/i, '')}</small>
                            </div>
                          )}
                          {(w.parts.length ? w.parts : [null]).map((p) => {
                            const key = p ? `${w.week}:${p.section}` : `w${w.week}`
                            return (
                              <div key={key} className="flex items-start gap-1" style={{ marginLeft: '0.5em' }}>
                                <input
                                  type="checkbox"
                                  checked={done.includes(key)}
                                  onChange={() => toggleDone(key)}
                                  style={{ margin: '0.2em 0 0' }}
                                />
                                <span>
                                  <button
                                    className="link"
                                    onClick={() =>
                                      setPrefill({
                                        text: p
                                          ? `Teach me section ${p.section}${p.title ? ` ${p.title}` : ''} (week ${w.week})` +
                                            (p.page ? `. It's in ${p.file}, PDF pages ${p.page}-${p.end_page}` : '') +
                                            (p.problems
                                              ? `. The outline's suggested problems for this section: ${p.problems}; use those for practice`
                                              : '') +
                                            '. Start from zero.'
                                          : `Teach me week ${w.week}: ${w.topics}. Start from zero.`,
                                        send: true,
                                      })
                                    }
                                  >
                                    {p ? `${p.section} ${p.title}` : 'Learn this week'}
                                  </button>
                                  {p?.page ? <small> p.{p.page}</small> : null}
                                  {p?.problems && (
                                    <div>
                                      <small>Problems: {p.problems.replace(/,\s*/g, ', ')}</small>
                                    </div>
                                  )}
                                </span>
                              </div>
                            )
                          })}
                        </>
                      )}
                      {w.note && (
                        <div>
                          <small>
                            <b>{w.note}</b>
                          </small>
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
              {outline.exams.map((e) => (
                <div key={e.name}>
                  <small>
                    <b>{e.name}</b>
                    {e.date && `: ${fmt(e.date)}`}
                    {e.covers && ` (${e.covers})`}
                  </small>
                </div>
              ))}
            </>
          )}
        </details>

        <details>
          <summary>
            <b>Patterns</b>
            {patternList.length > 0 &&
              ` (${patternList.filter((p) => p.solved > 0).length}/${patternList.length} practiced)`}
          </summary>
          {patternList.length === 0 ? (
            <div>
              <small>No pattern list yet. </small>
              <button onClick={seedPatterns} disabled={seeding}>
                {seeding ? 'Building... (1-2 min)' : 'Build from outline'}
              </button>
            </div>
          ) : (
            <div className="pl-3">
              <small>Number = problems solved. Click one to see its template, variations and traps.</small>
              {Object.entries(
                patternList.reduce<Record<string, PatternSummary[]>>((acc, p) => {
                  const ch = p.sections.match(/^\s*(\d+)\./)?.[1] ?? 'Other'
                  ;(acc[ch] ??= []).push(p)
                  return acc
                }, {}),
              ).map(([ch, list]) => (
                <details key={ch}>
                  <summary>
                    {ch === 'Other' ? 'Other' : `Chapter ${ch}`}{' '}
                    <small>
                      ({list.filter((p) => p.solved > 0).length}/{list.length})
                    </small>
                  </summary>
                  <ul className="plain">
                    {list.map((p) => (
                      <li key={p.slug} title={`${p.sections} · spot it: ${p.recognize}`}>
                        <button className="link" onClick={() => openPattern(p.slug)}>
                          {p.name}
                        </button>{' '}
                        <small style={{ color: p.solved ? '#000' : '#999' }}>{p.solved}</small>
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
            </div>
          )}
        </details>

        <details>
          <summary>
            <b>Solution files</b> ({solutions.length})
          </summary>
          {solutions.length === 0 && (
            <div>
              <small>None yet</small>
            </div>
          )}
          <div className="pl-3">
            {Object.entries(chapters).map(([group, files]) => (
              <details key={group}>
                <summary>
                  {group === 'cheatsheets'
                    ? 'Cheat sheets'
                    : group === 'assignments'
                      ? 'Assignments'
                      : group
                        ? group.replace('chapter-', 'Chapter ')
                        : 'Other'}
                </summary>
                <ul className="plain">
                  {files.map((s) => (
                    <li key={s.path}>
                      <button className="link" onClick={() => openSolution(s.path)} title={s.modified}>
                        {s.name.replace('-solutions.md', '').replace('-cheatsheet.md', '').replace('.md', '')}
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        </details>
      </div>

      {error ? (
        <p className="px-4" style={{ color: 'red' }}>
          {error}
        </p>
      ) : (
        <div className="flex min-w-0 flex-1">
          {sessionId ? (
            <Chat course={course} sessionId={sessionId} onToolDone={onToolDone} prefill={prefill} />
          ) : (
            <p className="px-4">Loading...</p>
          )}
        </div>
      )}

      {openFile && (
        <div className="line-left w-[45%] shrink-0 overflow-y-auto px-4">
          <p>
            <code>{openFile.path.startsWith('pattern:') ? 'pattern' : openFile.path}</code> &nbsp;
            <button className="link" onClick={() => reopen(openFile.path)}>
              reload
            </button>{' '}
            <button className="link" onClick={() => setOpenFile(null)}>
              close
            </button>
          </p>
          {openFile.path.startsWith('pattern:') && (
            <p>
              <button onClick={() => ask(`Drill pattern "${openFile.name}": give me a fresh problem of this type.`)}>
                Drill this pattern
              </button>{' '}
              <button
                onClick={() =>
                  ask(
                    `${patternFilled ? 'Redo' : 'Fill in'} the pattern page for "${openFile.name}": template, ` +
                      'variations with how likely each is on the exam, and traps.',
                  )
                }
              >
                {patternFilled ? 'Rewrite page' : 'Fill in this pattern'}
              </button>
            </p>
          )}
          <hr />
          <Markdown>{openFile.content}</Markdown>
        </div>
      )}
    </div>
  )
}
