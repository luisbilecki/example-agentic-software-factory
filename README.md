# Exemplo de Fábrica de Software Agêntica (v2)

> **Aviso**: Este repositório é um **exemplo didático e de referência** de uma **Fábrica de Software Agêntica v2** orientada a GitHub Issues. Ele demonstra na prática como estruturar um orquestrador de issues que dispara agentes para implementar, validar, revisar e finalizar entregas automaticamente.

Para fins de demonstração, a aplicação alvo é uma **API CRUD de Clientes (FastAPI)** simples e o executor padrão configurado é o **Antigravity (`agy`)**, com arquitetura extensível para outros agentes (`codex`, `claude`, etc.).

## Arquitetura v2

### Fluxo da Máquina de Estados

```mermaid
flowchart TD
    A["Issue com label agent:ready"] --> B["Claim: troca para agent:in-progress"]
    B --> C["Isolamento: cria git worktree (branch agent/issue-N)"]
    C --> D["Agente Implementador (Antigravity / agy)"]
    D --> E{"Validação Determinística (ruff + pytest)"}
    E -- "Falhou (turn < max_turns)" --> D
    E -- "Passou" --> F["Agente Revisor (contexto limpo sobre git diff)"]
    F -- "Reprovado com findings (turn < max_turns)" --> D
    F -- "Aprovado" --> G["Finalização: Conventional Commit + Push + PR + agent:done"]
    E -- "Limite excedido" --> H["Escalonamento: comentário diagnóstico + agent:needs-human"]
    F -- "Limite excedido" --> H
```

### Sequência de Execução entre Componentes

```mermaid
sequenceDiagram
    participant GH as IssueProvider (GitHub / JSON)
    participant ORC as Orquestrador
    participant WT as Git Worktree
    participant IMP as Agente Implementador (agy)
    participant VAL as Validador (ruff + pytest)
    participant REV as Agente Revisor (agy)

    ORC->>GH: Busca issues com label agent:ready
    ORC->>GH: Troca label para agent:in-progress
    ORC->>WT: Cria worktree isolado (.worktrees/issue-N)

    loop Até max_turns
        ORC->>IMP: Envia issue + regras (AGENTS.md) + feedback anterior
        IMP-->>WT: Edita código e testes
        ORC->>VAL: Executa ruff check e pytest no worktree
        alt Testes ou lint falharam
            VAL-->>ORC: Retorna logs de erro (feedback)
        else Validação passou
            ORC->>WT: Extrai git diff
            ORC->>REV: Envia issue + git diff (contexto limpo)
            alt Revisor reprovou
                REV-->>ORC: JSON {approved: false, findings: [...]}
            else Revisor aprovou
                REV-->>ORC: JSON {approved: true, summary: "..."}
                ORC->>WT: Commit (Conventional Commits) + Push
                ORC->>GH: Abre PR, comenta resumo e aplica agent:done
            end
        end
    end

    ORC->>WT: Remove worktree temporário
```

### Etapas em Resumo

1. **Trigger por Label**: O orquestrador busca issues com a label `agent:ready` e troca para `agent:in-progress`.
2. **Isolamento por `git worktree`**: Cada issue roda em `.worktrees/issue-<N>` na branch `agent/issue-<N>`.
3. **Agente Implementador**: Executa seguindo as regras do [`AGENTS.md`](AGENTS.md).
4. **Validação Determinística (Backpressure)**: Executa `uv run ruff check .` e `uv run pytest -q`. Se falhar, devolve o erro ao implementador.
5. **Agente Revisor (Contexto Limpo)**: Avalia o `git diff` + issue e retorna JSON estruturado (`approved`, `summary`, `findings`). Se reprovar, inicia retrabalho (até `--max-turns`).
6. **Finalização / Escalonamento**:
   - **Aprovado**: Commit em Conventional Commits, abertura de PR e label `agent:done`.
   - **Limite excedido**: Comentário diagnóstico na issue e label `agent:needs-human`.

## Como Rodar

### 1. Instalar dependências e rodar testes
```bash
uv sync
uv run ruff check .
uv run pytest -v
```

### 2. Subir a API CRUD de Clientes
```bash
uv run uvicorn app.main:app --reload
```
Documentação interativa em `http://127.0.0.1:8000/docs`.

### 3. Rodar a Fábrica em Modo Local (sem repositório remoto)
Teste todo o ciclo (incluindo `git worktree` real, `ruff`, `pytest` e revisão) usando `examples/local_issues.json` e o agente `mock`:
```bash
uv run python -m factory.orchestrator --provider local --agent mock
```

Ou usando o **Antigravity (`agy`)** localmente sobre o JSON de issues:
```bash
uv run python -m factory.orchestrator --provider local --agent antigravity
```

### 4. Rodar a Fábrica conectada ao GitHub Real
Pré-requisitos: repositório com remote `origin` configurado, `gh auth login` ativo e labels `agent:ready`, `agent:in-progress`, `agent:done`, `agent:needs-human` criadas no GitHub.
```bash
uv run python -m factory.orchestrator --provider github --agent antigravity --max-turns 3
```

## Extensibilidade para Outros Agentes (Codex, Claude, etc.)

Em [`factory/agents.py`](factory/agents.py), basta implementar uma subclasse de `AgentRunner` e registrá-la em `AGENT_REGISTRY`:
```python
AGENT_REGISTRY["codex"] = CodexAgentRunner
AGENT_REGISTRY["claude"] = ClaudeAgentRunner
```
