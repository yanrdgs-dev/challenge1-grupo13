import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"

type IconName =
  | "archive"
  | "arrow-up"
  | "ballot"
  | "book"
  | "chevron-down"
  | "close"
  | "external"
  | "file"
  | "menu"
  | "message"
  | "more"
  | "plus"
  | "search"
  | "shield"
  | "sparkle"

function Icon({
  name,
  className = "size-5",
}: {
  name: IconName
  className?: string
}) {
  const paths: Record<IconName, ReactNode> = {
    archive: (
      <>
        <path d="M4 7h16M5 7l1 13h12l1-13M9 11h6" />
        <path d="M5 4h14v3H5z" />
      </>
    ),
    "arrow-up": (
      <>
        <path d="M12 19V5M6.5 10.5 12 5l5.5 5.5" />
      </>
    ),
    ballot: (
      <>
        <path d="M6 4h12v16H6zM9 8h6M9 12h6M9 16h3" />
      </>
    ),
    book: (
      <>
        <path d="M4 5.5A3.5 3.5 0 0 1 7.5 2H11v17H7.5A3.5 3.5 0 0 0 4 22zM20 5.5A3.5 3.5 0 0 0 16.5 2H13v17h3.5A3.5 3.5 0 0 1 20 22z" />
      </>
    ),
    "chevron-down": <path d="m8 10 4 4 4-4" />,
    close: (
      <>
        <path d="m6 6 12 12M18 6 6 18" />
      </>
    ),
    external: (
      <>
        <path d="M14 4h6v6M20 4l-9 9" />
        <path d="M18 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h6" />
      </>
    ),
    file: (
      <>
        <path d="M6 2h8l4 4v16H6zM14 2v5h5M9 12h6M9 16h6" />
      </>
    ),
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    message: (
      <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
    ),
    more: (
      <>
        <circle cx="5" cy="12" r="1" />
        <circle cx="12" cy="12" r="1" />
        <circle cx="19" cy="12" r="1" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </>
    ),
    shield: (
      <>
        <path d="M12 2 4.5 5v5.5c0 4.8 3.2 9.2 7.5 10.5 4.3-1.3 7.5-5.7 7.5-10.5V5z" />
        <path d="m8.5 11.5 2.3 2.3 4.7-5" />
      </>
    ),
    sparkle: (
      <path d="M12 3c.4 4.8 2.2 6.6 7 7-4.8.4-6.6 2.2-7 7-.4-4.8-2.2-6.6-7-7 4.8-.4 6.6-2.2 7-7ZM19 16c.2 2 1 2.8 3 3-2 .2-2.8 1-3 3-.2-2-1-2.8-3-3 2-.2 2.8-1 3-3Z" />
    ),
  }

  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  )
}

function PolisLogo({ className = "size-6" }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 32 32"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3.5 11.5 16 4.5l12.5 7H3.5Z" strokeWidth="2.25" />
      <path d="M5 14h22M6.5 25h19M4.5 28h23" strokeWidth="2.5" />
      <path
        d="M8.5 15.5v8M13.5 15.5v8M18.5 15.5v8M23.5 15.5v8"
        strokeWidth="2.25"
      />
    </svg>
  )
}

interface ChatMessage {
  id: string
  role: "user" | "assistant"
  text: string
  verdict?: "VERDADEIRO" | "FALSO" | "INCONCLUSIVO" | "VERIFICADO"
  sources?: string[]
  subdetails?: string[]
}

interface ChatSession {
  id: string
  title: string
  createdAt: number
  messages: ChatMessage[]
}

interface Suggestion {
  icon: IconName
  eyebrow: string
  text: string
}

