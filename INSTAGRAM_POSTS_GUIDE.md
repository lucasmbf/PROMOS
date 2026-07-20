# 📸 Guia de Uso: Gerar Posts Instagram

## Visão Geral

O sistema de geradores agora permite criar posts otimizados para Instagram **automaticamente** a partir dos resultados de suas buscas (Relâmpago, Produtos, Alertas).

**Fluxo completo:**
```
Executar Busca → JSON gerado automaticamente → Botão "Gerar Posts Instagram" → Escolher formato → Posts prontos
```

---

## 🚀 Como Usar

### 1️⃣ Execute uma Busca

Qualquer uma das opções gera um JSON automaticamente:
- **"BUSCAR PRODUTO"** — Busca na home do Mercado Livre
- **"BUSCAR OFERTAS RELÂMPAGO"** — Coleta ofertas com desconto
- **"CONFIGURAR ALERTA DE PREÇO"** — Monitora preços (gera JSON ao detectar redução)

### 2️⃣ Clique em "📸 GERAR POSTS INSTAGRAM"

Localize o botão na seção **"PROGRAMAÇÕES"** (rodapé da interface).

### 3️⃣ Selecione o Formato

Uma janela será aberta com 3 opções:

| Formato | Dimensões | Uso |
|---------|-----------|-----|
| 📷 **Feed** | 1080×1350 px | Posts no feed principal |
| 📱 **Stories** | 1080×1920 px | Stories efêmeras |
| 📸 **Ambos** | Feed + Stories | Máxima cobertura |

O sistema **automaticamente** usa o JSON mais recente gerado.

### 4️⃣ Aguarde a Geração

- ⏳ Processamento em tempo real
- 🎨 Cada oferta gera 1 ou 2 imagens (conforme formato)
- ✅ Ao concluir, uma janela oferece **abrir a pasta** diretamente

---

## 📁 Estrutura de Saída

**Localização padrão:** `dist-interface/instagram_posts/`

**Nomes de arquivos:**
```
feed_123456_20260719_143052.png     ← Feed (ID da oferta + timestamp)
story_123456_20260719_143052.png    ← Story (mesma oferta)
feed_654321_20260719_143102.png     ← Próxima oferta...
story_654321_20260719_143102.png
```

---

## 📝 O Que Aparece em Cada Post

### Feed (1080×1350)
```
┌─────────────────┐
│ CATEGORIA       │ ← Nome da categoria
├─────────────────┤
│ Descrição do    │ ← Até 3 linhas
│ Produto XYZ     │
├─────────────────┤
│ ~~R$ 100,00~~   │ ← Preço anterior (riscado)
├─────────────────┤
│ R$ 70,00        │ ← Novo preço (verde)
├─────────────────┤
│ ┌─────────────┐ │
│ │  35% OFF    │ │ ← Desconto (destaque vermelho)
│ └─────────────┘ │
├─────────────────┤
│ 🔗 mercadolivre │ ← Link clicável
├─────────────────┤
│ Gerado: 19/07.. │ ← Timestamp
└─────────────────┘
```

### Story (1080×1920)
```
┌─────────────────┐
│ 🏷️ CATEGORIA   │
├─────────────────┤
│                 │
│ Descrição       │ ← Maior, mais destaque
│ Produto XYZ     │
│                 │
├─────────────────┤
│   ┌───────────┐ │
│   │ 35% OFF   │ │ ← Desconto muito grande
│   └───────────┘ │
├─────────────────┤
│ De: R$ 100,00   │ ← Preço anterior
│ Por: R$ 70,00   │ ← Novo preço (verde)
├─────────────────┤
│ 👉 TAP p/OFERTA │ ← CTA (Call-To-Action)
└─────────────────┘
```

---

## ⚙️ Requisitos

**Necessário instalado:**
```bash
pip install Pillow
```

**Se receber erro:** "Módulo generators não disponível"
```bash
pip install Pillow
```

---

## 🔄 Fluxo Completo Exemplo

