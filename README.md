# Promos

Automação em Python para coletar produtos do Mercado Livre, priorizar ofertas com desconto e executar o fluxo de ofertas relâmpago.

## Funcionalidades

- Coleta principal no hub de afiliados do Mercado Livre com filtro por categoria.
- Filtro por faixa de preço com parâmetros de preço mínimo e preço máximo.
- Filtro por desconto mínimo nas buscas.
- Priorização de cards com marcador de oferta imperdível na coleta principal.
- Encurtamento/obtenção de link de afiliado por produto aprovado.
- Envio de produtos aprovados por WhatsApp via Twilio (fluxo principal).
- Controle de histórico de anúncios enviados por ID para evitar repetição.
- Controle de histórico de preços para evitar reenviar item com preço pior.
- Fluxo de ofertas relâmpago com extração de dados a partir de HTML salvo.
- Modo relâmpago padrão: todas as categorias, preço máximo de R$ 400, desconto mínimo de 30% e seleção de 10 anúncios inéditos.
- Busca manual por descrição de produto na pesquisa genérica do Mercado Livre.
- Seleção do menor preço no modo manual de busca por descrição.
- Entrada no anúncio escolhido para extração de link de afiliado.
- Geração de executável por categoria para uso no Agendador de Tarefas do Windows.
- Suporte a parâmetros extras nos executáveis gerados.
- Geração de arquivos de saída com resultados consolidados e resultados de ofertas relâmpago.
- Interface com botão de alerta de preço e configuração de checagem agendada.
- Alerta sempre por URL com suporte a até 5 links por configuração.
- Descrição do produto usada como validação do link informado.
- Ciclo de alerta fixo em 1 hora.
- Importação opcional de alertas a partir de planilha Google (polling a cada 10 minutos).

## Especificação funcional

### Índice da seção