const defaultSuggestions: Suggestion[] = [
  {
    icon: "ballot",
    eyebrow: "Eleições",
    text: "Como funciona o segundo turno no Brasil?",
  },
  {
    icon: "book",
    eyebrow: "Cidadania",
    text: "A confirmação de ministros do STF pelo Senado é por votação secreta?",
  },
  {
    icon: "file",
    eyebrow: "Cota Parlamentar",
    text: "Todo deputado federal tem um teto fixo de R$ 500 por ano para combustível?",
  },
  {
    icon: "archive",
    eyebrow: "Transparência",
    text: "Dá para ver no site do TSE quanto cada candidato declarou ter gastado?",
  },
]

function groupSessions(sessions: ChatSession[]) {
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterdayStart = todayStart - 24 * 60 * 60 * 1000

  const today: ChatSession[] = []
  const yesterday: ChatSession[] = []
  const older: ChatSession[] = []

  for (const s of sessions) {
    if (s.createdAt >= todayStart) {
      today.push(s)
    } else if (s.createdAt >= yesterdayStart) {
      yesterday.push(s)
    } else {
      older.push(s)
    }
  }

  const groups: { label: string; items: ChatSession[] }[] = []
  if (today.length > 0) groups.push({ label: "Hoje", items: today })
  if (yesterday.length > 0) groups.push({ label: "Ontem", items: yesterday })
  if (older.length > 0) groups.push({ label: "Anteriores", items: older })

  return groups
}

