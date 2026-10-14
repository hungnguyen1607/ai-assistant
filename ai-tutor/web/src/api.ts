export type Course = { id: string; files: number }
export type Material = { name: string; pages: number }
export type SolutionFile = { name: string; path: string; group: string; modified: string }
export type SolutionContent = { name: string; path: string; content: string }

export type OutlinePart = {
  section: string
  title: string
  page: number
  end_page: number
  file: string
  problems: string
}
export type OutlineWeek = {
  week: string
  topics: string
  sections: string
  note: string
  assignment?: string
  parts: OutlinePart[]
}
export type Outline = {
  weeks: OutlineWeek[]
  exams: { name: string; date: string; covers: string }[]
  term_start?: string
  missing?: boolean
}

export type PatternSummary = {
  id: number
  slug: string
  name: string
  sections: string
  recognize: string
  filled: boolean
  solved: number
  verified: number
}

export type ProblemSummary = {
  id: number
  chapter: string
  section: string
  number: string
  title: string
  answer: string
  verified: boolean
}
export type Problem = ProblemSummary & {
  course: string
  statement: string
  solution: string
  source: string
  created_at: string
  updated_at: string
}

export type TutorEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool'; id: string; name: string; args: string }
  | { type: 'tool_result'; id: string; name: string; ok: boolean }
  | { type: 'done' }
  | { type: 'error'; message: string }

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  courses: () => fetch('/api/courses').then(json<Course[]>),
  materials: (course: string) => fetch(`/api/courses/${course}/materials`).then(json<Material[]>),
  solutions: (course: string) => fetch(`/api/courses/${course}/solutions`).then(json<SolutionFile[]>),
  solution: (course: string, path: string) =>
    fetch(`/api/courses/${course}/solutions/${path.split('/').map(encodeURIComponent).join('/')}`).then(
      json<SolutionContent>,
    ),
  outline: (course: string) => fetch(`/api/courses/${course}/outline`).then(json<Outline>),
  patterns: (course: string) => fetch(`/api/courses/${course}/patterns`).then(json<PatternSummary[]>),
  seedPatterns: (course: string) =>
    fetch(`/api/courses/${course}/patterns/seed`, { method: 'POST' }).then(json<{ added: number; tagged: number }>),
  pattern: (course: string, slug: string) =>
    fetch(`/api/courses/${course}/patterns/${encodeURIComponent(slug)}`).then(
      json<{ slug: string; name: string; filled: boolean; content: string }>,
    ),
  problems: (course: string) => fetch(`/api/courses/${course}/problems`).then(json<ProblemSummary[]>),
  problem: (id: number) => fetch(`/api/problems/${id}`).then(json<Problem>),
  deleteProblem: (id: number) => fetch(`/api/problems/${id}`, { method: 'DELETE' }).then(json<{ ok: boolean }>),
  newSession: (course: string) =>
    fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ course }),
    }).then(json<{ session_id: string }>),
  session: (id: string) =>
    fetch(`/api/sessions/${id}`).then(json<{ course: string; messages: { role: 'user' | 'assistant'; content: string }[] }>),
  reset: (id: string) => fetch(`/api/sessions/${id}/reset`, { method: 'POST' }).then(json<{ ok: boolean }>),
}

/** POST a message and yield server-sent events as they arrive. */
export async function* sendMessage(sessionId: string, text: string, signal: AbortSignal): AsyncGenerator<TutorEvent> {
  const res = await fetch(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
    signal,
  })
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) yield JSON.parse(line.slice(6)) as TutorEvent
      }
    }
  }
}
