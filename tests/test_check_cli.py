"""CLI local: envia uma alegação ao router e mostra o veredito (sem abrir o site)."""

import io

import pytest

from scripts import check_cli

RESPONSE = {
    "claim": "O PL 2630/2020 foi aprovado?",
    "veredito": "VERDADEIRO",
    "confianca": "ALTA",
    "justificativa": "Conforme a Câmara dos Deputados, a urgência foi aprovada.",
    "fontes_primarias": ["Câmara dos Deputados - Dados Abertos"],
    "ferramentas_usadas": ["resolve_proposition", "get_proposition_vote_result"],
    "tool_usada": "get_proposition_vote_result",
    "regra_acionada": None,
    "dados_atualizados_em": "2026-10-10T14:21:12+00:00",
    "tempo_total_ms": 36123.4,
}


def test_format_response_shows_verdict_text_sources_tools_and_time():
    text = check_cli.format_response(RESPONSE)
    assert "VERDADEIRO" in text and "ALTA" in text
    assert "a urgência foi aprovada" in text
    assert "Câmara dos Deputados - Dados Abertos" in text
    assert "resolve_proposition" in text and "get_proposition_vote_result" in text
    assert "36,1 s" in text or "36.1 s" in text
    assert "2026-10-10" in text


def test_format_response_omits_missing_parts_without_crashing():
    text = check_cli.format_response({"veredito": "INCONCLUSIVO", "justificativa": "Sem evidência."})
    assert "INCONCLUSIVO" in text and "Sem evidência." in text
    assert "Fontes" not in text and "None" not in text


def test_format_response_shows_the_rule_when_a_guardrail_answered():
    text = check_cli.format_response({**RESPONSE, "veredito": "INCONCLUSIVO", "regra_acionada": "sem_ferramenta_aplicavel",
                                      "ferramentas_usadas": [], "fontes_primarias": []})
    assert "sem_ferramenta_aplicavel" in text


def test_session_sends_each_line_and_prints_the_answer_until_exit():
    sent, out = [], io.StringIO()
    lines = iter(["O PL 2630/2020 foi aprovado?", "", "sair"])

    check_cli.session(
        "http://r", ask=lambda url, claim: sent.append((url, claim)) or RESPONSE,
        read=lambda prompt: next(lines), out=out,
    )

    assert sent == [("http://r", "O PL 2630/2020 foi aprovado?")]          # linha vazia é ignorada
    assert "VERDADEIRO" in out.getvalue()


def test_session_ends_on_eof_and_ctrl_c():
    def eof(prompt):
        raise EOFError

    check_cli.session("http://r", ask=lambda *a: RESPONSE, read=eof, out=io.StringIO())

    def interrupt(prompt):
        raise KeyboardInterrupt

    check_cli.session("http://r", ask=lambda *a: RESPONSE, read=interrupt, out=io.StringIO())


def test_session_reports_a_failed_request_and_keeps_going():
    out, lines = io.StringIO(), iter(["primeira", "segunda", "sair"])
    calls = []

    def ask(url, claim):
        calls.append(claim)
        if claim == "primeira":
            raise RuntimeError("503 Service Unavailable")
        return RESPONSE

    check_cli.session("http://r", ask=ask, read=lambda p: next(lines), out=out)

    assert calls == ["primeira", "segunda"]
    assert "503 Service Unavailable" in out.getvalue() and "VERDADEIRO" in out.getvalue()


def test_one_shot_with_url_does_not_start_services_and_prints_the_answer(capsys):
    code = check_cli.main(
        ["--url", "http://localhost:8000", "O PL 2630/2020 foi aprovado?"],
        ask=lambda url, claim: RESPONSE, start_services=lambda *a, **k: pytest.fail("não deveria subir serviços"),
    )
    assert code == 0
    assert "VERDADEIRO" in capsys.readouterr().out


def test_without_url_it_starts_local_services_and_runs_the_session():
    started = {}

    def start_services(session, argv):
        started["argv"] = argv
        return session("http://localhost:18000")

    ran = {}
    code = check_cli.main(
        [], ask=lambda *a: RESPONSE, start_services=start_services,
        interactive=lambda url: ran.setdefault("url", url) and 0,
    )

    assert ran["url"] == "http://localhost:18000"
    assert code == 0


def test_ask_posts_the_claim_to_the_check_endpoint_and_returns_json():
    import httpx

    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), request.content
        return httpx.Response(200, json={"veredito": "FALSO"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    data = check_cli.ask("http://r", "uma alegação", client=client)

    assert seen["url"] == "http://r/check" and b"uma alega" in seen["body"]
    assert data == {"veredito": "FALSO"}


def test_ask_raises_a_readable_error_on_http_failure():
    import httpx

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"detail": "LLM fora"})))
    with pytest.raises(RuntimeError, match="503"):
        check_cli.ask("http://r", "x", client=client)
