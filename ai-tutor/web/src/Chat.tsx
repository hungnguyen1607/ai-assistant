import { useEffect, useRef, useState } from 'react'
import { api, sendMessage } from './api'
import { Markdown } from './Markdown'

type Part =
  | { kind: 'text'; text: string }
  | { kind: 'tool'; id: string; name: string; args: string; status: 'running' | 'ok' | 'error' }
type Msg = { role: 'user' | 'assistant'; parts: Part[] }

const TOOL_LABELS: Record<string, string> = {
  list_materials: 'Listing course files',
  search_materials: 'Searching your materials',
  find_in_materials: 'Looking it up',
  read_pages: 'Reading pages',
  check_ode_solution: 'Verifying with SymPy',
  solve_ode: 'Solving with SymPy',
  math: 'Calculating with SymPy',
  run_code: 'Running code',
  list_solution_files: 'Checking your solutions',
  read_solution_file: 'Reading your solutions',
  write_solution_file: 'Writing solution file',
  save_problem: 'Saving to library',
  get_saved_problem: 'Checking the library',
  update_profile: 'Updating your profile',
}

const STATUS = { running: '...', ok: 'done', error: 'failed' }

const MODES = [
  { label: 'Solve', prefix: 'Solve ' },
  { label: 'Explain', prefix: 'Explain ' },
  { label: 'Hint', prefix: 'Give me a hint for ' },
  { label: 'Check my work', prefix: 'Check my work: ' },
  { label: 'Anki', prefix: 'Make an Anki card for ' },
]

const EXAMPLES: Record<string, string[]> = {
  engr213: ['Solve 2.3 problems 1-6', 'Explain integrating factors like I am 5', 'Give me a hint for 2.2 #9'],
  comp232: ['Explain proof by contrapositive with examples', 'Give me a hint for A3 question 1', 'Quiz me on week 4'],
}

export function Chat({
  course,
  sessionId,
  onToolDone,
  prefill,
}: {
  course: string
  sessionId: string
  onToolDone: (name: string) => void
  prefill: { text: string; send?: boolean } | null
}) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [exam, setExam] = useState('midterm')
  const [topics, setTopics] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setMessages([])
    setError(null)
    api
      .session(sessionId)
      .then((s) => setMessages(s.messages.map((m) => ({ role: m.role, parts: [{ kind: 'text', text: m.content }] }))))
      .catch(() => {})
  }, [sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!prefill) return
    if (prefill.send) {
      send(prefill.text)
      return
    }
    setInput(prefill.text)
    inputRef.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill])

  const updateLast = (fn: (parts: Part[]) => Part[]) =>
    setMessages((ms) => [...ms.slice(0, -1), { ...ms[ms.length - 1], parts: fn(ms[ms.length - 1].parts) }])

  async function send(text: string) {
    if (!text.trim() || busy) return
    setInput('')
    setError(null)
    setBusy(true)
    setMessages((ms) => [...ms, { role: 'user', parts: [{ kind: 'text', text }] }, { role: 'assistant', parts: [] }])
    const controller = new AbortController()
    abortRef.current = controller
    try {
      for await (const ev of sendMessage(sessionId, text, controller.signal)) {
        if (ev.type === 'text') {
          updateLast((parts) => {
            const last = parts[parts.length - 1]
            return last?.kind === 'text'
              ? [...parts.slice(0, -1), { kind: 'text', text: last.text + ev.delta }]
              : [...parts, { kind: 'text', text: ev.delta }]
          })
        } else if (ev.type === 'tool') {
          updateLast((parts) => [...parts, { kind: 'tool', id: ev.id, name: ev.name, args: ev.args, status: 'running' }])
        } else if (ev.type === 'tool_result') {
          updateLast((parts) =>
            parts.map((p) => (p.kind === 'tool' && p.id === ev.id ? { ...p, status: ev.ok ? 'ok' : 'error' } : p)),
          )
          onToolDone(ev.name)
        } else if (ev.type === 'error') {
          setError(ev.message)
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    } finally {
      setBusy(false)
      abortRef.current = null
      inputRef.current?.focus()
    }
  }

  async function newTopic() {
    abortRef.current?.abort()
    await api.reset(sessionId)
    setMessages([])
    setError(null)
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <div className="line-bottom px-4 py-2">
        <b>{course.toUpperCase()}</b> tutor &nbsp;
        <button className="link" onClick={newTopic}>
          clear chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4">
        <div className="max-w-3xl">
          {messages.length === 0 && (
            <>
              <p>What are we studying? Ask to solve, explain, hint or check your work. Try:</p>
              <ul>
                {(EXAMPLES[course] ?? ['Explain the first chapter of the outline', 'Make me a practice set']).map((ex) => (
                  <li key={ex}>
                    <button className="link" onClick={() => send(ex)}>
                      {ex}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {messages.map((m, i) =>
            m.role === 'user' ? (
              <p key={i} style={{ whiteSpace: 'pre-wrap' }}>
                <b>You:</b> {(m.parts[0] as { text: string }).text}
              </p>
            ) : (
              <div key={i}>
                <b>Tutor:</b>
                {m.parts.map((p, j) =>
                  p.kind === 'text' ? (
                    <Markdown key={j}>{p.text}</Markdown>
                  ) : (
                    <div key={j} title={p.args}>
                      <small>
                        <i>
                          {TOOL_LABELS[p.name] ?? p.name} {STATUS[p.status]}
                        </i>
                      </small>
                    </div>
                  ),
                )}
                {busy && i === messages.length - 1 && m.parts.length === 0 && <p>Thinking...</p>}
                <hr />
              </div>
            ),
          )}
          {error && <p style={{ color: 'red' }}>Error: {error}</p>}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="line-top px-4 py-2">
        <div>
          <small>
            Quick:{' '}
            {MODES.map((mode, i) => (
              <span key={mode.label}>
                {i > 0 && ' · '}
                <button
                  className="link"
                  onClick={() => {
                    setInput(mode.prefix)
                    inputRef.current?.focus()
                  }}
                >
                  {mode.label}
                </button>
              </span>
            ))}
          </small>
        </div>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
          rows={3}
          placeholder="e.g. solve 2.4 problems 1-5 (Enter to send, Shift+Enter for a new line)"
          style={{ width: '100%', maxWidth: '48rem', boxSizing: 'border-box', margin: '0.4em 0' }}
        />
        <div>
          {busy ? (
            <button onClick={() => abortRef.current?.abort()}>Stop</button>
          ) : (
            <button onClick={() => send(input)} disabled={!input.trim()}>
              Send
            </button>
          )}{' '}
          <button onClick={() => setSheetOpen((o) => !o)} disabled={busy}>
            Cheat sheet
          </button>
        </div>
        {sheetOpen && (
          <p>
            <select value={exam} onChange={(e) => setExam(e.target.value)}>
              <option value="midterm">Midterm</option>
              <option value="final">Final</option>
              <option value="quiz">Quiz</option>
            </select>{' '}
            <input
              value={topics}
              onChange={(e) => setTopics(e.target.value)}
              placeholder="chapters/topics, e.g. 1, 2.1-2.4 (blank = from outline)"
              style={{ width: '22rem' }}
            />{' '}
            <button
              disabled={busy}
              onClick={() => {
                setSheetOpen(false)
                send(
                  `Make a ${exam} cheat sheet for ${course.toUpperCase()} covering ` +
                    (topics.trim() || `everything on the ${exam} according to the outline`) +
                    '. Include the problem variations and which ones are most likely to come up.',
                )
              }}
            >
              Make
            </button>
          </p>
        )}
      </div>
    </div>
  )
}
