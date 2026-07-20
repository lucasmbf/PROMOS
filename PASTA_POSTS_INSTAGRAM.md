# 📁 Estrutura de Pastas: Posts Instagram

## 🎯 Onde os Arquivos São Salvos?

### **Arquivos de Posts (Imagens PNG + Captions)**

**Localização padrão:**
```
C:\Users\Lucas Bianco\Desktop\Projetos Dev\Promos\dist-interface\instagram_posts\
```

**Estrutura:**
```
dist-interface/
├── instagram_posts/                    ← 📸 AQUI OS POSTS SÃO SALVOS
│   ├── feed_12345_20260719_143052.png  ← Imagem Feed 1080x1350
│   ├── feed_67890_20260719_143052.png  ← Imagem Feed 1080x1350
│   ├── feed_11111_20260719_143052.png  ← Imagem Feed 1080x1350
│   ├── story_12345_20260719_143052.png ← Imagem Story 1080x1920
│   ├── story_67890_20260719_143052.png ← Imagem Story 1080x1920
│   ├── story_11111_20260719_143052.png ← Imagem Story 1080x1920
│   └── captions_20260719_143052.txt    ← 📝 TODOS OS LINKS E DESCRIÇÕES
│
├── ofertas_relampago/
│   ├── Historico de anuncios/          ← JSONs de entrada
│   │   ├── ofertas_20260719_143052.json
│   │   ├── ofertas_20260719_140000.json
│   │   └── ofertas_20260719_130000.json
│   └── html/
│
└── saidas_execucoes/
    ├── Alerta/
    ├── Campanha/
    └── OnDemand/
```

---

## 📊 Resumo do Fluxo de Pastas

| Etapa | Pasta | Arquivos |
|-------|-------|----------|
| **1. Busca Relâmpago** | `dist-interface/ofertas_relampago/Historico de anuncios/` | `ofertas_*.json` |
| **2. GUI encontra JSON** | (mesma pasta acima) | Usa o mais recente |
| **3. Gera Posts** | `dist-interface/instagram_posts/` | `feed_*.png` + `story_*.png` + `captions_*.txt` |
| **4. Salva também em:** | `dist-interface/saidas_execucoes/Alerta\|Campanha\|OnDemand/` | (copy dos JSONs) |

---

## 🔍 Verificar os Arquivos Gerados

### **Abrir a pasta automaticamente:**
- Após clicar "Gerar Posts Instagram"
- Sistema abre a pasta `instagram_posts/` automaticamente
- Vendo seus arquivos PNG e arquivo de captions

### **Abrir manualmente:**
```
Explorador de Arquivos → 
  Desktop → Projetos Dev → Promos → dist-interface → instagram_posts
```

---

## 📋 Conteúdo de Cada Arquivo

### **Imagens PNG (feed_*.png e story_*.png)**
```
Tamanho: ~200-500 KB cada
Formato: PNG (melhor qualidade)
Dimensões:
  - Feed: 1080x1350 pixels
  - Story: 1080x1920 pixels
Conteúdo:
  • Categoria do produto
  • Nome/descrição
  • Preço anterior (riscado)
  • Preço novo (em verde)
  • Desconto % (em vermelho)
  • Timestamp da busca
```

### **Arquivo de Captions (captions_*.txt)**
```
Tamanho: ~5-20 KB
Formato: Texto UTF-8
Conteúdo:
  • Descrição de cada produto
  • Link clicável (Mercado Livre)
  • Hashtags prontas
  • Instruções de uso
  • Dicas de posting
```

---

## ✅ O Que Fazer Depois

1. **Abrir a pasta Instagram posts:**
   - Lá você encontrará todas as imagens PNG
   - E o arquivo de captions com os links

2. **Usar as imagens:**
   - Baixe para seu computador/celular
   - Upload no Instagram
   - Cole a caption correspondente

3. **Usar os links:**
   - Estão no arquivo `captions_*.txt`
   - Cola na descrição/comentários
   - Ou use em Stories com sticker de link

---

## 🚀 Exemplo Real

**Você executou uma busca com 3 produtos:**

**Arquivos gerados:**
```
instagram_posts/
├── feed_AAA_20260719_143052.png      ← Produto 1 (Feed)
├── feed_BBB_20260719_143052.png      ← Produto 2 (Feed)
├── feed_CCC_20260719_143052.png      ← Produto 3 (Feed)
├── story_AAA_20260719_143052.png     ← Produto 1 (Story)
├── story_BBB_20260719_143052.png     ← Produto 2 (Story)
├── story_CCC_20260719_143052.png     ← Produto 3 (Story)
└── captions_20260719_143052.txt      ← Todas as descrições + links
```

**Arquivo captions_20260719_143052.txt contém:**
```
📷 POSTS FEED (3 imagens)
========================

--- FEED #1 ---
🔥 iPhone 14 Pro
50% OFF | R$ 3.999
Link: https://mercadolivre.com.br/...

--- FEED #2 ---
🔥 Samsung Galaxy S23
40% OFF | R$ 2.999
Link: https://mercadolivre.com.br/...

--- FEED #3 ---
🔥 Google Pixel 7
35% OFF | R$ 2.499
Link: https://mercadolivre.com.br/...

📱 POSTS STORY (3 imagens)
==========================
... (mesmo conteúdo)
```

---

## 💾 Dados Importantes

- **Pasta padrão:** `dist-interface/instagram_posts/`
- **Espaço necessário:** ~5-10 MB por 100 produtos
- **Retenção:** Todos os posts ficam lá (nunca é limpo automaticamente)
- **Backup:** Recomendado fazer backup dessa pasta periodicamente

---

## 🔄 Próximas Execuções

Cada vez que gera posts:
- **Novos arquivos** são criados com timestamp diferente
- **Antigos não são deletados** (você pode reutilizar)
- Pasta continua crescendo ao longo do tempo

Para limpar:
- Delete arquivos antigos manualmente
- Ou renomeie para "instagram_posts_backup" e crie nova pasta

---

**Resumo:** Posts são salvos em `dist-interface/instagram_posts/` e folder abre automaticamente! 🚀
