import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"

type IconName =
  | "alert-triangle"
  | "archive"
  | "arrow-up"
  | "ballot"
  | "book"
  | "calendar"
  | "check-circle"
  | "chevron-down"
  | "chevron-up"
  | "close"
  | "external"
  | "file"
  | "link"
  | "menu"
  | "message"
  | "more"
  | "newspaper"
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
    "alert-triangle": (
      <>
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <path d="M12 9v4M12 17h.01" />
      </>
    ),
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
    calendar: (
      <>
        <path d="M8 2v4M16 2v4M3 10h18" />
        <rect x="3" y="4" width="18" height="18" rx="2" />
      </>
    ),
    "check-circle": (
      <>
        <circle cx="12" cy="12" r="10" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    "chevron-down": <path d="m8 10 4 4 4-4" />,
    "chevron-up": <path d="m18 15-6-6-6 6" />,
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
    link: (
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
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
    newspaper: (
      <>
        <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2" />
        <path d="M18 14h-8M15 18h-5M10 6h8v4h-8z" />
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

// Schemas para a Verificação Integral por Link (Task 4.5)
interface VerifiedClaimItem {
  claim: string
  category?: string
  target_entity?: string
  verdict: "VERDADEIRO" | "FALSO" | "INCONCLUSIVO" | string
  confidence: string
  explanation: string
  sources: string[]
  rule_matched?: string
  latency_seconds?: Record<string, number>
}

interface VerifyUrlResultData {
  url: string
  success: boolean
  message: string
  article?: {
    title?: string
    author?: string
    publish_date?: string
    url: string
  }
  claims_count: number
  claims: VerifiedClaimItem[]
  overall_verdict: "VERDADEIRO" | "FALSO" | "PARCIALMENTE_FALSO" | "ENGANOSO" | "INCONCLUSIVO" | string
  reliability_score: number
  executive_summary?: string
  latency_seconds: {
    scraping: number
    claim_extraction: number
    batch_verification: number
    total: number
  }
  timeout_exceeded: boolean
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

function getDomainFromUrl(url: string): string {
  try {
    const parsed = new URL(url)
    return parsed.hostname.replace(/^www\./, "")
  } catch {
    return "Veículo de Imprensa"
  }
}

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
  onSelectTab,
}: {
  open: boolean
  onClose: () => void
  onNewChat: () => void
  sessions: ChatSession[]
  activeSessionId: string | null
  onSelectSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
  onSelectTab?: (tab: "chat" | "link") => void
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
              <p className="text-[0.68rem] font-medium text-emerald-800">
                Fact-Checking Cidadão
              </p>
            </div>
          </div>
          <button
            aria-label="Fechar menu"
            className="grid size-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 lg:hidden"
            onClick={onClose}
          >
            <Icon name="close" className="size-4" />
          </button>
        </div>

        <div className="space-y-2 px-4 pb-3">
          <button
            onClick={() => {
              onNewChat()
              onSelectTab?.("chat")
              onClose()
            }}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-700 px-4 py-2.5 text-xs font-semibold text-white shadow-sm shadow-emerald-950/10 transition hover:bg-emerald-800"
          >
            <Icon name="plus" className="size-4" />
            Nova consulta manual
          </button>

          <button
            onClick={() => {
              onSelectTab?.("link")
              onClose()
            }}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50/80 px-4 py-2 text-xs font-semibold text-emerald-900 transition hover:bg-emerald-100"
          >
            <Icon name="link" className="size-4 text-emerald-700" />
            Checar Notícia por Link
          </button>
        </div>

        {sessions.length > 0 && (
          <div className="px-4 pb-2">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200/80 bg-white px-2.5 py-1.5 text-xs text-slate-600 focus-within:border-emerald-500">
              <Icon name="search" className="size-3.5 text-slate-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Buscar no histórico..."
                className="w-full bg-transparent outline-none placeholder:text-slate-400"
              />
              {searchTerm && (
                <button onClick={() => setSearchTerm("")} className="text-slate-400 hover:text-slate-600">
                  <Icon name="close" className="size-3" />
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
                              onSelectTab?.("chat")
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
  
  // Controle de Abas Principais (Task 4.5)
  const [activeTab, setActiveTab] = useState<"chat" | "link">("chat")

  // Estado do Chat Manual
  const [message, setMessage] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<Suggestion[]>(defaultSuggestions)
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

  // Estado da Verificação por Link (Task 4.5)
  const [urlInput, setUrlInput] = useState("")
  const [isAnalyzingUrl, setIsAnalyzingUrl] = useState(false)
  const [urlError, setUrlError] = useState<string | null>(null)
  const [urlResult, setUrlResult] = useState<VerifyUrlResultData | null>(null)
  const [expandedClaims, setExpandedClaims] = useState<Record<number, boolean>>({ 0: true })

  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try {
      localStorage.setItem("polis_chat_sessions", JSON.stringify(sessions))
    } catch {
      // Ignora erro de cota de armazenamento
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
        // Fallback defaultSuggestions
      })
  }, [])

  useEffect(() => {
    if (activeTab === "chat") {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [conversation, isLoading, activeTab])

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

  // Ação de Verificação Integral por Link (Task 4.5)
  async function handleVerifyUrl(targetUrl?: string) {
    const rawUrl = (targetUrl || urlInput).trim()
    if (!rawUrl || isAnalyzingUrl) return

    if (!rawUrl.startsWith("http://") && !rawUrl.startsWith("https://")) {
      setUrlError("Por favor, insira uma URL válida iniciando com http:// ou https://")
      return
    }

    setIsAnalyzingUrl(true)
    setUrlError(null)
    setUrlResult(null)

    try {
      const response = await fetch("/api/v1/verify-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: rawUrl }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || `Erro HTTP ${response.status} ao analisar notícia.`)
      }

      setUrlResult(data)
      // Expande a primeira alegação por padrão para demonstrar interatividade
      setExpandedClaims({ 0: true })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Falha inesperada ao comunicar com o servidor."
      setUrlError(msg)
    } finally {
      setIsAnalyzingUrl(false)
    }
  }

  function toggleClaimAccordion(index: number) {
    setExpandedClaims((prev) => ({
      ...prev,
      [index]: !prev[index],
    }))
  }

  function submitChatMessage(event: FormEvent) {
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

  const isInitialChatView = conversation.length === 0

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
        onSelectTab={setActiveTab}
      />

      <main className="flex min-w-0 flex-1 flex-col bg-[#fcfdfc]">
        {/* Cabeçalho Principal com Seletor de Abas Integrado */}
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
                <span className="hidden items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[0.65rem] font-semibold text-emerald-700 sm:inline-flex">
                  <Icon name="shield" className="size-3" />
                  Fontes oficiais
                </span>
              </div>
              <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                <span className="size-1.5 rounded-full bg-emerald-500" />
                Online · Auditoria automatizada de fatos
              </p>
            </div>
          </div>

          {/* Seletor de Abas (Task 4.5) */}
          <div className="flex items-center gap-1 rounded-xl border border-slate-200/80 bg-slate-100/90 p-1">
            <button
              id="tab-manual-claim"
              type="button"
              onClick={() => setActiveTab("chat")}
              className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === "chat"
                  ? "bg-white text-slate-900 shadow-sm shadow-slate-900/5"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Icon name="message" className="size-3.5" />
              <span>Checar Afirmação</span>
            </button>
            <button
              id="tab-news-link"
              type="button"
              onClick={() => setActiveTab("link")}
              className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === "link"
                  ? "bg-white text-emerald-900 shadow-sm shadow-slate-900/5"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Icon name="link" className="size-3.5 text-emerald-700" />
              <span>Checar Notícia por Link</span>
              <span className="rounded-full bg-emerald-100 px-1.5 py-0.2 text-[0.6rem] font-bold text-emerald-800">
                Novo
              </span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            {activeTab === "chat" && !isInitialChatView && (
              <button
                onClick={handleNewChat}
                className="hidden items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 sm:inline-flex"
              >
                <Icon name="plus" className="size-3.5" />
                Nova consulta
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

        {/* =========================================================================
            ABA 1: CHECAGEM MANUAL DE AFIRMAÇÕES (CHAT CONVENCIONAL)
        ========================================================================= */}
        {activeTab === "chat" && (
          <>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-5xl px-5 pb-44 pt-8 sm:px-8 sm:pt-12 lg:px-12">
                {isInitialChatView ? (
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

            {/* Barra de Envio do Chat */}
            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-[#fcfdfc] via-[#fcfdfc] to-transparent px-4 pb-5 pt-12 sm:px-6 lg:left-[18rem]">
              <form
                className="pointer-events-auto mx-auto max-w-3xl"
                onSubmit={submitChatMessage}
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
          </>
        )}

        {/* =========================================================================
            ABA 2: CHECAGEM AUTOMATIZADA DE NOTÍCIA POR LINK (Task 4.5)
        ========================================================================= */}
        {activeTab === "link" && (
          <div className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-5xl px-5 pb-20 pt-8 sm:px-8 sm:pt-10 lg:px-12">
              {/* Header Editorial da Aba de Links */}
              <section className="mx-auto mb-8 max-w-3xl text-center">
                <div className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-800 shadow-sm shadow-emerald-900/10">
                  <Icon name="link" className="size-6" />
                </div>
                <h2 className="font-serif text-2xl font-medium tracking-tight text-slate-950 sm:text-3xl">
                  Auditoria Integral de Notícias por URL
                </h2>
                <p className="mt-2 text-sm leading-relaxed text-slate-500">
                  Cole o link de uma matéria jornalística para extrair suas alegações atômicas, auditar cada ponto contra dados abertos governamentais e gerar o selo editorial de confiabilidade.
                </p>
              </section>

              {/* Formulário de Ingestão de URL */}
              <div className="mx-auto max-w-3xl rounded-2xl border border-slate-200/90 bg-white p-4 shadow-sm sm:p-5">
                <form
                  onSubmit={(e) => {
                    e.preventDefault()
                    handleVerifyUrl()
                  }}
                  className="space-y-3"
                >
                  <label htmlFor="url-input" className="block text-xs font-semibold uppercase tracking-wider text-slate-600">
                    URL da Matéria Jornalística
                  </label>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <div className="relative flex-1">
                      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-slate-400">
                        <Icon name="link" className="size-4" />
                      </div>
                      <input
                        id="url-input"
                        type="url"
                        value={urlInput}
                        onChange={(e) => setUrlInput(e.target.value)}
                        placeholder="https://g1.globo.com/politica/noticia/..."
                        disabled={isAnalyzingUrl}
                        className="w-full rounded-xl border border-slate-200 bg-slate-50/50 py-3 pl-10 pr-4 text-sm text-slate-800 outline-none transition focus:border-emerald-500 focus:bg-white focus:ring-4 focus:ring-emerald-100/60"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={!urlInput.trim() || isAnalyzingUrl}
                      className="flex items-center justify-center gap-2 rounded-xl bg-emerald-700 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
                    >
                      {isAnalyzingUrl ? (
                        <>
                          <span className="size-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                          <span>Auditando...</span>
                        </>
                      ) : (
                        <>
                          <Icon name="shield" className="size-4" />
                          <span>Checar Notícia</span>
                        </>
                      )}
                    </button>
                  </div>

                  {/* Exemplos Rápidos de Teste */}
                  <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs text-slate-500">
                    <span className="font-medium text-slate-600">Exemplos rápidos:</span>
                    <button
                      type="button"
                      onClick={() => {
                        const url = "https://g1.globo.com/politica/noticia/2023/10/gastos-parlamentares-ceap.ghtml"
                        setUrlInput(url)
                        handleVerifyUrl(url)
                      }}
                      className="rounded-lg bg-slate-100 px-2.5 py-1 text-[0.72rem] text-slate-700 hover:bg-emerald-50 hover:text-emerald-800 transition"
                    >
                      G1 · Gastos da CEAP
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        const url = "https://agenciabrasil.ebc.com.br/politica/noticia/2023-11/senado-aprova-reforma-tributaria"
                        setUrlInput(url)
                        handleVerifyUrl(url)
                      }}
                      className="rounded-lg bg-slate-100 px-2.5 py-1 text-[0.72rem] text-slate-700 hover:bg-emerald-50 hover:text-emerald-800 transition"
                    >
                      Agência Brasil · Votação PEC 45
                    </button>
                  </div>
                </form>

                {/* Exibição de Erros de Ingestão/Scraping */}
                {urlError && (
                  <div className="mt-4 flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800 animate-in fade-in duration-200">
                    <Icon name="alert-triangle" className="size-4.5 shrink-0 text-rose-600 mt-0.5" />
                    <div>
                      <p className="font-semibold">Não foi possível auditar a notícia</p>
                      <p className="mt-0.5 text-rose-700">{urlError}</p>
                    </div>
                  </div>
                )}
              </div>

              {/* Indicador de Carregamento com Etapas Animadas */}
              {isAnalyzingUrl && (
                <div className="mx-auto mt-8 max-w-3xl rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm animate-in fade-in duration-200">
                  <div className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-emerald-50 text-emerald-700 animate-pulse">
                    <PolisLogo className="size-7" />
                  </div>
                  <h3 className="text-base font-semibold text-slate-900">
                    Executando Pipeline de Fact-Checking
                  </h3>
                  <p className="mt-1 text-xs text-slate-500">
                    Processando o conteúdo jornalístico com transparência e evidências rastreáveis
                  </p>

                  <div className="mx-auto mt-6 max-w-md space-y-2.5 text-left text-xs text-slate-600">
                    <div className="flex items-center gap-2.5 rounded-lg bg-slate-50 p-2.5">
                      <span className="size-2 rounded-full bg-emerald-500 animate-ping" />
                      <span>1. Extraindo corpo editorial e metadados via Trafilatura</span>
                    </div>
                    <div className="flex items-center gap-2.5 rounded-lg bg-slate-50 p-2.5">
                      <span className="size-2 rounded-full bg-emerald-500" />
                      <span>2. Decompondo alegações atômicas e filtrando adjetivações retóricas</span>
                    </div>
                    <div className="flex items-center gap-2.5 rounded-lg bg-slate-50 p-2.5">
                      <span className="size-2 rounded-full bg-emerald-500" />
                      <span>3. Auditando dados públicos oficiais e calculando confiabilidade</span>
                    </div>
                  </div>
                </div>
              )}

              {/* =====================================================================
                  RESULTADOS DA AUDITORIA DA NOTÍCIA (Task 4.5)
              ===================================================================== */}
              {urlResult && (
                <div className="mx-auto mt-8 max-w-3xl space-y-6 animate-in fade-in duration-300">
                  {/* 1. Metadados Extraídos da Matéria */}
                  <article className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm sm:p-6">
                    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-0.5 font-semibold text-slate-700">
                        <Icon name="newspaper" className="size-3.5" />
                        {getDomainFromUrl(urlResult.url)}
                      </span>
                      {urlResult.article?.publish_date && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-slate-600">
                          <Icon name="calendar" className="size-3.5" />
                          {urlResult.article.publish_date}
                        </span>
                      )}
                      {urlResult.article?.author && (
                        <span className="text-slate-500">
                          Por: <strong className="font-medium text-slate-700">{urlResult.article.author}</strong>
                        </span>
                      )}
                    </div>

                    <h3 className="font-serif text-xl font-medium leading-snug text-slate-950 sm:text-2xl">
                      {urlResult.article?.title || "Matéria Jornalística Analisada"}
                    </h3>

                    <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs">
                      <a
                        href={urlResult.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 font-semibold text-emerald-800 hover:text-emerald-950 hover:underline"
                      >
                        Abrir matéria original na íntegra
                        <Icon name="external" className="size-3.5" />
                      </a>
                      <span className="text-slate-400">
                        Tempo de processamento: {urlResult.latency_seconds.total}s
                      </span>
                    </div>
                  </article>

                  {/* 2. Selo Final Consolidado da Matéria Emitido pelo Agregador */}
                  <section className={`rounded-2xl border p-6 shadow-sm transition ${
                    urlResult.overall_verdict === "VERDADEIRO"
                      ? "border-emerald-200 bg-emerald-50/70"
                      : urlResult.overall_verdict === "ENGANOSO" || urlResult.overall_verdict === "PARCIALMENTE_FALSO"
                      ? "border-amber-200 bg-amber-50/70"
                      : urlResult.overall_verdict === "FALSO"
                      ? "border-rose-200 bg-rose-50/70"
                      : "border-slate-200 bg-slate-50/70"
                  }`}>
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex items-center gap-3.5">
                        <div className={`grid size-12 shrink-0 place-items-center rounded-2xl ${
                          urlResult.overall_verdict === "VERDADEIRO"
                            ? "bg-emerald-600 text-white shadow-md shadow-emerald-900/10"
                            : urlResult.overall_verdict === "ENGANOSO" || urlResult.overall_verdict === "PARCIALMENTE_FALSO"
                            ? "bg-amber-600 text-white shadow-md shadow-amber-900/10"
                            : urlResult.overall_verdict === "FALSO"
                            ? "bg-rose-600 text-white shadow-md shadow-rose-900/10"
                            : "bg-slate-600 text-white shadow-md shadow-slate-900/10"
                        }`}>
                          <Icon
                            name={
                              urlResult.overall_verdict === "VERDADEIRO"
                                ? "check-circle"
                                : urlResult.overall_verdict === "FALSO" || urlResult.overall_verdict === "ENGANOSO"
                                ? "alert-triangle"
                                : "search"
                            }
                            className="size-7"
                          />
                        </div>
                        <div>
                          <span className="block text-[0.65rem] font-bold uppercase tracking-[0.14em] text-slate-500">
                            Selo Consolidado de Fact-Checking
                          </span>
                          <h4 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
                            {urlResult.overall_verdict === "VERDADEIRO" && "MATÉRIA CONFIÁVEL"}
                            {urlResult.overall_verdict === "ENGANOSO" && "MATÉRIA ENGANOSA"}
                            {urlResult.overall_verdict === "PARCIALMENTE_FALSO" && "PARCIALMENTE FALSA"}
                            {urlResult.overall_verdict === "FALSO" && "MATÉRIA FALSA"}
                            {urlResult.overall_verdict === "INCONCLUSIVO" && "CONTEÚDO INCONCLUSIVO"}
                          </h4>
                        </div>
                      </div>

                      {/* Índice de Confiabilidade Calculado */}
                      <div className="rounded-xl border border-white/80 bg-white/90 p-3 text-center shadow-xs sm:min-w-36">
                        <span className="block text-[0.65rem] font-semibold uppercase tracking-wider text-slate-400">
                          Confiabilidade Factual
                        </span>
                        <span className={`text-2xl font-black ${
                          urlResult.reliability_score >= 80
                            ? "text-emerald-700"
                            : urlResult.reliability_score >= 50
                            ? "text-amber-700"
                            : "text-rose-700"
                        }`}>
                          {urlResult.reliability_score}%
                        </span>
                        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              urlResult.reliability_score >= 80
                                ? "bg-emerald-600"
                                : urlResult.reliability_score >= 50
                                ? "bg-amber-500"
                                : "bg-rose-500"
                            }`}
                            style={{ width: `${Math.max(5, urlResult.reliability_score)}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Resumo Executivo em 2 a 3 Parágrafos */}
                    {urlResult.executive_summary && (
                      <div className="mt-5 rounded-xl border border-white/90 bg-white/80 p-4 text-xs leading-relaxed text-slate-700 sm:text-sm">
                        <p className="mb-2 text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">
                          Síntese Executiva do Agregador
                        </p>
                        <div className="space-y-3 font-serif">
                          {urlResult.executive_summary.split("\n\n").map((paragrafo, idx) => (
                            <p key={idx}>{paragrafo}</p>
                          ))}
                        </div>
                      </div>
                    )}
                  </section>

                  {/* 3. Listagem Interativa das Afirmações Extraídas (Accordion) */}
                  <section className="space-y-3">
                    <div className="flex items-center justify-between px-1">
                      <div>
                        <h4 className="text-sm font-bold text-slate-900">
                          Alegações Atômicas Auditadas ({urlResult.claims_count})
                        </h4>
                        <p className="text-xs text-slate-500">
                          Expanda cada afirmação para inspecionar os vereditos, fontes oficiais e justificativas técnicas.
                        </p>
                      </div>
                      <span className="text-xs font-medium text-slate-400">
                        {urlResult.claims.length} verificações
                      </span>
                    </div>

                    {urlResult.claims.length === 0 ? (
                      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center text-xs text-slate-500">
                        Nenhuma alegação factual atômica verificável foi extraída do artigo.
                      </div>
                    ) : (
                      <div className="space-y-2.5">
                        {urlResult.claims.map((claim, idx) => {
                          const isExpanded = !!expandedClaims[idx]
                          return (
                            <div
                              key={idx}
                              className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs transition hover:border-slate-300"
                            >
                              <button
                                type="button"
                                onClick={() => toggleClaimAccordion(idx)}
                                className="flex w-full items-start justify-between gap-3 p-4 text-left transition hover:bg-slate-50/70"
                              >
                                <div className="space-y-1.5 min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span
                                      className={`rounded-full px-2.5 py-0.5 text-[0.65rem] font-extrabold uppercase tracking-wide ${
                                        claim.verdict === "VERDADEIRO"
                                          ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                                          : claim.verdict === "FALSO"
                                          ? "bg-rose-50 text-rose-800 border border-rose-200"
                                          : "bg-amber-50 text-amber-800 border border-amber-200"
                                      }`}
                                    >
                                      {claim.verdict}
                                    </span>
                                    {claim.category && (
                                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[0.65rem] font-semibold text-slate-600">
                                        {claim.category}
                                      </span>
                                    )}
                                    {claim.target_entity && (
                                      <span className="text-[0.68rem] text-slate-500">
                                        Alvo: <strong className="font-medium text-slate-700">{claim.target_entity}</strong>
                                      </span>
                                    )}
                                  </div>
                                  <p className="text-sm font-medium leading-snug text-slate-900">
                                    "{claim.claim}"
                                  </p>
                                </div>
                                <div className="mt-1 text-slate-400">
                                  <Icon
                                    name={isExpanded ? "chevron-up" : "chevron-down"}
                                    className="size-4"
                                  />
                                </div>
                              </button>

                              {/* Conteúdo Detalhado Expandido */}
                              {isExpanded && (
                                <div className="border-t border-slate-100 bg-slate-50/50 p-4 text-xs leading-relaxed text-slate-700 space-y-3 animate-in fade-in duration-150">
                                  <div>
                                    <span className="block font-semibold uppercase tracking-wider text-[0.65rem] text-slate-400">
                                      Explicação Técnica
                                    </span>
                                    <p className="mt-1 text-slate-800">{claim.explanation}</p>
                                  </div>

                                  {claim.rule_matched && (
                                    <div className="rounded-lg bg-white p-2.5 border border-slate-200/80 text-[0.72rem]">
                                      <span className="font-semibold text-slate-600">Raciocínio da Auditoria: </span>
                                      <span className="text-slate-500">{claim.rule_matched}</span>
                                    </div>
                                  )}

                                  {claim.sources && claim.sources.length > 0 && (
                                    <div className="pt-1">
                                      <span className="mb-2 block font-semibold uppercase tracking-wider text-[0.65rem] text-slate-400">
                                        Fontes Oficiais Consultadas
                                      </span>
                                      <div className="flex flex-wrap gap-1.5">
                                        {claim.sources.map((src, sIdx) => (
                                          <SourceChip key={sIdx}>{src}</SourceChip>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </section>

                  {/* Ação para Nova Verificação */}
                  <div className="pt-2 text-center">
                    <button
                      type="button"
                      onClick={() => {
                        setUrlResult(null)
                        setUrlInput("")
                      }}
                      className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
                    >
                      <Icon name="link" className="size-3.5 text-slate-500" />
                      Analisar outra notícia por link
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
