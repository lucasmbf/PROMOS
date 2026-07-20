# 📸 Gerador de Posts Instagram

Módulo para gerar imagens otimizadas para Instagram (Feed e Stories) a partir dos JSONs de ofertas gerados pelo sistema.

## 🎯 Recursos

- ✅ Gera posts para **Feed Instagram** (1080x1350 px)
- ✅ Gera posts para **Stories Instagram** (1080x1920 px)
- ✅ Processa lotes de ofertas
- ✅ Personalização de cores e layouts
- ✅ Informações destacadas: preço anterior, novo preço, desconto
- ✅ Link da oferta clicável
- ✅ Timestamp de geração

## 📦 Instalação

### Pré-requisito: Pillow

```bash
# Dentro do ambiente virtual do projeto
pip install Pillow

# Ou se estiver usando poetry
poetry add Pillow

# Ou se estiver usando conda
conda install pillow
```

## 🚀 Uso

### 1. Via Terminal (CLI)

```bash
# Gerar ambos (feed + story)
python generators/instagram_post_generator.py dist-interface/ofertas_relampago/Historico\ de\ anuncios/ofertas_20260719_143052.json ambos

# Apenas Feed
python generators/instagram_post_generator.py dist-interface/ofertas_relampago/Historico\ de\ anuncios/ofertas_20260719_143052.json feed

# Apenas Stories
python generators/instagram_post_generator.py dist-interface/ofertas_relampago/Historico\ de\ anuncios/ofertas_20260719_143052.json story
```

### 2. Via Helper (mais simples)

```bash
# Gera posts do JSON mais recente em uma pasta
python generators_helper.py dist-interface/ofertas_relampago/Historico\ de\ anuncios ambos
```

### 3. Em Código Python

```python
from generators import gerar_posts_em_lote

# Gerar posts de um JSON
resultado = gerar_posts_em_lote(
    caminho_json="dist-interface/ofertas_relampago/Historico de anuncios/ofertas_20260719_143052.json",
    formatos=["feed", "story"],  # ou ["feed"] ou ["story"]
    pasta_saida="dist-interface/instagram_posts"  # opcional
)

# resultado = {
#     'feed': ['/path/to/feed_123_20260719.png', ...],
#     'story': ['/path/to/story_123_20260719.png', ...]
# }

print(f"Feed: {len(resultado['feed'])} imagens")
print(f"Story: {len(resultado['story'])} imagens")
```

## 📁 Saída

Os posts são salvos em: `dist-interface/instagram_posts/`

Estrutura de nomes:
- Feed: `feed_{id_anuncio}_{timestamp}.png`
- Story: `story_{id_anuncio}_{timestamp}.png`

## 🎨 Personalização

### Cores Padrão

```python
from generators import gerar_post_feed

gerar_post_feed(
    oferta={"categoria": "...", "descricao": "...", ...},
    tamanho=(1080, 1350),
    cor_fundo=(245, 245, 245),      # Cinza claro
    cor_desconto=(220, 20, 60),     # Vermelho
)
```

### Formatos Suportados

| Formato | Dimensões | Uso |
|---------|-----------|-----|
| Feed | 1080x1350 px | Posts no feed principal |
| Story | 1080x1920 px | Stories efêmeras |

## 📝 Estrutura do JSON de Entrada

O JSON deve ter este formato (gerado por `salvar_resultado_relampago_json`):

```json
{
  "timestamp": "20260719_143052",
  "total": 5,
  "ofertas": [
    {
      "id_anuncio": "123456",
      "categoria": "Eletrônicos",
      "descricao": "Notebook gamer 16GB RAM",
      "antes": "R$ 4.500,00",
      "antes_valor": 4500.0,
      "desconto": "35% OFF",
      "depois": "R$ 2.925,00",
      "depois_valor": 2925.0,
      "link_anuncio": "https://www.mercadolivre.com.br/..."
    }
  ]
}
```

## 🔧 Troubleshooting

### Erro: `ModuleNotFoundError: No module named 'PIL'`

```bash
pip install Pillow
```

### Fonte não encontrada (usando fallback)

Se as fontes do sistema não forem encontradas, o gerador usa a fonte padrão do Pillow. Para melhor resultado, instale fontes:

**Windows:**
```powershell
# As fontes padrão estão em C:\Windows\Fonts
```

**Linux:**
```bash
sudo apt-get install fonts-dejavu fonts-liberation
```

**macOS:**
```bash
# Fontes já incluídas no sistema
```

## 📊 Exemplos de Layout

### Feed (1080x1350)
```
┌─────────────────────┐
│   CATEGORIA         │
├─────────────────────┤
│                     │
│  Descrição do       │
│  Produto em até     │
│  3 linhas           │
│                     │
│  ~~R$ 4.500,00~~   │
│                     │
│  R$ 2.925,00       │
│                     │
│  ┌────────────────┐ │
│  │  35% OFF       │ │
│  └────────────────┘ │
│                     │
│  🔗 mercadolivre... │
│                     │
│  Gerado: 19/07...  │
└─────────────────────┘
```

### Story (1080x1920)
```
┌─────────────────────┐
│  🏷️ CATEGORIA      │
├─────────────────────┤
│                     │
│  Descrição do       │
│  Produto            │
│                     │
│     ┌─────────────┐ │
│     │  35% OFF    │ │
│     └─────────────┘ │
│                     │
│  De: R$ 4.500,00   │
│  Por: R$ 2.925,00  │
│                     │
│  👉 TAP p/ OFERTA  │
└─────────────────────┘
```

## 🚀 Próximas Melhorias

- [ ] Adicionar imagem do produto (download automático)
- [ ] Gerar QR code dinâmico para link
- [ ] Templates customizáveis por brand
- [ ] Suporte a watermark/logo
- [ ] Exportar como HTML para preview

## 📄 Licença

Mesmo da aplicação Promos.
