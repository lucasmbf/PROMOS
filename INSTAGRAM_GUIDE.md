# 📸 Guia Completo: Gerar e Postar no Instagram

## ❓ Respondendo suas perguntas

### 1️⃣ **"Ele gera posts do histórico inteiro ou só da busca mais recente?"**

✅ **Apenas da busca mais recente!**

- A GUI encontra TODOS os JSONs disponíveis
- **Ordena por data** (mais recente primeiro)
- **Pega apenas o primeiro** (o mais recente)
- Você escolhe qual formato (Feed/Story/Ambos)
- ✅ **Nunca mistura dados antigos**

---

### 2️⃣ **"Como é salvo? É uma imagem com texto ou como?"**

**3 tipos de arquivos são criados:**

#### **A) Imagens PNG** (Visual para Instagram)
```
feed_12345_20260719_143052.png      ← Imagem 1080x1350
feed_67890_20260719_143052.png      ← Imagem 1080x1350
story_12345_20260719_143052.png     ← Imagem 1080x1920
story_67890_20260719_143052.png     ← Imagem 1080x1920
```

**Contém:**
- ✅ Categoria (ex: "Eletrônicos")
- ✅ Descrição do produto
- ✅ Preço anterior (riscado)
- ✅ Preço novo (em verde)
- ✅ Desconto em % (em vermelho, destacado)
- ✅ Timestamp da busca

**Uso:** Você faz o upload diretamente no Instagram

#### **B) Arquivo de Captions** (Descrições + Links)
```
captions_20260719_143052.txt
```

**Contém:**
```
📷 POSTS FEED (3 imagens)
===========================

--- FEED #1 ---
🔥 PRODUTO #1

iPhone 14 Pro - 256GB

50% OFF
Apenas R$ 3.999,00

🔗 Link: https://mercadolivre.com.br/...

#promoção #desconto #oferta #mercadolivre

--- FEED #2 ---
...
```

**Uso:** Você **copia e cola** no Instagram

---

### 3️⃣ **"Como o usuário clica no link se está embedded na imagem?"**

✅ **O link NÃO fica embedded na imagem!**

**Aqui está o fluxo correto:**

#### **Para Feed Posts:**
1. ✅ Você faz upload da imagem PNG no Instagram
2. ✅ Na **descrição do post**, você cola o caption
3. ✅ O caption **contém o link clicável**
4. ✅ Usuários clicam no link **na descrição**

Exemplo do que aparece:
```
🔥 PRODUTO #1 - iPhone 14 Pro

50% OFF | Apenas R$ 3.999,00

🔗 Link: https://bit.ly/3X4K9z  ← CLICÁVEL AQUI!

#promoção #desconto #mercadolivre
```

#### **Para Stories:**
1. ✅ Você faz upload da imagem PNG no Story
2. ✅ Adiciona o **sticker "Link"** (adesivo de link)
3. ✅ Cola a URL da oferta
4. ✅ Quando usuário clica, **abre o link automaticamente**

---

## 📁 Resumo dos Arquivos

| Arquivo | Tipo | Uso | Clicável? |
|---------|------|-----|-----------|
| `feed_*.png` | Imagem PNG | Upload no Instagram | ✅ (via descrição) |
| `story_*.png` | Imagem PNG | Upload em Story | ✅ (via sticker) |
| `captions_*.txt` | Texto | Copiar/colar descrição | ✅ (links) |

---

## 🚀 Workflow Passo a Passo

### **No App do Promos (GUI):**
```
1. Clique "PROCURAR OFERTAS RELAMPAGO"
   ↓
2. Configure filtros (categoria, preço, etc)
   ↓
3. Escolha pasta de saída
   ↓
4. ✅ JSON salvo AUTOMATICAMENTE
   ↓
5. Clique "📸 GERAR POSTS INSTAGRAM"
   ↓
6. Selecione formato (Feed/Story/Ambos)
   ↓
7. Recebe: 5 PNGs + 1 arquivo de captions
   ↓
8. Pasta aberta automaticamente
```

### **No Instagram (Web ou App):**

#### **Opção A: Feed (Desktop Recomendado)**
```
1. Acesse Instagram.com
   ↓
2. Clique em "Criar" (+)
   ↓
3. Selecione feed_*.png
   ↓
4. Copie e cole o caption do arquivo .txt
   ↓
5. O link fica CLICÁVEL na descrição
   ↓
6. Publique!
```

#### **Opção B: Stories (Celular Recomendado)**
```
1. Abra app do Instagram
   ↓
2. Clique em "Story" (seu avatar)
   ↓
3. Selecione story_*.png
   ↓
4. Toque em "Aa" (adicionar texto) ou clique em sticker
   ↓
5. Procure por "Link" sticker
   ↓
6. Cole a URL do caption
   ↓
7. Publique!
```

---

## 💡 Dicas Importantes

### ✅ **O que Funciona**
- Links na **descrição do post** (Feed)
- Sticker de **link em Stories**
- **URL encurtada** com bit.ly (mais bonito)
- Posts agendados via Buffer/Later

### ❌ **O que NÃO Funciona**
- Link dentro da imagem (não é clicável)
- Copiar imagem sem descrição (ninguém sabe o preço)
- Postar sem validar links

### 📌 **Melhor Momento para Postar**
- **Terça a quinta**: 14h-16h
- **Noite**: 18h-21h (pico de atividade)
- **Fim de semana**: 11h-14h

---

## 🎯 Exemplo Real

**Você faz busca e recebe:**
- `feed_12345_20260719_143052.png` (Imagem)
- `feed_67890_20260719_143052.png` (Imagem)
- `feed_11111_20260719_143052.png` (Imagem)
- `captions_20260719_143052.txt` (Texto)

**Você copia do .txt:**
```
🔥 NOVO IPHONE 14!

50% OFF
Apenas R$ 3.999,00

🔗 Compre agora: https://bit.ly/3X4K9z

#promoção #desconto #oferta
```

**No Instagram:**
1. Upload da imagem
2. Cola a descrição
3. Usuário vê a imagem + descrição com link
4. **Clica no link → vai para Mercado Livre** ✅

---

## 📊 Resumo

| Pergunta | Resposta |
|----------|----------|
| Histórico inteiro ou recente? | ✅ **Apenas o mais recente** |
| Como é salvo? | ✅ **PNG + arquivo de captions** |
| Link fica na imagem? | ❌ **Não, fica na descrição** |
| Como usuário clica? | ✅ **Clica no link da descrição/story** |
| Preciso editar depois? | ✅ **Pode editar captions_*.txt** |

---

## ❓ FAQ

**P: Se achei 5 produtos, recebo 5 posts?**
R: ✅ Sim! 5 imagens PNG diferentes + 5 captions no arquivo .txt

**P: Posso mudar o link depois?**
R: ✅ Sim! Edite o arquivo `captions_*.txt` antes de postar

**P: O link é encurtado?**
R: ❌ Não. Use `bit.ly` para encurtar URLs longas

**P: Onde aparecem as hashtags?**
R: ✅ No arquivo de captions. Você copia tudo junto

**P: Posso usar em múltiplas contas?**
R: ✅ Sim! Sem problema

---

Pronto! Agora você entende o fluxo completo! 🚀
