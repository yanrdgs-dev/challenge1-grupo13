// Estado da ingestão das bases públicas: tipos do JSON de GET /api/ingestion/status e a lógica pura da
// página /status. Sem React nem DOM, para rodar em `npm test` (node:test). Um teste em Python confere que
// estas interfaces têm exatamente as chaves que o backend devolve.

export interface RunSummary {
  iniciou_em: string | null
  terminou_em: string | null
  duracao_segundos: number | null
  resultado: "ok" | "falhou"
  exit_code: number | null
  fontes_com_novidade: string[]
  total_novidades: number
  novidades_por_origem: Record<string, number>
  build: "publicado" | "ignorado" | "falhou"
  falhas: string[]
}

export interface LatestNews {
  em: string
  total: number
  por_origem: Record<string, number>
  fontes: string[]
}

export interface HistoryEntry {
  terminou_em: string | null
  resultado: "ok" | "falhou"
  novidades: number
  build: "publicado" | "ignorado" | "falhou"
}

export interface IngestionStatus {
  gerado_em: string
  ultima_execucao: RunSummary | null
  ultimo_sucesso_em: string | null
  ultima_novidade: LatestNews | null
  carga_pendente: boolean
  dados_atualizados_em: string | null
  fontes_registradas: number
  falhas_seguidas: number
  historico: HistoryEntry[]
  ultimo_sucesso_ha_horas: number | null
  desatualizada: boolean
}

export type StatusLevel = "ok" | "atencao" | "falhou" | "desatualizada" | "sem-dados"

export function statusLevel(status: IngestionStatus | null): StatusLevel {
  if (!status || !status.ultima_execucao) return "sem-dados"
  if (status.desatualizada) return "desatualizada"
  if (status.ultima_execucao.resultado === "falhou") return "falhou"
  if (status.carga_pendente || status.falhas_seguidas > 0) return "atencao"
  return "ok"
}

export function summaryTitle(level: StatusLevel): string {
  switch (level) {
    case "ok":
      return "Ingestão em dia"
    case "atencao":
      return "Atenção: há algo a acompanhar"
    case "falhou":
      return "A última execução falhou"
    case "desatualizada":
      return "Dados desatualizados"
    case "sem-dados":
      return "A ingestão ainda não publicou o estado"
  }
}

export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—"
  const moment = new Date(iso)
  if (Number.isNaN(moment.getTime())) return "—"
  const seconds = Math.max(0, (now.getTime() - moment.getTime()) / 1000)
  if (seconds < 60) return "agora há pouco"
  if (seconds < 3600) return `há ${Math.floor(seconds / 60)} min`
  if (seconds < 48 * 3600) return `há ${Math.floor(seconds / 3600)} h`
  return `há ${Math.floor(seconds / 86400)} dias`
}

const BRASILIA = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
})

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const moment = new Date(iso)
  if (Number.isNaN(moment.getTime())) return "—"
  const p = Object.fromEntries(BRASILIA.formatToParts(moment).map((part) => [part.type, part.value]))
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—"
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`
}

const ORIGIN_ORDER = ["camara", "senado", "tse"]
const ORIGIN_LABELS: Record<string, string> = { camara: "Câmara", senado: "Senado", tse: "TSE" }

export function originLabel(origin: string): string {
  return ORIGIN_LABELS[origin] ?? origin
}

export function sortedOrigins(byOrigin: Record<string, number>): Array<[string, number]> {
  const rank = (origin: string) => {
    const i = ORIGIN_ORDER.indexOf(origin)
    return i === -1 ? ORIGIN_ORDER.length : i
  }
  return Object.entries(byOrigin).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
}

export function describeBuild(build: "publicado" | "ignorado" | "falhou"): string {
  switch (build) {
    case "publicado":
      return "Parquets reconstruídos e publicados"
    case "ignorado":
      return "Ignorado: sem novidades e parquets já publicados"
    case "falhou":
      return "Build não concluído; os dados em produção continuam os da carga anterior"
  }
}
