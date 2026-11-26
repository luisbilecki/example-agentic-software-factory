# Spec 001 — Evolução da API CRUD de Clientes

## Contexto / PRD
A API básica de clientes já suporta CRUD completo em memória. Para uso real por times de atendimento e integrações, precisamos evoluir a busca, integridade de dados e controle de ciclo de vida dos clientes.

## Requisitos e Tarefas Atômicas

### Task: Adicionar filtro opcional por email no GET /customers
- Permitir query param opcional `email` em `GET /customers` com busca parcial case-insensitive.
- Manter compatibilidade quando `email` não for informado.
- Cobrir com testes em `tests/test_customers_api.py`.

### Task: Garantir unicidade de email retornando 409 Conflict
- Impedir cadastro (`POST /customers`) ou atualização (`PUT /customers/{id}`) com um `email` já utilizado por outro cliente (comparação case-insensitive).
- Retornar HTTP `409 Conflict` com mensagem clara (`"Customer email already exists"`).
- Permitir atualizar o mesmo cliente mantendo seu próprio email.
- Cobrir com testes em `tests/test_customers_api.py`.

### Task: Adicionar paginação (limit e offset) no GET /customers
- Adicionar query params opcionais `limit` (default `50`, mínimo `1`, máximo `100`) e `offset` (default `0`, mínimo `0`) em `GET /customers`.
- Aplicar paginação após os filtros existentes.
- Cobrir com testes de limites e valores inválidos em `tests/test_customers_api.py`.

### Task: Adicionar endpoint PATCH /customers/{id}/deactivate
- Criar rota `PATCH /customers/{customer_id}/deactivate` que define `active = False` e retorna o cliente atualizado (`200 OK`).
- Retornar `404 Not Found` caso o cliente não exista.
- Cobrir com testes em `tests/test_customers_api.py`.
