# Promos

Automação em Python para coletar produtos do Mercado Livre, priorizar ofertas com desconto e executar o fluxo de ofertas relâmpago.

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

## Saídas geradas

- `ofertas_consolidadas_*.txt`: lista consolidada de produtos para envio.
- `historico_anuncios.txt`: histórico de anúncios já enviados, usando o ID do anúncio como chave.
- `ofertas_relampago/html_relampago_*.txt`: HTML salvo do fluxo de ofertas relâmpago.
- `ofertas_relampago/resultado_*.txt`: resultado do fluxo de ofertas relâmpago.
