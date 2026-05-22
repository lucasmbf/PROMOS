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

## Como executar

Use o Python do ambiente virtual:

```powershell
.\venv\Scripts\python.exe main.py
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

## Saídas geradas

- `ofertas_consolidadas_*.txt`: lista consolidada de produtos para envio.
- `historico_anuncios.txt`: histórico de anúncios já enviados, usando o ID do anúncio como chave.
- `ofertas_relampago/html_relampago_*.txt`: HTML salvo do fluxo de ofertas relâmpago.
- `ofertas_relampago/resultado_*.txt`: resultado do fluxo de ofertas relâmpago.