- [1. Escopo](#1-escopo)
- [2. Fluxos funcionais](#2-fluxos-funcionais)
- [3. Saídas e persistência](#3-saídas-e-persistência)
- [4. Regras de negócio](#4-regras-de-negócio)
- [5. Limitações atuais e planejado](#5-limitações-atuais-e-planejado)

### 1. Escopo

O sistema Promos automatiza coleta e seleção de ofertas do Mercado Livre com três formas principais de operação:

- Execução sob demanda (CLI ou interface), para rodar imediatamente.
- Campanhas agendadas, com configuração de ciclo em horas.
- Alertas de preço, por URL ou por descrição de produto.

O objetivo funcional é identificar candidatos válidos, aplicar filtros de preço e desconto, evitar repetição de anúncios e salvar resultados em arquivos de histórico e saídas por modalidade.

### 2. Fluxos funcionais

#### 2.1 Fluxo sob demanda

1. Usuário executa o processo por linha de comando ou pela interface.
2. O sistema coleta ofertas (hub ou relâmpago) conforme parâmetros.
3. Aplica filtros de preço, desconto e limite de produtos/candidatos.
4. Remove itens já enviados com base no histórico.
5. Salva resultados consolidados e registra histórico.
6. Persiste também a saída na modalidade OnDemand.

#### 2.2 Fluxo de campanha agendada

1. Usuário cria/edita configuração na área Programações da interface.
2. Define ciclo (horas), filtros e quantidade de candidatos válidos.
3. Ao salvar, pode opcionalmente executar na hora.
4. O agendador interno monitora next_run_at e dispara quando devido.
5. Cada execução grava saída na modalidade Campanha.

#### 2.3 Fluxo de alerta de preço

1. Usuário cria alerta por URL informando descrição, preço desejado e contatos.
2. O primeiro processamento é executado automaticamente ao criar o alerta.
3. O agendador interno monitora next_check_at e reexecuta no ciclo fixo de 1 hora.
4. A descrição serve como validação do produto do anúncio carregado pelo link.
5. Quando encontra preço menor ou igual ao desejado, gera notificação e persistência da execução na modalidade Alerta.

### 3. Saídas e persistência

| Tipo | Caminho | Formato | Estratégia de escrita | Origem |
| --- | --- | --- | --- | --- |
| Histórico de anúncios enviados | historico_anuncios.txt | texto | append por item/processo | Fluxos gerais |
| Consolidação geral de ofertas | ofertas_consolidadas_*.txt | texto | arquivo por execução | Fluxo sob demanda/hub |
| HTML de relâmpago | ofertas_relampago/html_relampago_*.txt | texto (HTML bruto) | arquivo por página/coleta | Fluxo relâmpago |
| Resultado relâmpago | ofertas_relampago/resultado_*.txt | texto | arquivo por execução | Fluxo relâmpago |
| Saída por modalidade Alerta | saidas_execucoes/Alerta/lista_anuncios.txt | texto | append por execução | Alertas |
| Saída por modalidade Campanha | saidas_execucoes/Campanha/lista_anuncios.txt | texto | append por execução | Programações |
| Saída por modalidade OnDemand | saidas_execucoes/OnDemand/lista_anuncios.txt | texto | append por execução | Execuções manuais |

Observações de persistência:

- As pastas de modalidade são criadas automaticamente quando necessário.
- Quando a modalidade não é informada explicitamente, o sistema usa OnDemand como fallback.

### 4. Regras de negócio

- Deduplicação por anúncio já processado via histórico.
- Limite mínimo de 1 hora para ciclos de checagem/execução agendada.
- Preço-alvo de alertas aceita apenas valor decimal válido.
- Alerta de preço é sempre baseado em URL válida do produto.
- Cada alerta aceita no máximo 5 links e apenas 1 e-mail e 1 telefone WhatsApp.
- Telefone de WhatsApp é normalizado com prefixo 55.
- O envio de notificação de um mesmo alerta é limitado a 1 vez por dia enquanto o preço permanecer abaixo do alvo.
- Alertas têm validade padrão de 30 dias e são desativados automaticamente após o vencimento.
- Quantidade de candidatos válidos (campanhas/hub):
	- Se não informada, assume valor padrão 10.
	- Deve ser inteiro maior ou igual a 1.

### 5. Limitações atuais e planejado

Estado atual:

- Backend operacional focado em Mercado Livre.
- Fontes adicionais na interface ainda não executam coleta completa no backend.

Planejado:

- Expansão funcional de fontes adicionais na execução real.
- Evoluções de rastreabilidade e monitoramento das execuções agendadas.

## Como executar

Use o Python do ambiente virtual:

```powershell
.\venv\Scripts\python.exe main.py
```



Ative o ambiente virtual:

```powershell
.\venv\Scripts\Activate.ps1
```
		Gere o executável:
		```powershell
		.\gerar_executavel_interface.ps1



```
Para filtrar por categoria, passe o parâmetro `--categoria` com o nome exato exibido no Mercado Livre:

```powershell
.\venv\Scripts\python.exe main.py --categoria "Games"
```

## Parâmetros disponíveis

- `--categoria`: define a categoria usada na coleta principal.
- `--preco-maximo`: limite superior de preço dos produtos.
- `--preco-minimo`: limite inferior de preço dos produtos.
- `--menor-preco`: prioriza o menor preço dentro dos resultados encontrados.
- `--descricao-produto`: ativa busca manual na pesquisa genérica do Mercado Livre para um produto específico.
- `--limite-paginas-pesquisa`: quantidade de páginas analisadas na busca manual por descrição.
- `--limite-produtos`: quantidade máxima de produtos aceitos por execução.
- `--limite-candidatos`: quantidade máxima de candidatos buscados por tentativa.
- `--desconto-minimo`: desconto mínimo exigido para aceitar o anúncio.
- `--somente-relampago`: executa apenas o fluxo de ofertas relâmpago.

## Categorias disponíveis

As categorias abaixo foram recuperadas do filtro de categorias da página de ofertas do Mercado Livre e podem ser usadas no argumento `--categoria`.

- Acessórios para Veículos
- Agro
- Alimentos e Bebidas
- Arte, Papelaria e Armarinho
- Bebês
- Beleza e Cuidado Pessoal
- Brinquedos e Hobbies
- Calçados, Roupas e Bolsas
- Casa, Móveis e Decoração
- Celulares e Telefones
- Construção
- Câmeras e Acessórios
- Eletrodomésticos
- Eletrônicos, Áudio e Vídeo
- Esportes e Fitness
- Ferramentas
- Festas e Lembrancinhas
- Games
- Indústria e Comércio
- Informática
- Instrumentos Musicais
- Joias e Relógios
- Livros, Revistas e Comics
- Pet Shop
- Saúde

## Exemplos

Executar a coleta principal para uma categoria específica:

```powershell
.\venv\Scripts\python.exe main.py --categoria "Informática"
```

Executar com limite de preço e desconto mínimo ajustados:

```powershell
.\venv\Scripts\python.exe main.py --categoria "Games" --preco-maximo 400 --desconto-minimo 35
```

Executar somente o fluxo de ofertas relâmpago:

```powershell
.\venv\Scripts\python.exe main.py --somente-relampago
```

Busca manual por produto específico (pesquisa genérica) e escolhe menor preço:

```powershell
.\venv\Scripts\python.exe main.py --descricao-produto "air fryer mondial" --menor-preco --limite-paginas-pesquisa 5 --preco-maximo 400
```

Nesse modo manual, o script encontra o candidato válido de menor preço, entra no anúncio, tenta gerar o link de afiliado e salva o resultado.

Executar o modo relâmpago padrão (sem categoria, até R$ 400, mínimo 30% de desconto, 10 inéditos):

```powershell
.\venv\Scripts\python.exe main.py --relampago-padrao
```

No modo `--relampago-padrao`, o fluxo percorre todas as páginas disponíveis de ofertas relâmpago, salva os HTMLs, extrai os candidatos dos `.txt` salvos e seleciona os 10 primeiros anúncios válidos e inéditos por `id_anuncio`.

## Executavel por categoria (para Agendador de Tarefas)

O projeto inclui um script para gerar um `.exe` separado por categoria, mantendo a possibilidade de passar parametros extras no comando.

1. Ajuste as categorias em `categorias_exec.txt` no formato `slug|Categoria`.
2. Gere os executaveis com:

```powershell
.\gerar_executaveis_categoria.ps1
```

Os binarios serao criados em `dist-categorias/` com nomes como:

- `promos_games.exe`
- `promos_informatica.exe`

### Passando parametros extras para um executavel de categoria

Mesmo com categoria fixa, voce ainda pode complementar no PowerShell:

```powershell
.\dist-categorias\promos_games.exe --preco-maximo 350 --desconto-minimo 35
```

### Exemplo no Agendador de Tarefas (Windows)

- Programa/script: caminho completo para o `.exe` da categoria
- Adicionar argumentos (opcional): `--preco-maximo 350 --desconto-minimo 35`
- Iniciar em (opcional): pasta do projeto

> Observacao: para gerar os executaveis, instale o PyInstaller no ambiente virtual:

```powershell
.\venv\Scripts\python.exe -m pip install pyinstaller
```

## Executavel com interface grafica

Foi adicionado um executavel de interface em `gui_promos.py`, com dois quadros principais:

- Procurar produto
- Procurar ofertas relampago

Para gerar o executavel da interface:

```powershell
.\gerar_executavel_interface.ps1
```

Saida esperada:

- `dist-interface/promos_interface.exe`

## Importação de alertas via planilha

O arquivo `integracao_planilha_alertas.json` controla a integração com Google Sheets:

```json
{
	"enabled": false,
	"auth_mode": "oauth_user",
	"spreadsheet_url": "",
	"spreadsheet_id": "",
	"worksheet_name": "Respostas ao formulário 1",
	"oauth_client_file": "credentials/google-oauth-client-secret.json",
	"oauth_token_file": "credentials/google-oauth-token.json",
	"service_account_file": "credentials/google-service-account.json"
}
```

- Se `enabled=true`, a interface tenta importar novas linhas a cada 10 minutos.
- Com `auth_mode=oauth_user`, na primeira execução abre login no navegador e salva token local.
- Novas linhas são identificadas por `Q (agendado) = false`.
- Após importar com sucesso, o sistema grava `Q=true` e `R=dt_criacao`.
- O range A1 é montado com nome da aba entre aspas simples para suportar espaços, parênteses e acentos.
- Mapeamento utilizado:
	- `A`: carimbo de data/hora (informativo)
	- `B`: e-mail
	- `D`: descrição
	- `E`: preço desejado
	- `F`: link 1
	- `G`: telefone
	- `I`: link 2
	- `K`: link 3
	- `M`: link 4
	- `O`: link 5
	- `Q`: agendado
	- `R`: dt_criacao

Na interface:

- O quadro **Procurar produto** permite preencher descricao, fontes, categoria, faixa de preco e desconto minimo.
- O icone `(i)` ao lado de descricao mostra detalhes da funcionalidade ao passar o mouse.
- O quadro **Procurar ofertas relampago** permite usar modo padrao (`--relampago-padrao`) ou modo customizado (`--somente-relampago` com filtros).
- Fontes Amazon, Shoppee e Tiktok Shop aparecem na UI, mas hoje o backend executa apenas Mercado Livre.

## Logs operacionais

Para facilitar diagnóstico das rotinas de alerta e integração com planilha, a interface grava logs em `dist-interface/logs_execucao`:

- `alertas/alertas_AAAAMMDD.log`: ciclo de checagem, validações, erros de extração, geração de link e notificações.
- `planilha/sincronizacao_planilha_AAAAMMDD.log`: início/fim da sincronização, autenticação, leitura da planilha, marcação de linhas e erros.

## Saídas geradas

- `ofertas_consolidadas_*.txt`: lista consolidada de produtos para envio.
- `historico_anuncios.txt`: histórico de anúncios já enviados, usando o ID do anúncio como chave.
- `ofertas_relampago/html_relampago_*.txt`: HTML salvo do fluxo de ofertas relâmpago.
- `ofertas_relampago/resultado_*.txt`: resultado do fluxo de ofertas relâmpago.
