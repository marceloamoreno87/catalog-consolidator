---
name: python-sqlite-expert
description: Implement, review, migrate, secure, test, and optimize SQLite persistence in Python. Use for sqlite3 code, database configuration, schema and migrations, SQL queries, transactions, concurrency/WAL, indexes, query plans, FTS5, backup, or integrity work in Python applications.
---

# Python SQLite Expert

Construir persistência SQLite simples, segura e mensurável com o módulo padrão `sqlite3`. Não assumir que a versão do CPython é a versão do motor SQLite vinculado.

## Protocolo obrigatório

1. Confirmar o motor no ambiente-alvo ou em CI com `SELECT sqlite_version()` (ou `sqlite3.sqlite_version`). Quando o requisito do sistema for SQLite **3.53.4**, exigir essa versão explicitamente; atualizar Python/distribuição ou usar uma build apropriada se o resultado for diferente.
2. Usar parâmetros `?` ou nomeados para todos os valores. Nunca interpolar dados externos em SQL.
3. Tornar explícita a política de transação na conexão (`autocommit` em Python 3.12+ ou `isolation_level` no modo legado); agrupar operações relacionadas em uma transação e não misturar `Connection` e uma transação já em curso.
4. Manter DDL, migrações e operações relacionadas em transações quando SQLite permitir. Não usar `executescript()` como se ele fornecesse atomicidade: ele confirma uma transação pendente antes de executar o script.
5. Antes de otimizar, medir com `EXPLAIN QUERY PLAN` e dados representativos. Não adicionar PRAGMAs, índices, WAL, pooling ou FTS por hábito.

## Leituras condicionais

Ler a referência indicada antes de implementar:

- Qualquer SQL que receba dado externo, ordenação/campo/tabela dinâmica ou dado sensível: [references/security.md](references/security.md).
- Migração, concorrência, WAL, índices, lentidão, FTS5, manutenção ou backup: [references/operations.md](references/operations.md).

