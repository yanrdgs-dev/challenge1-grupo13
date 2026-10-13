// Lógica pura da página /status (sem React). Roda com `npm test` (node:test, sem dependências).
import assert from "node:assert/strict"
import { describe, it } from "node:test"

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
} from "./ingestionStatus.ts"

const NOW = new Date("2026-10-10T15:00:00Z")

function status(over: Partial<IngestionStatus> = {}): IngestionStatus {
  return {
    gerado_em: "2026-10-10T14:23:58+00:00",
    ultima_execucao: {
      iniciou_em: "2026-10-10T14:23:36+00:00",
      terminou_em: "2026-10-10T14:23:58+00:00",
      duracao_segundos: 22,
      resultado: "ok",
      exit_code: 0,
      fontes_com_novidade: [],
      total_novidades: 0,
      novidades_por_origem: {},
      novidades_adiadas: 0,
      build: "ignorado",
      falhas: [],
    },
    ultimo_sucesso_em: "2026-10-10T14:23:58+00:00",
    ultima_novidade: null,
    carga_pendente: false,
    dados_atualizados_em: "2026-10-10T14:19:06+00:00",
    fontes_registradas: 82,
    aguardando_build: 0,
    falhas_seguidas: 0,
    historico: [],
    ultimo_sucesso_ha_horas: 0.6,
    desatualizada: false,
    ...over,
  }
}

describe("statusLevel", () => {
  it("é ok quando a última execução passou e nada pende", () => {
    assert.equal(statusLevel(status()), "ok")
  })
  it("é desatualizada quando o backend marca desatualizada", () => {
    assert.equal(statusLevel(status({ desatualizada: true })), "desatualizada")
  })
  it("é falhou quando a última execução falhou", () => {
    const s = status()
    s.ultima_execucao!.resultado = "falhou"
    assert.equal(statusLevel(s), "falhou")
  })
  it("desatualizada tem prioridade sobre falhou", () => {
    const s = status({ desatualizada: true })
    s.ultima_execucao!.resultado = "falhou"
    assert.equal(statusLevel(s), "desatualizada")
  })
  it("é atenção com carga pendente ou falhas seguidas", () => {
    assert.equal(statusLevel(status({ carga_pendente: true })), "atencao")
    assert.equal(statusLevel(status({ falhas_seguidas: 1 })), "atencao")
  })
  it("é sem-dados quando não há status", () => {
    assert.equal(statusLevel(null), "sem-dados")
    assert.equal(statusLevel(status({ ultima_execucao: null })), "sem-dados")
  })
})

describe("summaryTitle", () => {
  it("traduz cada nível", () => {
    assert.match(summaryTitle("ok"), /em dia/i)
    assert.match(summaryTitle("atencao"), /atenção/i)
    assert.match(summaryTitle("falhou"), /falhou/i)
    assert.match(summaryTitle("desatualizada"), /desatualizad/i)
    assert.match(summaryTitle("sem-dados"), /ainda/i)
  })
})

describe("timeAgo", () => {
  it("minutos, horas e dias", () => {
    assert.equal(timeAgo("2026-10-10T14:55:00Z", NOW), "há 5 min")
    assert.equal(timeAgo("2026-10-10T13:00:00Z", NOW), "há 2 h")
    assert.equal(timeAgo("2026-10-07T15:00:00Z", NOW), "há 3 dias")
  })
  it("menos de um minuto vira agora há pouco", () => {
    assert.equal(timeAgo("2026-10-10T14:59:40Z", NOW), "agora há pouco")
  })
  it("data inválida ou ausente vira traço", () => {
    assert.equal(timeAgo(null, NOW), "—")
    assert.equal(timeAgo("lixo", NOW), "—")
  })
})

describe("formatDateTime", () => {
  it("usa o horário de Brasília em pt-BR", () => {
    assert.equal(formatDateTime("2026-10-10T14:23:58+00:00"), "10/10/2026 11:23")
  })
  it("ausente vira traço", () => {
    assert.equal(formatDateTime(null), "—")
  })
})

describe("formatDuration", () => {
  it("segundos e minutos", () => {
    assert.equal(formatDuration(22), "22 s")
    assert.equal(formatDuration(477), "7 min 57 s")
    assert.equal(formatDuration(120), "2 min")
    assert.equal(formatDuration(null), "—")
  })
})

describe("origens", () => {
  it("rótulos legíveis", () => {
    assert.equal(originLabel("camara"), "Câmara")
    assert.equal(originLabel("senado"), "Senado")
    assert.equal(originLabel("tse"), "TSE")
    assert.equal(originLabel("outra"), "outra")
  })
  it("tolera o campo ausente (JSON de um backend anterior à contagem por origem)", () => {
    assert.deepEqual(sortedOrigins(undefined), [])
    assert.deepEqual(sortedOrigins(null), [])
  })
  it("ordem fixa Câmara, Senado, TSE e depois as demais", () => {
    assert.deepEqual(sortedOrigins({ tse: 45, zeta: 1, camara: 26, senado: 11 }), [
      ["camara", 26],
      ["senado", 11],
      ["tse", 45],
      ["zeta", 1],
    ])
    assert.deepEqual(sortedOrigins({}), [])
  })
})

describe("describeBuild com novidades adiadas", () => {
  it("explica que as novidades do Senado esperam o próximo build", () => {
    assert.match(describeBuild("ignorado", 2), /senado/i)
    assert.match(describeBuild("ignorado", 2), /próximo build/i)
  })
  it("sem adiadas mantém o texto de sem novidades", () => {
    assert.match(describeBuild("ignorado", 0), /sem novidades/i)
    assert.match(describeBuild("ignorado"), /sem novidades/i)
  })
})

describe("describeBuild", () => {
  it("explica o que cada resultado de build significa", () => {
    assert.match(describeBuild("publicado"), /publicados/i)
    assert.match(describeBuild("ignorado"), /sem novidades/i)
    assert.match(describeBuild("falhou"), /não concluído/i)
  })
})
