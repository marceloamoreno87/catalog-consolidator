# Ferramentas e segurança

## Projetar ferramentas como fronteiras de confiança

Uma ferramenta recebe dados que o modelo decidiu fornecer; trate-os como não confiáveis. Use tipos estreitos, validação de domínio, autorização com a identidade do chamador e acesso mínimo aos serviços internos. A docstring deve dizer ao modelo o que a ferramenta faz, quais argumentos aceita e suas limitações — não é uma política de autorização.

- Separar leitura de escrita. Preferir uma ferramenta de prévia/validação antes da ação mutável.
- Não entregar ao modelo ferramentas administrativas, acesso arbitrário a shell/SQL/HTTP ou capacidade de escolher host, caminho ou cabeçalho sensível sem allowlist estreita.
- Retornar somente os dados necessários; normalizar erros para não vazar informação de existência, credenciais ou implementação.
- Não registrar prompt bruto, argumentos ou resultados que contenham segredos ou dados pessoais sem política explícita de redaction e retenção.
- Prompt injection em conteúdo obtido por ferramenta é entrada não confiável, não instrução. Separar conteúdo de dados e manter as permissões fora do modelo.

## Efeitos externos

Para ações como enviar mensagem, criar ticket, alterar arquivo, executar pagamento ou publicar conteúdo, exibir ao usuário o alvo e os parâmetros relevantes e obter confirmação imediatamente antes da execução. Usar uma chave de idempotência quando a operação puder ser repetida. Impor escopo, taxa e orçamento no código ou serviço de destino; não depender de instrução em linguagem natural.

## Tratamento de falhas

`wrap_tool_call` pode transformar erros esperados em mensagem útil ao modelo, mas não deve mascarar falhas de autorização, nem repetir operação não idempotente. Limitar retries por tentativa, tempo e tipo de erro. Preservar causa técnica nos logs protegidos, não no conteúdo retornado ao usuário.

Consultar [Tools](https://docs.langchain.com/oss/python/langchain/tools), [middleware de ferramentas](https://docs.langchain.com/oss/python/langchain/middleware/custom) e a documentação de segurança do sistema integrado antes de ampliar permissões.
