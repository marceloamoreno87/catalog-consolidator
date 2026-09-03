# Catalog Consolidator

CLI em Python que importa catálogos de vendedores para um banco SQLite de marketplace. Ela evita criar produtos duplicados quando itens de vendedores diferentes representam o mesmo produto e, ao mesmo tempo, registra quais vendedores oferecem cada produto.

O projeto foi desenvolvido como solução local para o desafio descrito em [docs/desafio.md](docs/desafio.md). Não há serviço web, deploy, argumentos de linha de comando ou automação de produção.

## O que o sistema faz

Para cada item de um arquivo JSON, o programa:

1. valida os campos recebidos;
2. pergunta quais campos adicionais, além de nome, serão usados na comparação;
3. procura uma correspondência exata no catálogo, ignorando caixa, acentos e pontuação;
4. quando não há igualdade exata, seleciona no máximo 100 candidatos compatíveis e ordena os 5 mais parecidos;
5. pede ao agente de IA uma decisão somente para esses candidatos, quando houver ambiguidade;
6. cria um produto apenas quando não há uma correspondência segura;
7. registra o vínculo entre vendedor e produto.

As alterações em `Product` e `SellerProduct` são gravadas em uma única transação SQLite. Se a importação falhar durante o planejamento ou a gravação, o banco não fica parcialmente importado.

## Estrutura do repositório

| Caminho | Responsabilidade |
| --- | --- |
| `src/catalog_consolidator/cli.py` | Ponto de entrada, leitura da configuração e mensagens no terminal. |
| `src/catalog_consolidator/service.py` | Planejamento da consolidação e decisões de progresso. |
| `src/catalog_consolidator/repository.py` | Leitura e escrita no SQLite, preparação de índices e transação. |
| `src/catalog_consolidator/matching.py` | Filtro determinístico e ordenação de candidatos. |
| `src/catalog_consolidator/agent.py` | Agente LangChain somente de leitura para casos ambíguos. |
| `src/catalog_consolidator/domain.py` | Validação dos dados de entrada e objetos do domínio. |
| `data/` | Banco e feeds de exemplo para execução local. |
| `tests/` | Suíte de testes automatizados. |
| `docs/` | Material original do desafio e seus arquivos de referência. |

## Pré-requisitos

