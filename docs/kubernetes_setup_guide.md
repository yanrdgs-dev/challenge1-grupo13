# Guia Prático: Orquestração de Agentes com Docker e Kubernetes

Este guia foi elaborado para quem já conhece **Dockerfile** e **Docker Compose**, explicando passo a passo como empacotar e orquestrar os agentes **Roteador** e **Julgador** no **Kubernetes**.

---

## 1. O Paralelo: Docker Compose vs. Kubernetes

Se você já usou Docker Compose, o Kubernetes faz exatamente o mesmo papel, porém com capacidades avançadas de auto-recuperação (*self-healing*) e escalabilidade.

| Conceito no Docker Compose | Equivalente no Kubernetes | Função no Sistema de Fact-Checking |
|---|---|---|
| `services.judge-service` | **Deployment** (`k8s/base/judge-deployment.yaml`) | Declara quantas réplicas do container rodar e qual imagem usar. |
| `ports: 8000:8000` | **Service** (`k8s/base/judge-deployment.yaml`) | Cria um nome de rede DNS interno (`http://judge-service:8000`) estável para os pods conversarem. |
| `environment:` | **ConfigMap** (`k8s/base/configmap.yaml`) | Armazena configurações compartilhadas (como `OLLAMA_BASE_URL` e nomes dos modelos). |
| `docker compose up -d` | **`kubectl apply -k k8s/overlays/dev`** | Envia todos os manifestos para o cluster criar os pods e serviços. |
| `docker compose ps` | **`kubectl get pods,svc`** | Lista os pods em execução, status de saúde e portas expostas. |
| `docker compose logs -f` | **`kubectl logs -f <nome-do-pod>`** | Exibe os logs do container em tempo real. |
| `docker compose down` | **`kubectl delete -k k8s/overlays/dev`** | Remove os pods e serviços do cluster. |

---

## 2. Estrutura dos Arquivos Criados no Projeto

```text
├── docker/
│   ├── Dockerfile.router        # Container do Agente Roteador + Tools (FastAPI na porta 8000)
│   └── Dockerfile.judge         # Container do Agente Julgador (FastAPI na porta 8000)
├── docker-compose.yml           # Orquestração local simples via Docker Compose (para testes rápidos)
├── k8s/
│   ├── base/                    # Manifests comuns a todos os ambientes (sem tag de imagem)
│   │   ├── configmap.yaml           # Variáveis de ambiente compartilhadas
│   │   ├── router-deployment.yaml   # Deployment e Service (LoadBalancer) do Roteador
│   │   ├── judge-deployment.yaml    # Deployment e Service (ClusterIP interno) do Julgador
│   │   └── kustomization.yaml       # Lista os recursos da base
│   └── overlays/
│       └── dev/
│           └── kustomization.yaml   # Ambiente local: aponta para a base e define as tags das imagens
├── src/services/
│   ├── router_service.py        # Código do microsserviço Roteador
│   └── judge_service.py         # Código do microsserviço Julgador
```

---

## 3. Passo a Passo para Subir o Ambiente

### Passo 1: Iniciar o Docker Desktop e Ativar o Kubernetes

1. Abra o aplicativo **Docker** no seu Mac (`/Applications/Docker.app`).
2. Clique no ícone de **Engrenagem (Settings)** no topo à direita.
3. No menu lateral esquerdo, clique em **Kubernetes**.
4. Marque a caixa **"Enable Kubernetes"** e clique em **Apply & restart**.
5. Aguarde o ícone do Kubernetes ficar verde no canto inferior do Docker Desktop.

Para testar se o Kubernetes está respondendo no terminal:
```bash
kubectl get nodes
```
*(Deve exibir um nó chamado `docker-desktop` com status `Ready`).*

---

### Passo 2: Construir as Imagens Docker Localmente

No terminal, na raiz do repositório, faça o build das duas imagens:

```bash
# 1. Constrói a imagem do Roteador
docker build -t factcheck-router:latest -f docker/Dockerfile.router .

# 2. Constrói a imagem do Julgador
docker build -t factcheck-judge:latest -f docker/Dockerfile.judge .
```

---

### Passo 3: Garantir que o Ollama está Rodando no Mac

Como estamos no Mac com chip Apple M4, o Ollama roda no macOS nativo usando a aceleração da GPU Metal. Os containers Docker acessam o Ollama através do endereço especial `http://host.docker.internal:11434`.

Certifique-se de que o Ollama está ativo:
```bash
ollama list
```
*(Deve listar `qwen2.5:7b` e `qwen2.5:14b`).*

---

### Passo 4: Fazer o Deploy no Kubernetes

Com as imagens construídas e o Kubernetes ativo, aplique os manifestos com um único comando:

```bash
kubectl apply -k k8s/overlays/dev
```

O `-k` usa o Kustomize embutido no `kubectl`. As tags das imagens (`factcheck-router` e `factcheck-judge`) ficam em `k8s/overlays/dev/kustomization.yaml`, no campo `images`, e não mais dentro dos Deployments. Para trocar a versão, edite essa tag. Para conferir o resultado antes de aplicar:

```bash
kubectl kustomize k8s/overlays/dev
```

Para verificar o status dos containers subindo:
```bash
kubectl get pods -w
```

Assim que a coluna `STATUS` estiver como `Running`, veja os serviços criados:
```bash
kubectl get svc
```

Saída esperada:
```text
NAME             TYPE        CLUSTER-IP       PORT(S)          AGE
judge-service    ClusterIP   10.96.120.45     8000/TCP         1m
router-service   LoadBalancer    10.96.210.12     8000:30080/TCP   1m
```

---

## 4. Testando a Checagem de Fatos via Kubernetes

Envie uma requisição HTTP via `curl` para a porta do Roteador:

```bash
curl -X POST http://localhost:8000/check \
  -H "Content-Type: application/json" \
  -d '{"claim": "Em 2023, o deputado que mais gastou a cota parlamentar (CEAP) foi Pompeo de Mattos (PDT-RS)."}'
```
*(Ou pela porta NodePort `http://localhost:30080/check`).*

### O que acontece por baixo dos panos:
1. O pod **`router-agent`** recebe a claim e consulta o `qwen2.5:7b` no Ollama.
2. O Roteador executa a tool correspondente em Python/DuckDB e obtém os dados factuais.
3. O Roteador dispara uma requisição interna de rede para `http://judge-service:8000/judge`.
4. O pod **`judge-agent`** recebe a evidência, consulta o `qwen2.5:14b` no Ollama e emite o veredito final.
5. Você recebe a resposta consolidada com veredito, fontes e tempos de execução.

---

## 5. Comandos Úteis no Dia a Dia do Kubernetes

| Objetivo | Comando |
|---|---|
| Ver logs do Roteador | `kubectl logs -l app=router-service -f` |
| Ver logs do Julgador | `kubectl logs -l app=judge-service -f` |
| Reiniciar um serviço | `kubectl rollout restart deployment router-deployment` |
| Escalar o Julgador para 2 réplicas | `kubectl scale deployment judge-deployment --replicas=2` |
| Destruir os pods e limpar o cluster | `kubectl delete -k k8s/overlays/dev` |

---

## 6. Alternativa Rápida com Docker Compose

Se em algum momento você quiser apenas rodar os dois containers sem iniciar o Kubernetes:
```bash
docker compose up -d
docker compose logs -f
```
E testar exatamente na mesma porta: `http://localhost:8000/check`.
