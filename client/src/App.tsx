import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

type Role = 'user' | 'assistant'

interface Message {
  id: string
  role: Role
  text: string
}

function getSessionId(): string {
  const key = 'session_id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(key, id)
  }
  return id
}

function newSessionId(): string {
  const id = crypto.randomUUID()
  localStorage.setItem('session_id', id)
  return id
}

const SUGERENCIAS = [
  '¿Qué artículos tenemos sobre sistemas de entrega de activos y péptidos antiedad?',
  'Dame un resumen de las conclusiones sobre cómo mejorar la penetración de ingredientes activos en la piel',
  '¿Qué desafíos técnicos comparten los estudios sobre formulación cosmética avanzada?',
  'Dame el detalle del estudio FAM-107 sobre penetración dérmica',
]

// ── íconos ────────────────────────────────────────────────────────────────────

function IconPlus() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
      <path d="M12 5v14M5 12h14" strokeLinecap="round" />
    </svg>
  )
}

function IconSend() {
  return (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
    </svg>
  )
}

// ── componentes de markdown ───────────────────────────────────────────────────

const mdComponents: Components = {
  p: ({ children }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
  h1: ({ children }) => <h1 className="text-base font-semibold text-stone-900 mt-4 mb-2 first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-semibold text-stone-900 mt-3 mb-1.5 first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-stone-700 mt-3 mb-1 first:mt-0">{children}</h3>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-3 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-3 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-stone-900">{children}</strong>,
  em: ({ children }) => <em className="italic text-stone-700">{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-stone-300 pl-3 my-2 text-stone-600 italic">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-stone-700 underline underline-offset-2 hover:text-stone-900">
      {children}
    </a>
  ),
  hr: () => <hr className="border-stone-200 my-3" />,
  pre: ({ children }) => (
    <pre className="my-2 bg-stone-100 rounded-xl px-4 py-3 overflow-x-auto text-xs leading-relaxed">
      {children}
    </pre>
  ),
  code: ({ className, children }) =>
    className ? (
      <code className="font-mono text-stone-800">{children}</code>
    ) : (
      <code className="bg-stone-100 text-stone-800 px-1.5 py-0.5 rounded text-xs font-mono">
        {children}
      </code>
    ),
  table: ({ children }) => (
    <div className="overflow-x-auto my-2">
      <table className="border-collapse w-full text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-stone-200 bg-stone-50 px-3 py-1.5 text-left font-semibold text-stone-700">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-stone-200 px-3 py-1.5 text-stone-700">{children}</td>
  ),
}

// ── indicador de escritura ────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex max-w-2xl">
      <div className="bg-white rounded-2xl rounded-bl-sm px-4 py-3.5 shadow-sm border border-stone-100">
        <div className="flex gap-1.5 items-center h-4">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </div>
      </div>
    </div>
  )
}

// ── burbuja ───────────────────────────────────────────────────────────────────

function Bubble({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-stone-100 text-stone-900 rounded-2xl rounded-br-sm px-4 py-3 max-w-xl text-sm leading-relaxed whitespace-pre-wrap shadow-sm border border-stone-200">
          {message.text}
        </div>
      </div>
    )
  }

  return (
    <div className="flex max-w-2xl">
      <div className="bg-white rounded-2xl rounded-bl-sm px-4 py-3.5 shadow-sm border border-stone-100 text-sm text-stone-800 min-w-0">
        {message.text ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {message.text}
          </ReactMarkdown>
        ) : (
          <span className="inline-block w-1.5 h-4 bg-stone-300 animate-pulse rounded-sm" />
        )}
      </div>
    </div>
  )
}