function Sidebar({
  open,
  onClose,
  onNewChat,
  sessions,
  activeSessionId,
  onSelectSession,
  onDeleteSession,
}: {
  open: boolean
  onClose: () => void
  onNewChat: () => void
  sessions: ChatSession[]
  activeSessionId: string | null
  onSelectSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
}) {
  const [searchTerm, setSearchTerm] = useState("")

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchTerm.toLowerCase().trim())
  )
  const groups = groupSessions(filteredSessions)

  return (
    <>
      {open && (
        <button
          aria-label="Fechar menu"
          className="fixed inset-0 z-30 bg-slate-950/30 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[18rem] flex-col border-r border-slate-200/80 bg-[#f8faf9] transition-transform duration-300 lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-20 items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-emerald-700 text-white shadow-sm shadow-emerald-900/20">
              <PolisLogo className="size-6" />
            </div>
            <div>
              <p className="text-base font-semibold tracking-tight text-slate-900">
                Pólis
              </p>
              <p className="text-[0.65rem] font-medium uppercase tracking-[0.16em] text-slate-500">
                Política com clareza
              </p>
            </div>
          </div>
          <button
            aria-label="Fechar menu lateral"
            className="grid size-9 place-items-center rounded-lg text-slate-500 hover:bg-slate-200/70 lg:hidden"
            onClick={onClose}
          >
            <Icon name="close" />
          </button>
        </div>

        <div className="px-4 pb-4">
          <button
            onClick={() => {
              onNewChat()
              onClose()
            }}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white shadow-sm shadow-emerald-900/10 transition hover:bg-emerald-800"
          >
            <Icon name="plus" className="size-4" />
            Nova conversa
          </button>
        </div>

        {sessions.length > 0 && (
          <div className="px-4 pb-3">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white/70 px-3 py-2 text-slate-400 focus-within:border-emerald-300 focus-within:ring-2 focus-within:ring-emerald-100">
              <Icon name="search" className="size-4 shrink-0" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Buscar conversas..."
                className="w-full bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400"
              />
              {searchTerm && (
                <button
                  type="button"
                  aria-label="Limpar busca"
                  onClick={() => setSearchTerm("")}
                  className="text-slate-400 hover:text-slate-600"
                >
                  <Icon name="close" className="size-3.5" />
                </button>
              )}
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-3">
          {sessions.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <div className="mx-auto mb-3 grid size-10 place-items-center rounded-xl bg-slate-100 text-slate-400">
                <Icon name="message" className="size-5" />
              </div>
              <p className="text-xs font-semibold text-slate-600">Nenhum histórico anterior</p>
              <p className="mt-1 text-[0.72rem] leading-relaxed text-slate-400">
                O histórico de chats aparecerá aqui conforme você utilizar a Pólis para fazer perguntas e checagens.
              </p>
            </div>
          ) : filteredSessions.length === 0 ? (
            <div className="px-4 py-8 text-center text-xs text-slate-400">
              Nenhuma conversa encontrada para "{searchTerm}".
            </div>
          ) : (
            <nav aria-label="Histórico de conversas" className="space-y-5">
              {groups.map((group) => (
                <div key={group.label}>
                  <p className="mb-2 px-3 text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-slate-400">
                    {group.label}
                  </p>
                  <div className="space-y-0.5">
                    {group.items.map((sess) => {
                      const isActive = sess.id === activeSessionId
                      return (
                        <div
                          key={sess.id}
                          className={`group flex items-center justify-between rounded-lg px-3 py-2.5 text-sm transition ${
                            isActive
                              ? "bg-emerald-50 font-medium text-emerald-900 border border-emerald-200/60"
                              : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                          }`}
                        >
                          <button
                            onClick={() => {
                              onSelectSession(sess.id)
                              onClose()
                            }}
                            className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                          >
                            <Icon
                              name="message"
                              className={`size-4 shrink-0 ${
                                isActive ? "text-emerald-700" : "opacity-60"
                              }`}
                            />
                            <span className="truncate">{sess.title}</span>
                          </button>
                          <button
                            type="button"
                            aria-label="Excluir conversa do histórico"
                            title="Excluir conversa"
                            onClick={(e) => {
                              e.stopPropagation()
                              onDeleteSession(sess.id)
                            }}
                            className="ml-1 hidden rounded p-1 text-slate-400 hover:bg-slate-200/60 hover:text-rose-600 group-hover:block"
                          >
                            <Icon name="close" className="size-3.5" />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </nav>
          )}
        </div>

        <div className="border-t border-slate-200/80 p-3 text-center">
          <p className="text-[0.68rem] font-medium text-slate-400">
            Pólis · Informação pública auditável
          </p>
        </div>
      </aside>
    </>
  )
}

function SourceChip({ children }: { children: ReactNode }) {
  return (
    <button className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800 transition hover:border-emerald-300">
      <Icon name="shield" className="size-3.5" />
      {children}
      <Icon name="external" className="size-3" />
    </button>
  )
}

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [message, setMessage] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<Suggestion[]>(defaultSuggestions)

  // Histórico dinâmico de conversas sincronizado com o uso do sistema
  const [sessions, setSessions] = useState<ChatSession[]>(() => {
    try {
      const stored = localStorage.getItem("polis_chat_sessions")
      return stored ? JSON.parse(stored) : []
    } catch {
      return []
    }
  })
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [conversation, setConversation] = useState<ChatMessage[]>([])

  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Salva o histórico dinâmico no localStorage conforme o uso
  useEffect(() => {
    try {
      localStorage.setItem("polis_chat_sessions", JSON.stringify(sessions))
    } catch {
      // Ignora erro de cota de armazenamento se houver
    }
  }, [sessions])

  useEffect(() => {
    fetch("/api/suggestions")
      .then((res) => {
        if (!res.ok) throw new Error("Erro ao carregar sugestões")
        return res.json()
      })
      .then((data: Suggestion[]) => {
        if (Array.isArray(data) && data.length > 0) {
          setSuggestions(data)
        }
      })
      .catch(() => {
        // Mantém defaultSuggestions em caso de falha de conexão inicial
      })
  }, [])

  useEffect(() => {
    // Rolagem automática para a mensagem mais recente
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [conversation, isLoading])

  async function sendQuery(queryText: string) {
    const trimmed = queryText.trim()
    if (!trimmed || isLoading) return

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: trimmed,
    }

    let currentSessionId = activeSessionId
    const updatedConversation = [...conversation, userMsg]
    setConversation(updatedConversation)
    setMessage("")
    setIsLoading(true)

    // Se for uma nova conversa, cria a sessão no histórico dinâmico
    if (!currentSessionId) {
      currentSessionId = `session-${Date.now()}`
      setActiveSessionId(currentSessionId)
      const newSession: ChatSession = {
        id: currentSessionId,
        title: trimmed.length > 42 ? trimmed.slice(0, 40) + "..." : trimmed,
        createdAt: Date.now(),
        messages: [userMsg],
      }
      setSessions((prev) => [newSession, ...prev])
    } else {
      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentSessionId
            ? { ...s, messages: [...s.messages, userMsg] }
            : s
        )
      )
    }

    try {
      const response = await fetch("/api/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed }),
      })

      if (!response.ok) {
        throw new Error(`Falha na requisição: ${response.status}`)
      }

      const data = await response.json()
      const assistantReply: ChatMessage = {
        id: data.id || `assistant-${Date.now()}`,
        role: "assistant",
        text: data.text,
        verdict: data.verdict,
        subdetails: data.subdetails,
        sources: data.sources,
      }

      setConversation((prev) => [...prev, assistantReply])
      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentSessionId
            ? { ...s, messages: [...s.messages, assistantReply] }
            : s
        )
      )
    } catch {
      const fallbackReply: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text: "Não foi possível conectar ao servidor de fact-checking no momento. Verifique se o backend está em execução.",
        verdict: "INCONCLUSIVO",
        sources: ["Sistema Offline"],
      }
      setConversation((prev) => [...prev, fallbackReply])
      setSessions((prev) =>
        prev.map((s) =>
          s.id === currentSessionId
            ? { ...s, messages: [...s.messages, fallbackReply] }
            : s
        )
      )
    } finally {
      setIsLoading(false)
    }
  }

  function submitMessage(event: FormEvent) {
    event.preventDefault()
    sendQuery(message)
  }

  function handleSelectSuggestion(suggestionText: string) {
    sendQuery(suggestionText)
  }

  function handleNewChat() {
    setActiveSessionId(null)
    setConversation([])
    setMessage("")
  }

  function handleSelectSession(sessionId: string) {
    const session = sessions.find((s) => s.id === sessionId)
    if (session) {
      setActiveSessionId(session.id)
      setConversation(session.messages)
      setMessage("")
    }
  }

  function handleDeleteSession(sessionId: string) {
    setSessions((prev) => prev.filter((s) => s.id !== sessionId))
    if (activeSessionId === sessionId) {
      setActiveSessionId(null)
      setConversation([])
    }
  }

  const isInitialView = conversation.length === 0

  return (
    <div className="flex h-dvh overflow-hidden bg-white text-slate-800">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onNewChat={handleNewChat}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
      />

      <main className="flex min-w-0 flex-1 flex-col bg-[#fcfdfc]">
        <header className="flex h-20 shrink-0 items-center justify-between border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <button
              aria-label="Abrir menu lateral"
              className="grid size-10 place-items-center rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50 lg:hidden"
              onClick={() => setSidebarOpen(true)}
            >
              <Icon name="menu" />
            </button>
            <div>
              <div className="flex items-center gap-2">
                <p className="font-semibold text-slate-900">Assistente Pólis</p>
                <span className="hidden items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[0.65rem] font-semibold text-emerald-700 sm:inline-flex">
                  <Icon name="shield" className="size-3" />
                  Fontes oficiais
                </span>
                {!isInitialView && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[0.65rem] font-medium text-slate-600">
                    Conversa ativa
                  </span>
                )}
              </div>
              <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                <span className="size-1.5 rounded-full bg-emerald-500" />
                Online · Respostas imparciais e verificáveis
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!isInitialView && (
              <button
                onClick={handleNewChat}
                className="hidden items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 sm:inline-flex"
              >
                <Icon name="plus" className="size-3.5" />
                Nova conversa
              </button>
            )}
            <button
              className="grid size-10 place-items-center rounded-xl text-slate-500 transition hover:bg-slate-100"
              aria-label="Mais opções"
            >
              <Icon name="more" />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-5 pb-44 pt-8 sm:px-8 sm:pt-12 lg:px-12">
            {isInitialView ? (
              // 1. Visão Inicial Acolhedora com Hero e Sugestões
              <div className="animate-in fade-in duration-300">
                <section className="mx-auto max-w-3xl text-center">
                  <div className="mx-auto mb-6 grid size-12 place-items-center rounded-2xl border border-emerald-100 bg-emerald-50 text-emerald-700 shadow-sm shadow-emerald-900/10">
                    <PolisLogo className="size-7" />
                  </div>
                  <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-700">
                    Informação pública, sem complicação
                  </p>
                  <h1 className="text-balance font-serif text-3xl font-medium leading-tight tracking-tight text-slate-950 sm:text-4xl lg:text-[2.75rem]">
                    Como posso ajudar você a entender a política hoje?
                  </h1>
                  <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-slate-500 sm:text-base">
                    Tire dúvidas sobre cidadania, eleições e instituições com
                    respostas claras, contexto e fontes oficiais que você pode conferir.
                  </p>
                </section>

                <section
                  aria-label="Sugestões de perguntas"
                  className="mx-auto mt-10 grid max-w-3xl gap-3 sm:grid-cols-2"
                >
                  {suggestions.map((suggestion) => (
                    <button
                      className="group flex min-h-28 items-start gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-sm shadow-slate-900/[0.02] transition duration-200 hover:-translate-y-0.5 hover:border-emerald-200 hover:shadow-md hover:shadow-emerald-900/[0.05]"
                      key={suggestion.text}
                      onClick={() => handleSelectSuggestion(suggestion.text)}
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600 transition group-hover:bg-emerald-50 group-hover:text-emerald-700">
                        <Icon name={suggestion.icon} className="size-4.5" />
                      </span>
                      <span>
                        <span className="block text-[0.65rem] font-semibold uppercase tracking-[0.13em] text-slate-400">
                          {suggestion.eyebrow}
                        </span>
                        <span className="mt-1.5 block text-sm font-medium leading-5 text-slate-700 group-hover:text-slate-950">
                          {suggestion.text}
                        </span>
                      </span>
                    </button>
                  ))}
                </section>

                <div className="mx-auto mt-12 max-w-3xl rounded-xl border border-slate-100 bg-slate-50/70 p-4 text-center text-xs text-slate-500">
                  <span className="font-semibold text-slate-700">Verificação Baseada em Evidências:</span> O agente consulta datasets abertos do TSE, Câmara dos Deputados, Senado Federal e normativos legais antes de emitir qualquer veredito.
                </div>
              </div>
            ) : (
              // 2. Visão de Conversa Ativa Dinâmica
              <div className="mx-auto max-w-3xl space-y-6">
                {conversation.map((msg) =>
                  msg.role === "user" ? (
                    <div key={msg.id} className="flex justify-end animate-in fade-in slide-in-from-bottom-2 duration-200">
                      <div className="max-w-xl rounded-2xl rounded-br-md bg-emerald-700 px-4 py-3 text-sm leading-6 text-white shadow-sm">
                        {msg.text}
                      </div>
                    </div>
                  ) : (
                    <div key={msg.id} className="flex items-start gap-3 sm:gap-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
                      <div className="mt-1 grid size-9 shrink-0 place-items-center rounded-xl bg-emerald-700 text-white shadow-sm shadow-emerald-900/10">
                        <PolisLogo className="size-6" />
                      </div>
                      <article className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-slate-200 bg-white p-5 shadow-sm shadow-slate-900/[0.03] sm:p-6">
                        <div className="mb-4 flex items-center gap-2">
                          <p className="text-sm font-semibold text-slate-900">
                            Assistente Pólis
                          </p>
                          {msg.verdict && (
                            <span
                              className={`rounded-full px-2.5 py-0.5 text-[0.68rem] font-bold tracking-wide uppercase ${
                                msg.verdict === "VERDADEIRO"
                                  ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                                  : msg.verdict === "FALSO"
                                  ? "bg-rose-50 text-rose-800 border border-rose-200"
                                  : msg.verdict === "INCONCLUSIVO"
                                  ? "bg-amber-50 text-amber-800 border border-amber-200"
                                  : "bg-emerald-50 text-emerald-800 border border-emerald-200"
                              }`}
                            >
                              {msg.verdict}
                            </span>
                          )}
                        </div>
                        <div className="space-y-4 text-sm leading-6 text-slate-700">
                          <p>{msg.text}</p>
                          {msg.subdetails && msg.subdetails.length > 0 && (
                            <ul className="space-y-2.5 pt-1">
                              {msg.subdetails.map((detail, idx) => (
                                <li key={idx} className="flex gap-3">
                                  <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-emerald-600" />
                                  <span>{detail}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        {msg.sources && msg.sources.length > 0 && (
                          <div className="mt-6 border-t border-slate-100 pt-4">
                            <p className="mb-3 flex items-center gap-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.13em] text-slate-400">
                              <Icon name="shield" className="size-3.5" />
                              Fontes oficiais auditáveis
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {msg.sources.map((src, idx) => (
                                <SourceChip key={idx}>{src}</SourceChip>
                              ))}
                            </div>
                          </div>
                        )}
                      </article>
                    </div>
                  )
                )}

                {isLoading && (
                  <div className="flex items-start gap-3 sm:gap-4 animate-in fade-in duration-150">
                    <div className="mt-1 grid size-9 shrink-0 place-items-center rounded-xl bg-emerald-700 text-white animate-pulse">
                      <PolisLogo className="size-6" />
                    </div>
                    <div className="rounded-2xl rounded-tl-md border border-slate-200 bg-white p-4 text-sm text-slate-600 shadow-sm flex items-center gap-3">
                      <span className="size-2 rounded-full bg-emerald-500 animate-ping" />
                      Consultando bases e fontes normativas oficiais...
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )}
          </div>
        </div>

        {/* Barra de Envio sem clip de anexo e sem microfone */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-[#fcfdfc] via-[#fcfdfc] to-transparent px-4 pb-5 pt-12 sm:px-6 lg:left-[18rem]">
          <form
            className="pointer-events-auto mx-auto max-w-3xl"
            onSubmit={submitMessage}
          >
            <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 pl-4 shadow-xl shadow-slate-900/[0.07] ring-1 ring-slate-900/[0.02] focus-within:border-emerald-300 focus-within:ring-4 focus-within:ring-emerald-100/70">
              <textarea
                aria-label="Mensagem para o Assistente Pólis"
                className="min-h-10 max-h-32 flex-1 resize-none bg-transparent py-2.5 text-sm leading-5 text-slate-800 outline-none placeholder:text-slate-400"
                disabled={isLoading}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    event.currentTarget.form?.requestSubmit()
                  }
                }}
                placeholder="Pergunte sobre política, cidadania ou cheque uma alegação..."
                rows={1}
                value={message}
              />
              <button
                aria-label="Enviar mensagem"
                className="grid size-10 shrink-0 place-items-center rounded-xl bg-emerald-700 text-white shadow-sm transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
                disabled={!message.trim() || isLoading}
                type="submit"
              >
                <Icon name="arrow-up" className="size-5" />
              </button>
            </div>
            <p className="mt-2 text-center text-[0.65rem] text-slate-400">
              A Pólis checa dados oficiais e normativos. Verifique sempre informações importantes nas fontes primárias indicadas.
            </p>
          </form>
        </div>
      </main>
    </div>
  )
}
