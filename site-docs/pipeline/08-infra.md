# Etapa 8 — Infraestrutura (Docker & Kubernetes)

## Objetivo

Empacotar os microsserviços em containers Docker e orquestrar com Kubernetes para deploy estável em ambiente de demonstração.

---

## Docker

O projeto possui dois `Dockerfiles` otimizados usando **uv** como package manager para builds determinísticos e reprodutíveis.

### Imagens disponíveis

| Imagem | Dockerfile | Porta | Serviço |
|---|---|---|---|
| `factcheck-router:latest` | `docker/Dockerfile.router` | `8000` | Roteador + Tools |
| `factcheck-judge:latest` | `docker/Dockerfile.judge` | `8000` (interno) | Sintetizador |

### Build das imagens

```bash
# Construir ambas as imagens
docker build -f docker/Dockerfile.router -t factcheck-router:latest .
docker build -f docker/Dockerfile.judge -t factcheck-judge:latest .
```

### Otimizações aplicadas

```dockerfile
# Usa uv para instalação determinística (uv.lock)
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/

# Instala somente dependências de produção (sem dev/eda)
RUN uv sync --frozen --no-dev --no-install-project

# Cache do bytecode Python pré-compilado
ENV UV_COMPILE_BYTECODE=1
```

---

## Docker Compose (ambiente local)

Orquestra os dois microsserviços numa rede interna Docker, apontando o Ollama para o host da máquina.

```bash
# Subir todo o stack
docker compose up -d

# Ver status
docker compose ps

# Ver logs em tempo real
docker compose logs -f router-service

# Parar tudo
docker compose down
```

### Topologia do Compose

```yaml
services:
  judge-service:
    image: factcheck-judge:latest
    ports: ["8001:8000"]
    environment:
      OLLAMA_BASE_URL: http://host.docker.internal:11434
      JUDGE_MODEL: qwen2.5:14b

  router-service:
    image: factcheck-router:latest
    depends_on: [judge-service]
    ports: ["8000:8000"]
    environment:
      JUDGE_SERVICE_URL: http://judge-service:8000
      ROUTER_MODEL: qwen2.5:7b
```

---

## Kubernetes

Para deploy em cluster, o projeto fornece manifests Kubernetes prontos no diretório `k8s/`.

### Arquivos

| Arquivo | Tipo | Descrição |
|---|---|---|
| `k8s/configmap.yaml` | `ConfigMap` | Variáveis de ambiente compartilhadas |
| `k8s/router-deployment.yaml` | `Deployment` + `Service` | Router Service com LoadBalancer |
| `k8s/judge-deployment.yaml` | `Deployment` + `Service` | Judge Service com ClusterIP interno |

### Deploy completo

```bash
# Aplicar todos os manifests
kubectl apply -f k8s/

# Verificar pods e serviços
kubectl get pods,svc

# Ver logs do roteador
kubectl logs -f deployment/router-service

# Remover tudo
kubectl delete -f k8s/
```

### ConfigMap

```yaml
# k8s/configmap.yaml
data:
  OLLAMA_BASE_URL: "http://host.docker.internal:11434"
  ROUTER_MODEL: "qwen2.5:7b"
  JUDGE_MODEL: "qwen2.5:14b"
  JUDGE_SERVICE_URL: "http://judge-service:8000"
```

---

## Equivalência Docker Compose ↔ Kubernetes

| Docker Compose | Kubernetes | Função |
|---|---|---|
| `services.judge-service` | `Deployment` | Define réplicas e imagem |
| `ports: 8000:8000` | `Service` (LoadBalancer) | Expõe porta externamente |
| `environment:` | `ConfigMap` | Variáveis de configuração |
| `depends_on:` | `initContainers` / ordering | Ordem de inicialização |
| `docker compose up -d` | `kubectl apply -f k8s/` | Deploy |
| `docker compose logs -f` | `kubectl logs -f <pod>` | Logs em tempo real |

!!! tip "Guia completo"
    Consulte [`docs/kubernetes_setup_guide.md`](https://github.com/yanrdgs-dev/challenge1-grupo13/blob/main/docs/kubernetes_setup_guide.md) para o tutorial passo a passo com exemplos de comandos.
