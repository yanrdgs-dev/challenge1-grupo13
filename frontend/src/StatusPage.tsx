import { useEffect, useState } from "react"

import {
  describeBuild,
  formatDateTime,
  formatDuration,
  originLabel,
  sortedOrigins,
  statusLevel,
  summaryTitle,
  timeAgo,
  type IngestionStatus,
  type StatusLevel,
} from "./ingestionStatus.ts"

const REFRESH_MS = 60_000

const LEVEL_STYLE: Record<StatusLevel, { box: string; dot: string }> = {
  ok: { box: "border-emerald-200 bg-emerald-50 text-emerald-900", dot: "bg-emerald-600" },
  atencao: { box: "border-amber-200 bg-amber-50 text-amber-900", dot: "bg-amber-500" },
  falhou: { box: "border-rose-200 bg-rose-50 text-rose-900", dot: "bg-rose-600" },
  desatualizada: { box: "border-rose-200 bg-rose-50 text-rose-900", dot: "bg-rose-600" },
  "sem-dados": { box: "border-slate-200 bg-slate-50 text-slate-700", dot: "bg-slate-400" },
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; status: IngestionStatus }
  | { kind: "missing" }
  | { kind: "error"; message: string }

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-900/[0.04]">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
      <div className="mt-3 space-y-2 text-sm text-slate-700">{children}</div>
    </section>
  )
}

function OriginChips({ byOrigin }: { byOrigin: Record<string, number> | null | undefined }) {
  const entries = sortedOrigins(byOrigin)
  if (entries.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-2">
      {entries.map(([origin, count]) => (
        <li
          key={origin}
          className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-800"
        >
          {originLabel(origin)} · {count}
        </li>
      ))}
    </ul>
  )
}

function Result({ resultado }: { resultado: "ok" | "falhou" }) {
  return resultado === "ok" ? (
    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">OK</span>
  ) : (
    <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">Falhou</span>
  )
}

