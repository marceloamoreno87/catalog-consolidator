# Operações SQLite

## Conexões, transações e concorrência

Manter transações curtas: não executar I/O de rede, chamadas lentas nem lógica interativa enquanto houver escrita aberta. Há apenas um escritor por banco; WAL permite que leitores coexistam com um escritor, mas não transforma SQLite em banco multiwriter.

Use arquivo temporário para testar bloqueios, WAL e reinicialização. `:memory:` por conexão não testa esses comportamentos. Trate `sqlite3.OperationalError` de bloqueio conforme o requisito de idempotência; não faça retry cego de escrita parcialmente aplicada.

WAL é apropriado para banco local com leitores e escritor concorrentes. Ele cria arquivos auxiliares e exige que todos os processos estejam na mesma máquina; não o use em filesystem de rede. Escolher timeout e checkpoint com carga observada, tamanho aceitável de WAL e estratégia de reversão.

## Migrações e recuperação

Registrar migrações aplicadas com versão, momento e checksum quando isso for necessário para detectar arquivos alterados. Antes de uma migração destrutiva, produzir backup e confirmar restauração em cópia representativa. Para mudanças de schema, validar com `PRAGMA foreign_key_check`; usar `PRAGMA integrity_check` quando houver suspeita de corrupção.

Executar um passo por vez dentro da transação apropriada e não esconder estado divergente. Conferir as limitações de transação do DDL na versão do SQLite em uso.

## Medição e manutenção

Começar pela consulta real e dados representativos:

```python
plan = connection.execute(
    "EXPLAIN QUERY PLAN SELECT id FROM events WHERE account_id = ? ORDER BY created_at DESC",
    (account_id,),
).fetchall()
```

Adicionar índice apenas quando o plano e a medição justificarem. Reavaliar índices em inserções/atualizações frequentes. `PRAGMA optimize` é manutenção sob demanda; `ANALYZE` e `VACUUM` podem custar tempo, espaço ou bloquear e não pertencem a caminho de requisição.

FTS5 é para busca textual com `MATCH`; projetar tokenizer e sincronização entre conteúdo e índice antes de adotá-lo. Backups online devem usar a API `Connection.backup()` ou procedimento SQLite apropriado, não cópia ingênua de arquivo enquanto há escrita.

Consultar antes de mudar comportamento: [WAL](https://sqlite.org/wal.html), [PRAGMAs](https://sqlite.org/pragma.html), [EXPLAIN QUERY PLAN](https://sqlite.org/eqp.html), [FTS5](https://sqlite.org/fts5.html) e [backup online](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
