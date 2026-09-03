# Segurança com SQLite e Python

## Limites de parâmetros

Placeholders vinculam somente valores. Eles não podem representar identificadores, palavras-chave, direções de ordenação, fragmentos de expressão nem uma lista completa de valores. Para qualquer parte dinâmica da estrutura do SQL, use uma lista de valores permitidos no código e selecione apenas constantes dela.

```python
ORDER_BY = {"email": "email", "created": "created_at"}
order_by = ORDER_BY[user_choice]  # rejeitar antes chaves ausentes
rows = connection.execute(
    f"SELECT id, email FROM users ORDER BY {order_by} LIMIT ?", (limit,)
)
```

Nunca valide identificadores apenas por regex quando uma allowlist pequena pode representar o domínio permitido. Não aceite SQL arbitrário de usuário, mesmo parametrizado.

## Valores e dados sensíveis

- Passe uma tupla/lista para marcadores `?` e um dicionário para marcadores nomeados; não misture estilos.
- `executemany()` é apropriado para repetição de um único statement parametrizado, não para concatenar múltiplos statements.
- Não registre em logs SQL completo com segredos, tokens ou dados pessoais. Registre operação, duração, contagem e identificadores não sensíveis, conforme a política da aplicação.
- Não habilite carregamento de extensões nem exponha `create_function`, `set_authorizer` ou acesso ao arquivo do banco a entradas não confiáveis sem desenho explícito de isolamento.
- Validar limites de paginação, tamanhos de BLOB/texto e o domínio dos parâmetros antes de consultar protege disponibilidade, embora não substitua parâmetros.

## Arquivos e URIs

Não deixe entrada externa escolher livremente o caminho do banco ou uma URI SQLite. Se a aplicação abre bancos fornecidos por usuários, tratar o arquivo como dado não confiável: usar permissões mínimas, evitar filesystem compartilhado e definir se anexos, extensões e funções SQL são permitidos.

Consultar a documentação oficial de [placeholders do `sqlite3`](https://docs.python.org/3/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries) e [SQL injection do SQLite](https://www.sqlite.org/security.html) quando o modelo de ameaça alterar o desenho.
