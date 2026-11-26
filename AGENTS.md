# AGENTS.md — Regras da Fábrica de Software Agêntica v2

Este arquivo define as regras obrigatórias para qualquer agente (Implementador ou Revisor) que atuar neste repositório.

## 1. Stack e Comandos de Verificação

- **Linguagem**: Python 3.11+ gerenciado via `uv`.
- **Framework da API**: FastAPI (`app/`).
- **Orquestrador da Fábrica**: `factory/`.
- **Qualidade e Testes** (devem passar 100% antes de concluir qualquer tarefa):
  ```bash
  uv run ruff check .
  uv run pytest -q
  ```

## 2. Padrão de Commits (Conventional Commits)

Todos os commits — sejam humanos ou gerados pelo orquestrador/agentes — **DEVEM** seguir [Conventional Commits](https://www.conventionalcommits.org/):

- Formato: `<type>(<scope>): <descrição curta no imperativo>`
- Tipos permitidos: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
- Exemplos:
  - `feat(customers): add optional email filter to list endpoint`
  - `fix(customers): return 409 on duplicate customer email`
  - `test(factory): add rework loop coverage to orchestrator`
- Sempre referencie a issue no corpo ou rodapé quando aplicável (`Closes #<numero>`).

## 3. Convenções de Código (API CRUD de Clientes)

- Mantenha a separação de responsabilidades:
  - `app/models.py`: Schemas Pydantic (`CustomerCreate`, `CustomerUpdate`, `Customer`).
  - `app/repository.py`: Acesso e persistência de dados (`CustomerRepository`).
  - `app/main.py`: Rotas HTTP FastAPI e tratamento de status codes.
- Todo novo endpoint, filtro ou validação **DEVE** incluir testes correspondentes em `tests/test_customers_api.py`.
- Use type hints em todas as funções e métodos.
- Não quebre contratos existentes da API sem solicitação explícita na issue.

## 4. Regras para o Agente Implementador

1. Leia atentamente a issue e o contexto do repositório antes de editar.
2. Faça alterações mínimas, coesas e focadas estritamente no escopo da issue.
3. Escreva ou atualize testes automatizados cobrindo o novo comportamento e casos de borda.
4. Execute `uv run ruff check .` e `uv run pytest -q` antes de encerrar.
5. Nunca faça `git push` nem abra PR manualmente — o orquestrador controla o ciclo de vida Git/GitHub.

## 5. Regras para o Agente Revisor

1. Atue com contexto limpo, analisando apenas a descrição da issue, este `AGENTS.md` e o `git diff`.
2. Verifique: aderência aos requisitos da issue, qualidade dos testes, edge cases, tipagem e ausência de regressões.
3. Responda **estritamente** no formato JSON especificado no prompt de revisão (`approved`, `summary`, `findings`).
4. Só aprove (`"approved": true`) quando não houver falhas críticas ou requisitos faltantes.
