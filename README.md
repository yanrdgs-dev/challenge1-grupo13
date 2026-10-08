# challenge1-grupo13

## Ambiente de desenvolvimento

O repositório usa o [uv](https://docs.astral.sh/uv/) como package manager. As dependências ficam em `pyproject.toml` e as versões travadas em `uv.lock`.

```bash
uv sync                      # cria .venv com Python 3.11 + dependências + grupo dev
uv sync --group eda          # inclui pandas/matplotlib/seaborn para os scripts de EDA
uv run pytest                # roda a suíte de testes
uv run uvicorn src.services.router_service:app --reload

uv add <pacote>              # nova dependência de produção
uv add --dev <pacote>        # nova dependência de teste/dev
```
