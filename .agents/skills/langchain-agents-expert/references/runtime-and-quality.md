# Runtime, observabilidade e qualidade

## Estado e conversas

Com `checkpointer`, reutilizar `thread_id` apenas na mesma conversa autorizada. Não derivar o identificador diretamente de dado público previsível sem vinculação ao usuário/sessão. Definir retenção, exclusão e proteção de histórico antes de persistir mensagens. Contexto de execução (`context_schema`) é preferível a inserir identidade, permissões e segredos no histórico do modelo.

Estado adicional deve ser pequeno, tipado e ter um proprietário claro. Resumir ou aparar histórico somente após avaliar a perda de informações e testar conversas longas relevantes.

## Middleware e tolerância a falhas

Hooks `before_*` executam na ordem declarada, `after_*` na ordem reversa e wrappers se aninham. Manter middleware independente e observável. Usar wrappers para retries, timeouts e seleção dinâmica somente com limites explícitos; propagação de erro é melhor que uma recuperação ambígua que possa produzir ação indevida.

Streaming altera a interface de consumo, não a política de segurança: não considerar uma resposta parcial como resultado validado nem executar efeitos baseados nela antes da conclusão e validação.

## Testes e avaliação

Testar ferramentas isoladamente e o harness com doubles/fakes. Cobrir no mínimo:

- pergunta que deve usar a ferramenta correta;
- argumento inválido ou usuário não autorizado;
- timeout/erro da ferramenta sem retry perigoso;
- resposta estruturada inválida ou ausente;
- isolamento de dois `thread_id`s, se houver memória.

Em avaliação de ponta a ponta, usar conjunto versionado de cenários e critérios verificáveis (correção, chamada permitida, ausência de ação não autorizada, custo/latência). Capturar tracing sem segredos e só quando a integração e política de dados permitirem.

Referências oficiais: [agents](https://docs.langchain.com/oss/python/langchain/agents), [middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom), [memória](https://docs.langchain.com/oss/python/langchain/short-term-memory) e [testes](https://docs.langchain.com/oss/python/langchain/test).