```
1. Você clica "BUSCAR OFERTAS RELÂMPAGO"
   ↓
2. Sistema executa busca e gera:
   - lista_anuncios.txt (como antes)
   - ofertas_20260719_143052.json (NOVO)
   ↓
3. Você clica "📸 GERAR POSTS INSTAGRAM"
   ↓
4. Dialog abre: "Qual formato?"
   - [•] Feed
   - [ ] Stories
   - [ ] Ambos
   ↓
5. Você seleciona "Ambos" e clica "Gerar Posts"
   ↓
6. Sistema cria:
   - feed_offer1_20260719_143055.png
   - story_offer1_20260719_143055.png
   - feed_offer2_20260719_143056.png
   - story_offer2_20260719_143056.png
   (etc.)
   ↓
7. Dialog: "Posts gerados! Abrir pasta?"
   - [Sim] [Não]
   ↓
8. Pasta abre no explorador de arquivos
   ↓
9. Você faz upload das imagens para Instagram!
```

---

## 💡 Dicas

✅ **Gere múltiplos formatos:** A cada busca, você pode gerar feed, story, ou ambos

✅ **Organização:** Cada busca cria um novo JSON com timestamp, mantendo histórico

✅ **Customização:** Você pode editar as imagens geradas com ferramentas externas (Photoshop, GIMP, etc.)

✅ **Automação:** Execute buscas programadas (campanhas/alertas) e gere posts automaticamente

---

## 🐛 Troubleshooting

### Botão não aparece
**Causa:** Módulo `generators` não importado
**Solução:** 
```bash
pip install Pillow
# E reinicie a aplicação
```

### "Nenhum JSON encontrado"
**Causa:** Você ainda não executou nenhuma busca
**Solução:** Clique em "BUSCAR PRODUTOS" ou "BUSCAR OFERTAS RELÂMPAGO" primeiro

### Imagens com fonte estranha
**Causa:** Fontes do sistema não encontradas
**Solução:** As imagens ainda funcionam, mas com fonte padrão. Instale fontes:
- **Windows:** Já incluído
- **Linux:** `sudo apt-get install fonts-dejavu`
- **Mac:** Já incluído

### "Erro ao gerar posts"
**Causa:** Pasta de saída sem permissão
**Solução:** Verifique se `dist-interface/instagram_posts/` tem permissão de escrita

---

## 📚 Referência Técnica

**Funções utilizadas:**
```python
# Importadas de generators/
- gerar_posts_em_lote()        # Processa lotes de ofertas
- gerar_post_feed()            # Cria Feed individual
- gerar_post_story()           # Cria Story individual

# Importadas de generators_helper.py
- listar_jsons_ofertas()       # Lista JSONs disponíveis
- gerar_posts_instagram_para_json_recente()  # Helper
```

**Estrutura do JSON de entrada:**
```json
{
  "timestamp": "20260719_143052",
  "total": 5,
  "ofertas": [
    {
      "id_anuncio": "123456",
      "categoria": "Eletrônicos",
      "descricao": "Notebook...",
      "antes": "R$ 4.500,00",
      "antes_valor": 4500.0,
      "desconto": "35% OFF",
      "depois": "R$ 2.925,00",
      "depois_valor": 2925.0,
      "link_anuncio": "https://..."
    }
  ]
}
```

---

## 🎯 Próximas Melhorias Planejadas

- [ ] Preview das imagens dentro do dialog
- [ ] Adicionar logo/watermark personalizado
- [ ] Importar imagem do produto automaticamente
- [ ] Gerar QR code dinâmico
- [ ] Exportar como HTML para preview
- [ ] Integração direta com API do Instagram (upload automático)

---

## 📞 Suporte

Problema? Verifique:
1. ✅ Pillow instalado: `pip list | grep Pillow`
2. ✅ Pasta exists: `ls dist-interface/instagram_posts/`
3. ✅ JSON gerado: `ls dist-interface/ofertas_relampago/Historico\ de\ anuncios/`
