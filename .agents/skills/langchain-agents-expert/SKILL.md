---
name: langchain-agents-expert
description: Build, review, test, and secure Python LangChain 1.3.18 agents. Use for create_agent, tools, middleware, structured output, state, memory, streaming, tracing, and agent evaluation; not for non-agent LLM calls that need only a direct model invocation.
---

# LangChain Agents Expert

Construir agentes Python previsíveis, limitados ao problema e fáceis de testar com `langchain==1.3.18`. Um agente é um loop de modelo e ferramentas; o *harness* — prompt, ferramentas, estado e middleware — determina seu comportamento. Não usar agentes quando uma chamada direta ao modelo ou fluxo determinístico resolve o requisito.

## Protocolo obrigatório

1. Fixar e verificar `langchain==1.3.18` no ambiente do projeto antes de usar APIs desta skill. Não misturar exemplos de outras versões nem assumir compatibilidade de integrações de provedores.
2. Delimitar objetivo, ferramentas permitidas, dados acessíveis, efeitos externos, orçamento de chamadas/tokens e condição de parada. Perguntar quando um desses pontos mudar risco, custo ou permissão.
3. Começar por `create_agent(model=..., tools=..., system_prompt=...)`; adicionar estado, memória, middleware, subagentes ou Deep Agents somente quando há uma necessidade observável.
4. Declarar ferramentas com argumentos tipados, docstrings específicas e retorno serializável. Aplicar validação e autorização dentro da própria ferramenta; o prompt não é um limite de segurança.
5. Fazer confirmação humana antes de ferramentas com efeito irreversível ou externo (pagamento, exclusão, publicação, e-mail, alteração de acesso). Para ferramentas de escrita reversível, definir idempotência e limites explícitos.
6. Preferir saída estruturada (`response_format=` com modelo Pydantic) quando o resultado alimentar código. Validar antes de efeitos posteriores.
7. Testar o caminho normal, ferramentas recusadas/falhas, saídas inválidas e limites de execução. Não exigir credenciais ou chamadas reais para testes unitários.

## Leituras condicionais

- Ferramentas que acessam dados, sistemas externos ou fazem escrita: [references/tools-and-security.md](references/tools-and-security.md).
- Estado por conversa, memória, streaming, middleware, retries, tracing ou avaliação: [references/runtime-and-quality.md](references/runtime-and-quality.md).

Usar primeiro a [documentação oficial de agents](https://docs.langchain.com/oss/python/langchain/agents) e o repositório [langchain-ai/langchain](https://github.com/langchain-ai/langchain). Consultar a documentação da integração oficial do provedor escolhido antes de fixar parâmetros de modelo, streaming ou tool-calling.

## Fluxo de trabalho

1. Escrever o menor caso de uso e um teste objetivo. Determinar se basta modelo direto, se `create_agent` basta, ou se o fluxo precisa ser determinístico.
2. Implementar um agente mínimo com poucas ferramentas e um `system_prompt` que descreva objetivo, escopo, restrições e quando não agir.
3. Acrescentar `response_format`, `context_schema`, `state_schema`, `checkpointer` e middleware apenas pela necessidade que os justifica.
4. Executar testes locais com ferramentas falsas e modelos/simulações suportados pelo projeto. Em integração, usar ambiente isolado e dados não sensíveis.
5. Relatar versão de LangChain, modelo e integração usados, ferramentas/efeitos permitidos, persistência de estado, testes e limites remanescentes.

## Agente mínimo

Mantenha as ferramentas pequenas e auditáveis. O modelo escolhe *quando* chamá-las; a implementação decide *se* a chamada é autorizada.

```python
from pydantic import BaseModel
from langchain.agents import create_agent
from langchain.tools import tool


@tool
def lookup_order(order_id: str) -> str:
    """Return the status of one order the caller is authorized to view."""
    # Validate authorization and query the application service here.
    return f"Order {order_id}: processing"


class OrderAnswer(BaseModel):
    status: str
    needs_human_help: bool


agent = create_agent(
    model="provider:model-name",
    tools=[lookup_order],
    system_prompt=(
        "Help with order status. Use only the supplied tools; never invent order data. "
        "Escalate when authorization or data is unavailable."
    ),
    response_format=OrderAnswer,
)

result = agent.invoke({"messages": [{"role": "user", "content": "Where is order A-42?"}]})
answer = result["structured_response"]
```

O identificador `provider:model-name` e o pacote da integração dependem do provedor. Não colocar chaves, usuário autenticado ou segredos no prompt; passá-los como contexto tipado e validar no limite da ferramenta.

## Estado, memória e middleware

- `AgentState` contém o histórico da execução. Estender `state_schema` apenas para dados que pertencem ao estado do agente; não usar como banco de dados geral.
- Usar `context_schema` para informação por execução, como identidade autenticada e flags. Tratar contexto como entrada confiável do aplicativo, não como conteúdo fornecido pelo usuário.
- Persistir conversas somente com `checkpointer` e um `thread_id` estável, cuja posse é autorizada. `InMemorySaver` serve para desenvolvimento/testes, não para memória durável.
- Middleware é para preocupações transversais: limites, observabilidade, seleção de modelo, retries e tratamento de erro. Preservar ordem e tornar retries limitados e seguros para idempotência.
- Não criar subagentes/Deep Agents para uma tarefa curta de uma ferramenta. Só delegar quando a divisão reduz de fato contexto, ferramentas ou complexidade; definir escopo e contrato de cada subagente.

## Critérios de aceite

- Dependência fixa em `langchain==1.3.18`; versões das integrações são compatíveis e declaradas pelo projeto.
- Ferramentas validam e autorizam seus argumentos, têm escopo mínimo e não expõem segredos em retorno, trace ou log.
- Toda escrita externa tem confirmação, idempotência ou ambos, conforme risco.
- Saída usada pelo código é estruturada e validada; falhas de modelo e ferramenta não resultam em efeito indevido.
- Testes cobrem sucesso, recusa/autorização, falha de ferramenta e dados/saída inválidos.
- Memória persistente tem `thread_id`, isolamento entre usuários e política de retenção definida.
