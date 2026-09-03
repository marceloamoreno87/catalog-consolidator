# Diretrizes para agentes de código

Estas diretrizes reduzem erros comuns de implementação. Aplique-as junto às instruções específicas do projeto; em caso de conflito, as instruções mais específicas prevalecem.

Elas privilegiam segurança e precisão em vez de velocidade. Para mudanças triviais e inequívocas, use bom senso: não transforme uma pequena edição em um processo burocrático.

## 0. Escopo operacional: desenvolvimento local

Todo desenvolvimento, execução e validação devem ocorrer localmente por padrão.

- Não crie infraestrutura, configuração, camadas ou fluxos destinados a produção.
- Não crie, altere ou execute pipelines de CI/CD, deploy, publicação, provisionamento ou automações externas.
- Só trabalhe em produção ou CI/CD quando isso for pedido explicitamente e houver contexto completo sobre a arquitetura de produção, o fluxo desejado, credenciais/permissões necessárias e critérios de validação.
- Na ausência desse contexto, limite-se a entregar código, testes e instruções locais.

## 1. Entenda antes de alterar

Não presuma requisitos, nem esconda incertezas.

Antes de implementar:

- Declare suposições que afetem a solução. Se uma suposição puder mudar escopo, comportamento ou risco, peça confirmação.
- Quando houver interpretações razoáveis, apresente-as e recomende uma; não escolha silenciosamente.
- Prefira a solução mais simples que cumpra o pedido. Se o pedido sugerir complexidade desnecessária, explique o trade-off e proponha a alternativa menor.
- Se faltar informação essencial, pare e diga exatamente o que está ambíguo. Não invente requisitos.

## 2. Mantenha a solução mínima

Implemente somente o necessário para atender ao pedido atual.

- Não adicione funcionalidades, opções, configurações ou extensibilidade que não foram solicitadas.
- Não crie abstrações para código de uso único.
- Não trate cenários impossíveis no contexto conhecido; trate falhas reais e plausíveis no limite apropriado.
- Se a implementação parecer desproporcional ao problema, simplifique antes de concluir.
- Priorize código legível e direto em vez de generalização prematura.

Pergunta de controle: uma pessoa engenheira sênior consideraria esta mudança mais complexa do que o problema exige? Se sim, reduza-a.

## 2.1. Reuse regras sem antecipar abstrações

Antes de criar uma função, tipo ou regra, procure uma implementação equivalente no projeto e reutilize-a quando ela já atender ao caso.

- Mantenha regras de negócio compartilhadas em uma única fonte de verdade; não replique transformações, validações ou critérios em classes e módulos diferentes.
- Extraia um helper ou objeto de valor somente quando houver repetição real ou uma regra de domínio compartilhada. Não crie interfaces, classes-base, opções ou configurações para uma única chamada.
- Ao adicionar uma regra configurável, use um único objeto de valor e passe-o somente pelas camadas que realmente a consomem. Não introduza prompts, parâmetros ou opções sem requisito explícito.
- Prefira compor e reutilizar o código existente a duplicá-lo para preservar uma separação de camadas artificial.

## 2.2. Preserve legibilidade

- Organize imports em grupos: biblioteca padrão, dependências externas e imports locais, separados por linhas em branco. Não use comentários inline em imports; remova imports obsoletos.
- Comentários devem explicar o porquê, invariantes, restrições de segurança ou trade-offs. Não descreva linha a linha algo que nomes claros e o próprio código já mostram.
- Use docstrings curtas para APIs públicas ou comportamentos não óbvios. Não adicione documentação que apenas repete a assinatura ou a implementação.
- Siga o formatter e o linter configurados pelo projeto. Na ausência deles, mantenha o estilo predominante e legível do arquivo alterado.

## 3. Faça mudanças cirúrgicas

Altere apenas o que for necessário para a solicitação.

- Não refatore, reformate ou "melhore" código, comentários ou arquivos adjacentes sem relação direta com a tarefa.
- Siga os padrões já adotados pelo projeto, mesmo que você prefira outro estilo.
- Cada linha modificada deve ser justificável pelo requisito ou por uma consequência direta dele.
- Remova imports, variáveis, funções ou testes que a **sua mudança** tornou obsoletos.
- Não remova código morto ou problemas preexistentes; registre-os brevemente para o solicitante quando forem relevantes.

## 4. Trabalhe por critérios verificáveis

Converta o pedido em um resultado que possa ser demonstrado e verifique-o antes de encerrar.

- Para correções de bug, primeiro reproduza a falha em um teste ou em um procedimento objetivo; então confirme que a correção a elimina.
- Para novas validações ou comportamentos, cubra os casos relevantes — especialmente entradas inválidas e o caminho esperado — quando a base de testes permitir.
- Para refatorações, confirme o comportamento existente antes e depois da alteração.
- Execute as verificações mais específicas e proporcionais disponíveis (testes afetados, lint, type-check ou build). Não alegue que algo foi verificado sem executar a checagem.
- Antes de concluir, revise o diff em busca de imports não usados ou desorganizados, regras de negócio duplicadas, comentários redundantes e alterações fora do escopo.
- Se não for possível verificar, diga o que não foi executado, por quê e qual o risco restante.

Em tarefas com mais de uma etapa ou risco não trivial, apresente um plano curto com a forma de verificação de cada etapa. Em tarefas pequenas e claras, vá direto à execução.

## 5. Conclua com transparência

Ao finalizar, informe de forma concisa:

- o que mudou;
- como foi verificado;
- suposições, limitações ou riscos remanescentes.

Evite relatar passos sem utilidade para quem solicitou a mudança. O objetivo é entregar uma alteração correta, pequena e comprovada.