// ── componente principal ──────────────────────────────────────────────────────

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sessionId = useRef(getSessionId())
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || loading) return

    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', text: trimmed }])
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setLoading(true)
    setError(null)

    const assistantId = crypto.randomUUID()

    try {
      const res = await fetch('/webhook/papermind-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: trimmed, session_id: sessionId.current }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const contentType = res.headers.get('content-type') ?? ''

      if (contentType.includes('text/event-stream')) {
        setMessages(prev => [...prev, { id: assistantId, role: 'assistant', text: '' }])

        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const raw = line.slice(6).trim()
            if (raw === '[DONE]') continue

            let token = raw
            try {
              const parsed = JSON.parse(raw)
              token = parsed.token ?? parsed.text ?? parsed.content ?? parsed.output ?? raw
            } catch { /* el dato ya es texto plano */ }

            setMessages(prev =>
              prev.map(m => m.id === assistantId ? { ...m, text: m.text + token } : m)
            )
          }
        }
      } else {
        const data = await res.json()
        const answer: string =
          data.answer ?? data.output ?? data.text ?? data.response ?? JSON.stringify(data)

        setMessages(prev => [...prev, { id: assistantId, role: 'assistant', text: '' }])
        setLoading(false)

        let i = 0
        const iv = setInterval(() => {
          i = Math.min(i + 4, answer.length)
          setMessages(prev =>
            prev.map(m => m.id === assistantId ? { ...m, text: answer.slice(0, i) } : m)
          )
          if (i >= answer.length) clearInterval(iv)
        }, 20)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Error desconocido'
      setError(`No se pudo obtener respuesta: ${msg}`)
    } finally {
      setLoading(false)
      textareaRef.current?.focus()
    }
  }, [loading])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  const handleNuevaConversacion = () => {
    sessionId.current = newSessionId()
    setMessages([])
    setError(null)
    setInput('')
  }

  const showWelcome = messages.length === 0 && !loading

  return (
    <div className="flex flex-col h-full bg-stone-50">

      <header className="border-b border-stone-200 bg-white shrink-0">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center">
            <span className="text-sm font-semibold text-stone-900 tracking-tight">PaperMind</span>
          </div>
          <button
            onClick={handleNuevaConversacion}
            className="flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-900 border border-stone-200 hover:border-stone-400 px-3 py-1.5 rounded-lg transition-colors"
          >
            <IconPlus />
            Nueva consulta
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        {showWelcome ? (
          <div className="flex flex-col items-center justify-center h-full gap-8 px-4 pb-12">
            <div className="text-center space-y-2">
              <h2 className="text-2xl font-semibold text-stone-900">¿Qué quieres consultar?</h2>
              <p className="text-sm text-stone-400 max-w-xs leading-relaxed">
                Encuentra respuestas en tus documentos de investigación al instante.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-3xl">
              {SUGERENCIAS.map(s => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="text-left text-sm text-stone-600 bg-white border border-stone-200 rounded-xl px-4 py-3.5 hover:border-stone-400 hover:bg-stone-50 transition-all"
                >
                  <span className="block text-stone-300 text-xs mb-1">Sugerencia</span>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="px-4 py-6 space-y-4 max-w-3xl mx-auto">
            {messages.map(m => <Bubble key={m.id} message={m} />)}
            {loading && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        )}
        {showWelcome && <div ref={bottomRef} />}
      </main>

      {error && (
        <div className="max-w-3xl mx-auto px-4 pb-1 w-full">
          <div className="bg-red-50 border border-red-100 text-red-600 text-xs rounded-lg px-3 py-2">
            {error}
          </div>
        </div>
      )}

      <footer className="border-t border-stone-200 bg-white shrink-0">
        <div className="max-w-3xl mx-auto px-4 pt-3 pb-4">
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={e => {
                setInput(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
              }}
              onKeyDown={handleKeyDown}
              placeholder="Escribe tu consulta..."
              className="flex-1 resize-none rounded-xl border border-stone-200 bg-stone-50 px-4 py-2.5 text-sm text-stone-900 placeholder-stone-400 focus:outline-none focus:border-stone-400 focus:bg-white transition-colors"
            />
            <button
              onClick={() => send(input)}
              disabled={!input.trim() || loading}
              className="shrink-0 bg-stone-900 text-white rounded-xl w-10 h-10 flex items-center justify-center disabled:opacity-30 hover:bg-stone-700 transition-colors"
            >
              <IconSend />
            </button>
          </div>
          <p className="text-center text-xs text-stone-300 mt-2">
            Shift+Enter para nueva línea
          </p>
        </div>
      </footer>

    </div>
  )
}