Consultar a [documentação oficial do SQLite](https://sqlite.org/docs.html) quando a decisão depender da semântica do motor ou de uma PRAGMA; e a [documentação de `sqlite3`](https://docs.python.org/3/library/sqlite3.html) para comportamento da API e da versão de Python usada. Não copiar configurações de blog sem justificativa e teste.

## Fluxo de trabalho

1. Delimitar a operação, invariantes e volume/concor­rência esperados. Perguntar quando isso mudar a escolha entre configuração simples e WAL, FTS ou migração destrutiva.
2. Escrever primeiro um teste: `:memory:` para lógica isolada; arquivo temporário para WAL, migrações, bloqueios e qualquer comportamento que dependa de múltiplas conexões.
3. Implementar o menor schema e a menor consulta que atendam ao caso. Preferir `NOT NULL`, `CHECK`, `UNIQUE` e chaves estrangeiras a validação apenas na aplicação.
4. Executar os testes afetados e `EXPLAIN QUERY PLAN` para qualquer consulta que motivou índice ou mudança de desempenho.
5. Informar o que foi alterado, versão SQLite verificada, testes executados e qualquer trade-off de durabilidade ou concorrência.

## Fundamentos de Python e `sqlite3`

- Criar e fechar conexões de forma explícita; o gerenciador de contexto da conexão confirma/reverte transações, mas **não fecha** a conexão.
- Uma conexão não deve ser usada simultaneamente por múltiplas threads. Manter `check_same_thread=True` (padrão); só desabilitá-lo com serialização externa das escritas e teste de contenção.
- `:memory:` cria um banco por conexão. Para testes multi-conexão, usar um arquivo temporário ou uma URI de memória compartilhada (`file:...?...cache=shared`, com `uri=True`) quando o caso exigir.
- Executar `PRAGMA foreign_keys = ON` em toda nova conexão. Aplicar PRAGMAs connection-local em cada conexão criada, não apenas uma vez durante inicialização de um pool.
- Usar `sqlite3.Row` apenas quando acesso por nome melhorar legibilidade; converter resultados para tipos de domínio na borda do repositório.
- Não introduzir ORM ou query builder para uma necessidade simples. SQL explícito e parametrizado é o padrão.

## Inicialização mínima

Após abrir o banco, validar a versão e habilitar integridade. Configurar concorrência somente quando o caso justificar.

```python
import sqlite3


def connect_database(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path, autocommit=False)
    version = connection.execute("SELECT sqlite_version()").fetchone()[0]
    if version != "3.53.4":
        connection.close()
        raise RuntimeError(f"SQLite {version} loaded; require 3.53.4")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
```

Para Python anterior a 3.12, escolher e documentar `isolation_level` em vez de passar `autocommit`. Usar `journal_mode = WAL`, `busy_timeout` e `synchronous = NORMAL` somente para banco local com concorrência de leitura/escrita e após aceitar o trade-off de durabilidade descrito na referência. Evitar WAL em filesystem de rede.

## Consultas e transações

Usar parâmetros para valores e validar/permitir explicitamente os poucos identificadores dinâmicos possíveis.

```python
def find_user(connection: sqlite3.Connection, user_id: int) -> tuple[int, str] | None:
    return connection.execute(
        "SELECT id, email FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def move(connection: sqlite3.Connection, source: int, target: int, cents: int) -> None:
    with connection:
        result = connection.execute(
            "UPDATE accounts SET cents = cents - ? WHERE id = ?", (cents, source)
        )
        if result.rowcount != 1:
            raise LookupError("source account not found")
        result = connection.execute(
            "UPDATE accounts SET cents = cents + ? WHERE id = ?", (cents, target)
        )
        if result.rowcount != 1:
            raise LookupError("target account not found")
```

Verificar `rowcount` quando a operação exigir que uma linha exista. Para dinheiro, armazenar inteiros na menor unidade; não usar `float`.

## Migrações e schema

- Versionar migrações imutáveis e registrar versões aplicadas em tabela dedicada. Uma migração é idempotente apenas quando isso for requisito explícito; não mascarar divergência de versões com `IF NOT EXISTS` indiscriminadamente.
- Executar migrações uma por vez em transação; usar `BEGIN IMMEDIATE` quando for necessário falhar cedo diante de outro escritor.
- Fazer backup testado antes de mudança destrutiva ou reescrita de tabela. Testar upgrade a partir de cópia representativa e executar `PRAGMA foreign_key_check` após alterações de relações.
- Preferir `INTEGER PRIMARY KEY` a `AUTOINCREMENT`, salvo se nunca reutilizar IDs for requisito real.
- Usar `STRICT` quando o domínio exigir tipagem rígida; a afinidade de tipo normal do SQLite é deliberadamente flexível.

## Performance sem complexidade acidental

- Indexar a consulta medida: colunas de igualdade primeiro, depois as de intervalo/ordenação quando aplicável. Remover índices que não sustentem consulta real, pois toda escrita paga por eles.
- Usar `EXPLAIN QUERY PLAN` e validar que o plano usa o índice esperado. Executar `PRAGMA optimize` como manutenção apropriada; não executar `ANALYZE` ou `VACUUM` no caminho de requisição.
- Fazer inserções em lote numa transação; reutilizar statements quentes só quando medição indicar benefício.
- Usar FTS5 apenas para busca textual. Projetar tabela virtual, tokenizer, sincronização e consultas `MATCH` conforme a referência.
- Não alterar `page_size`, `mmap_size`, `cache_size`, `temp_store`, auto-vacuum ou checkpoint automático sem benchmark, limite de memória e plano de reversão.

## Critérios de aceite

- Teste cobre caminho feliz e falhas/invariantes afetados; tentativa de injeção é tratada como dado, não SQL.
- Teste de migração começa em schema anterior e chega ao novo sem perder dados esperados.
- Banco de teste habilita chaves estrangeiras e não mascara problemas por usar apenas uma conexão em memória.
- A versão SQLite exigida é verificada no ambiente que executa o código.
- Toda alteração de performance inclui medição ou plano de consulta anexável à revisão.