- Python 3.11 ou superior;
- [uv](https://docs.astral.sh/uv/), para sincronizar dependências e executar os comandos;
- uma chave da OpenAI, somente se o feed contiver itens ambíguos que precisem ser avaliados pelo agente;
- SQLite, já incluído na biblioteca padrão do Python.

## Instalação e configuração

No diretório do projeto:

```bash
cp .env.example .env
uv sync
```

Edite `.env` e preencha os valores:

```dotenv
OPENAI_API_KEY=sua_chave
OPENAI_MODEL=gpt-4.1-mini
CATALOG_DATABASE=data/catalog.db
CATALOG_INPUT=data/ProductEntry.json
CATALOG_MATCH_THRESHOLD=0.72
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=http://localhost:3000
LANGFUSE_PROMPT_LABEL=local
```

`OPENAI_API_KEY` é lida pelo cliente da OpenAI. O arquivo `.env` não deve ser versionado e variáveis já definidas no ambiente têm precedência sobre seus valores.

### Configurações

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `OPENAI_API_KEY` | Para casos ambíguos | Chave usada pelo cliente da OpenAI. |
| `OPENAI_MODEL` | Sim | Modelo a ser usado pelo agente. |
| `CATALOG_DATABASE` | Sim | Caminho do banco SQLite a consolidar. |
| `CATALOG_INPUT` | Sim | Caminho do arquivo JSON de produtos de vendedores. |
| `CATALOG_MATCH_THRESHOLD` | Não | Limite de similaridade entre `0` e `1`; o padrão é `0.72`. |
| `LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY` | Não | Habilitam prompt versionado, tracing e scores no Langfuse. |
| `LANGFUSE_BASE_URL` | Não | URL da instância Langfuse; localmente, `http://localhost:3000`. |
| `LANGFUSE_PROMPT_LABEL` | Não | Label da versão do prompt a usar; localmente, `local`. |
| `LANGFUSE_RELEASE` | Não | Identificador da versão do código exibido nos traces; localmente, `local`. |

Um limite menor envia mais casos para avaliação do agente, o que pode elevar custo e tempo. Um limite maior é mais restritivo e tende a criar mais produtos novos quando não há correspondência exata.

### Langfuse local

Suba a instância local e abra `http://localhost:3000`:

```bash
docker compose -f compose.langfuse.yml up -d
```

No primeiro acesso, crie uma conta, uma organização e um projeto. Copie as chaves pública e secreta do projeto para `LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY` no `.env`. Para criar a versão inicial do prompt, execute:

```bash
uv run catalog-langfuse-bootstrap
```

Com as variáveis `LANGFUSE_*` configuradas, cada consolidação cria uma sessão com spans de planejamento e persistência. Cada decisão ambígua é rastreada pelo callback do LangChain, vinculada à versão do prompt e avaliada pelos evaluators `catalog_decision_allowed` e `catalog_decision_type`. Esses checks verificam integridade da política; o dataset de avaliação deve receber gabaritos revisados para medir qualidade semântica.

Para parar os containers, use `docker compose -f compose.langfuse.yml down`. Os dados ficam em volumes Docker; para apagá-los também, use `docker compose -f compose.langfuse.yml down -v`.

### Preservar o banco de exemplo

A importação modifica o banco apontado por `CATALOG_DATABASE`. Para experimentar sem alterar `data/catalog.db`, use uma cópia local:

```bash
cp data/catalog.db /tmp/catalog-local.db
```

Então defina `CATALOG_DATABASE=/tmp/catalog-local.db` no `.env`.

## Como executar

Com o `.env` configurado:

```bash
uv run catalog-consolidate
```

Não há argumentos de linha de comando; toda a configuração vem do `.env` ou de variáveis de ambiente exportadas.

Antes de ler o feed, a CLI usa Nome obrigatoriamente e pergunta se Marca e/ou Categoria também devem participar da comparação. Digite `1`, `2` ou `1,2`; pressione Enter para comparar somente pelo Nome. A escolha vale apenas para a execução atual.

Para usar o feed com casos mais ambíguos disponível no repositório, altere temporariamente a configuração:

```dotenv
CATALOG_INPUT=data/ProductEntry-ambiguous.json
```

## Formato de entrada

O arquivo de entrada deve ser um array JSON. Cada objeto precisa ter os campos abaixo:

```json
[
  {
    "Id": "identificador-do-produto-no-vendedor",
    "SellerName": "Nome do vendedor",
    "Name": "Nome do produto",
    "Brand": "Marca opcional",
    "Category": "Categoria"
  }
]
```

`Id`, `SellerName`, `Name` e `Category` não podem ficar vazios. `Brand` pode ser nula, mas, se fornecida, não pode ficar vazia. Espaços nas extremidades são removidos durante a validação.

## O que esperar durante a execução

O terminal informa a leitura do feed, a inspeção do catálogo, o andamento da comparação, a gravação e um resumo final. Para cada item, ele exibe uma das mensagens simples abaixo:

| Resultado | Significado |
| --- | --- |
| `já estava no catálogo` | Nome, marca e categoria normalizados identificaram um produto existente. |
| `achei um igual` | O agente confirmou, com alta confiança, um dos candidatos permitidos. |
| `é um produto novo` | Não houve candidato seguro; um produto será criado. |
| `já apareceu neste arquivo` | O mesmo produto novo já foi encontrado anteriormente no feed e compartilhará a criação planejada. |
| `é uma repetição; deixei de lado` | O mesmo vendedor enviou novamente o mesmo identificador de origem. |

Uma saída tem este formato geral:

```text
Estou lendo o arquivo...
Estou olhando o catálogo...
Antes: 10 produtos e 4 ofertas.
Agora vou comparar os produtos...
[1 de 3] Loja A: Produto X — já estava no catálogo.
[2 de 3] Loja B: Produto X — achei um igual.
[3 de 3] Loja C: Produto Y — é um produto novo.
Estou guardando tudo...
Pronto!
Li 3 itens.
...
Agora: 11 produtos e 7 ofertas.
```

As decisões internas são códigos tipados (`ProgressDecision`), com uma justificativa técnica separada quando há agente. A CLI mostra somente a frase simples, para não tornar sua saída dependente de detalhes internos ou da justificativa do modelo.

Se houver erro de configuração, arquivo, validação ou execução do agente, a CLI mostra uma instrução curta para conferir os arquivos e tentar novamente, e termina com código de saída `2`.

## Como funciona a consolidação

### Identidade normalizada e igualdade exata

O sistema normaliza nome, marca e categoria: converte para minúsculas, remove acentos, ignora apóstrofos e substitui os demais sinais de pontuação por espaços. Portanto, diferenças de caixa, acentuação ou pontuação não geram produtos distintos.

Na primeira execução, o banco recebe as colunas `NormalizedName`, `NormalizedBrand` e `NormalizedCategory` na tabela `Product`, quando elas ainda não existem. Também são criados os índices `idx_product_identity`, `idx_product_candidates_by_brand` e `idx_product_candidates_by_category`.

### Casos parecidos e agente

Quando a identidade exata não existe, o repositório busca candidatos pela marca e categoria normalizadas. Se essa combinação não encontrar nada, procura por marca; quando não há marca, procura por categoria. A busca é limitada a 100 produtos.

O programa ordena os candidatos por similaridade de nome e categoria, incluindo uma comparação com as palavras do nome ordenadas, e envia no máximo 5 ao agente. O agente só pode inspecionar os candidatos fornecidos; ele não escreve no banco. Uma correspondência é aceita apenas se o agente retornar um ID permitido com confiança alta. Qualquer outra resposta resulta na criação planejada de um produto novo.

### Duplicatas e idempotência

- Duas entradas com o mesmo `SellerName` e `Id`, representando o mesmo produto, são ignoradas após a primeira.
- O mesmo `SellerName` e `Id` associado a produtos diferentes interrompe a importação antes de qualquer escrita.
- Um produto novo repetido no mesmo feed é criado uma única vez e pode receber vários vínculos de vendedor.
- Executar novamente o mesmo plano não duplica vínculos já existentes entre vendedor e produto.

## Banco de dados esperado

O banco SQLite precisa conter estas tabelas e colunas mínimas:

```text
Product(Id, Name, Brand, Category)
SellerProduct(Id, SellerName, ProductId, SellerProductId)
```

O sistema preserva as tabelas existentes e adiciona somente as colunas normalizadas e índices necessários para a consulta. O vínculo `SellerProduct` representa a oferta de um produto por um vendedor.

## Testes

Execute a suíte local com:

```bash
uv run pytest
```

Os testes cobrem validação de entrada e configuração, similaridade, uso do agente com mocks, preparação dos índices SQLite, planejamento, progresso, duplicidade, idempotência e persistência.

## Limitações conhecidas

- A IA é usada apenas para decidir casos ambíguos; ela exige credenciais e pode ter custo.
- Não há modo de revisão manual, modo simulador (dry run) ou parâmetros de linha de comando.
- A interface de erros é intencionalmente curta e não exibe detalhes internos no terminal.
- O projeto é voltado à execução local e ao escopo do desafio, não a operação de produção.