export function StatusBody({ status }: { status: IngestionStatus }) {
  const level = statusLevel(status)
  const style = LEVEL_STYLE[level]
  const run = status.ultima_execucao
  const news = status.ultima_novidade

  return (
    <div className="space-y-5">
      <div aria-live="polite" className={`flex items-start gap-3 rounded-2xl border p-5 ${style.box}`}>
        <span className={`mt-1.5 inline-block size-3 shrink-0 rounded-full ${style.dot}`} />
        <div>
          <p className="text-lg font-semibold">{summaryTitle(level)}</p>
          <p className="mt-1 text-sm">
            {run
              ? `Última verificação ${timeAgo(run.terminou_em)} (${formatDateTime(run.terminou_em)}). `
              : ""}
            Dados atualizados em {formatDateTime(status.dados_atualizados_em)}.
          </p>
          {status.desatualizada && (
            <p className="mt-1 text-sm font-medium">
              Sem execução bem-sucedida{" "}
              {status.ultimo_sucesso_ha_horas === null
                ? "registrada."
                : `há ${Math.floor(status.ultimo_sucesso_ha_horas)} h.`}
            </p>
          )}
          {status.carga_pendente && (
            <p className="mt-1 text-sm font-medium">
              Há dados baixados ainda não convertidos em parquet; o próximo build os publica.
            </p>
          )}
        </div>
      </div>

      {run && (
        <div className="grid gap-5 md:grid-cols-2">
          <Card title="Última execução">
            <p className="flex items-center gap-2">
              <Result resultado={run.resultado} />
              <span>
                terminou {timeAgo(run.terminou_em)} · {formatDateTime(run.terminou_em)}
              </span>
            </p>
            <p>Duração: {formatDuration(run.duracao_segundos)}</p>
            <p>Build: {describeBuild(run.build)}</p>
            {status.falhas_seguidas > 1 && (
              <p className="font-medium text-rose-700">{status.falhas_seguidas} execuções seguidas com falha.</p>
            )}
          </Card>

          <Card title="Novidades na última execução">
            {run.total_novidades === 0 ? (
              <p>Nenhuma novidade nas fontes.</p>
            ) : (
              <>
                <p className="text-base font-semibold text-slate-900">{run.total_novidades} fonte(s) atualizada(s)</p>
                <OriginChips byOrigin={run.novidades_por_origem} />
                {run.fontes_com_novidade.length > 0 && (
                  <details className="text-xs text-slate-500">
                    <summary className="cursor-pointer font-medium text-slate-600">
                      Ver fontes (mostrando {run.fontes_com_novidade.length} de {run.total_novidades})
                    </summary>
                    <ul className="mt-2 space-y-0.5 font-mono">
                      {run.fontes_com_novidade.map((id) => (
                        <li key={id}>{id}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )}
          </Card>

          <Card title="Última carga com novidade">
            {news ? (
              <>
                <p>
                  {timeAgo(news.em)} · {formatDateTime(news.em)}
                </p>
                <p className="font-semibold text-slate-900">{news.total} fonte(s)</p>
                <OriginChips byOrigin={news.por_origem} />
              </>
            ) : (
              <p>Nenhuma registrada ainda.</p>
            )}
          </Card>

          <Card title="Bases">
            <p>Fontes acompanhadas: {status.fontes_registradas}</p>
            <p>
              Último sucesso: {timeAgo(status.ultimo_sucesso_em)} ({formatDateTime(status.ultimo_sucesso_em)})
            </p>
          </Card>
        </div>
      )}

      {run && run.falhas.length > 0 && (
        <Card title="Falhas da última execução">
          <ul className="list-disc space-y-1 pl-5 text-rose-800">
            {run.falhas.map((falha) => (
              <li key={falha}>{falha}</li>
            ))}
          </ul>
        </Card>
      )}

      {status.historico.length > 0 && (
        <Card title={`Últimas ${status.historico.length} execuções`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="py-1 pr-4 font-semibold">Quando</th>
                  <th className="py-1 pr-4 font-semibold">Resultado</th>
                  <th className="py-1 pr-4 font-semibold">Novidades</th>
                  <th className="py-1 font-semibold">Build</th>
                </tr>
              </thead>
              <tbody>
                {[...status.historico].reverse().map((h, i) => (
                  <tr key={`${h.terminou_em}-${i}`} className="border-t border-slate-100">
                    <td className="py-1.5 pr-4">{formatDateTime(h.terminou_em)}</td>
                    <td className="py-1.5 pr-4">
                      <Result resultado={h.resultado} />
                    </td>
                    <td className="py-1.5 pr-4">{h.novidades}</td>
                    <td className="py-1.5">{h.build}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

export default function StatusPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" })
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  // Incrementar força uma nova consulta (botão "Atualizar") sem chamar setState direto dentro do efeito.
  const [reloads, setReloads] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    async function load() {
      try {
        const response = await fetch("/api/ingestion/status", {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        })
        if (response.status === 404) {
          setState({ kind: "missing" })
        } else if (!response.ok) {
          setState({ kind: "error", message: `O servidor respondeu ${response.status}.` })
        } else {
          setState({ kind: "ready", status: (await response.json()) as IngestionStatus })
        }
        setUpdatedAt(new Date())
      } catch (error) {
        if ((error as Error).name === "AbortError") return
        setState({ kind: "error", message: "Não foi possível consultar o servidor." })
      }
    }

    void load()
    const timer = setInterval(() => void load(), REFRESH_MS)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [reloads])

  return (
    <div className="min-h-screen bg-[#fcfdfc] text-slate-800">
      <header className="border-b border-slate-200/80 bg-white/90">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-5 sm:px-6">
          <div>
            <a href="/" className="text-xs font-semibold text-emerald-700 hover:underline">
              ← Voltar ao verificador
            </a>
            <h1 className="mt-1 text-xl font-semibold text-slate-900">Estado da ingestão de dados</h1>
            <p className="text-sm text-slate-500">Câmara, Senado e TSE: o que foi atualizado e quando.</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {updatedAt && <span>Consultado às {updatedAt.toLocaleTimeString("pt-BR")}</span>}
            <button
              type="button"
              onClick={() => setReloads((n) => n + 1)}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-50"
            >
              Atualizar
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        {state.kind === "loading" && <p className="text-sm text-slate-500">Carregando…</p>}
        {state.kind === "missing" && (
          <div aria-live="polite" className={`rounded-2xl border p-5 ${LEVEL_STYLE["sem-dados"].box}`}>
            <p className="text-lg font-semibold">{summaryTitle("sem-dados")}</p>
            <p className="mt-1 text-sm">A primeira execução da ingestão ainda não gravou o arquivo de estado.</p>
          </div>
        )}
        {state.kind === "error" && (
          <div role="alert" className={`rounded-2xl border p-5 ${LEVEL_STYLE.falhou.box}`}>
            <p className="font-semibold">{state.message}</p>
            <p className="mt-1 text-sm">A página tenta de novo sozinha a cada minuto.</p>
          </div>
        )}
        {state.kind === "ready" && <StatusBody status={state.status} />}
      </main>
    </div>
  )
}
