"""
Gerador de Posts Instagram a partir de JSONs de Ofertas.

Cria imagens otimizadas para Instagram (Feed e Stories) com:
- Informações de preço (antes/depois)
- Percentual de desconto destacado
- Categoria e descrição do produto
- Link clicável (URL encurtada)
- Timestamp de execução

Formatos suportados:
  - Feed: 1080x1350 px
  - Story: 1080x1920 px
"""

import os
import json
import textwrap
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parents[1]
PASTA_GERADORES_SAIDA = str(BASE_DIR / "dist-interface" / "instagram_posts")


def _garantir_pasta_saida(pasta=None):
    """Garante que a pasta de saída existe."""
    if not pasta:
        pasta = PASTA_GERADORES_SAIDA
    
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _carregar_ofertas_json(caminho_json: str) -> Dict:
    """Carrega estrutura de ofertas de um arquivo JSON.
    
    Args:
        caminho_json: Caminho para o arquivo JSON gerado por salvar_resultado_relampago_json()
    
    Returns:
        Dict com chave 'ofertas' contendo lista de ofertas
    """
    if not os.path.exists(caminho_json):
        raise FileNotFoundError(f"Arquivo JSON não encontrado: {caminho_json}")
    
    with open(caminho_json, 'r', encoding='utf-8') as f:
        dados = json.load(f)
    
    return dados


def _escolher_fonte_sistema(tamanho: int, negrito: bool = False) -> str:
    """Escolhe uma fonte disponível no sistema.
    
    Tenta encontrar fontes comuns em Windows/Linux/Mac.
    Fallback para fonte padrão se nenhuma encontrada.
    """
    fontes_candidatas = [
        # Windows
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # macOS
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    
    for caminho_fonte in fontes_candidatas:
        if os.path.exists(caminho_fonte):
            try:
                return ImageFont.truetype(caminho_fonte, tamanho)
            except Exception:
                continue
    
    # Fallback para fonte padrão
    return ImageFont.load_default()


def gerar_post_feed(
    oferta: Dict,
    tamanho: Tuple[int, int] = (1080, 1350),
    pasta_saida: Optional[str] = None,
    cor_fundo: Tuple[int, int, int] = (245, 245, 245),
    cor_desconto: Tuple[int, int, int] = (220, 20, 60),
) -> Optional[str]:
    """Gera imagem de post para Feed do Instagram (1080x1350).
    
    Args:
        oferta: Dicionário com dados da oferta (categoria, descricao, antes, depois, desconto, link_anuncio)
        tamanho: Dimensões da imagem (padrão 1080x1350)
        pasta_saida: Pasta onde salvar a imagem (padrão: dist-interface/instagram_posts)
        cor_fundo: RGB para cor de fundo (padrão: cinza claro)
        cor_desconto: RGB para cor do desconto destaque (padrão: vermelho)
    
    Returns:
        Caminho do arquivo gerado ou None se falha
    """
    if not PILLOW_AVAILABLE:
        print("❌ Pillow não instalado. Execute: pip install Pillow")
        return None
    
    pasta_saida = _garantir_pasta_saida(pasta_saida)
    
    # Criar imagem com fundo
    img = Image.new('RGB', tamanho, cor_fundo)
    draw = ImageDraw.Draw(img)
    
    # Definir fontes
    fonte_titulo = _escolher_fonte_sistema(42, negrito=True)
    fonte_preco = _escolher_fonte_sistema(56, negrito=True)
    fonte_desconto = _escolher_fonte_sistema(48, negrito=True)
    fonte_categoria = _escolher_fonte_sistema(28)
    fonte_link = _escolher_fonte_sistema(18)
    
    largura, altura = tamanho
    margem = 40
    cor_texto = (51, 51, 51)
    cor_texto_claro = (120, 120, 120)
    
    y_atual = margem
    
    # 1. Categoria (topo)
    categoria = oferta.get('categoria', '-').upper()
    draw.text((margem, y_atual), categoria, font=fonte_categoria, fill=cor_texto_claro)
    y_atual += 60
    
    # 2. Descrição (multilinha)
    descricao = oferta.get('descricao', '-')
    linhas_descricao = textwrap.wrap(descricao, width=35)
    for linha in linhas_descricao[:3]:  # Máx 3 linhas
        draw.text((margem, y_atual), linha, font=fonte_titulo, fill=cor_texto)
        y_atual += 60
    
    y_atual += 20
    
    # 3. Preço anterior (riscado)
    preco_antes = oferta.get('antes', '-')
    draw.text((margem, y_atual), preco_antes, font=fonte_preco, fill=cor_texto_claro)
    # Linha riscada sobre o preço
    texto_width = draw.textlength(preco_antes, font=fonte_preco)
    draw.line(
        [(margem, y_atual + 28), (margem + texto_width, y_atual + 28)],
        fill=cor_desconto,
        width=3
    )
    y_atual += 80
    
    # 4. Preço novo (destaque)
    preco_depois = oferta.get('depois', '-')
    draw.text(
        (margem, y_atual),
        preco_depois,
        font=fonte_preco,
        fill=(0, 150, 0)  # Verde para novo preço
    )
    y_atual += 90
    
    # 5. Desconto (destaque vermelho)
    desconto = oferta.get('desconto', '-')
    # Fundo para o desconto
    bbox_desconto = draw.textbbox((margem, y_atual), desconto, font=fonte_desconto)
    draw.rectangle(
        [(bbox_desconto[0] - 10, bbox_desconto[1] - 10),
         (bbox_desconto[2] + 10, bbox_desconto[3] + 10)],
        fill=cor_desconto
    )
    draw.text((margem, y_atual), desconto, font=fonte_desconto, fill=(255, 255, 255))
    y_atual += 80
    
    # 6. Link clicável (rodapé)
    y_link = altura - 80
    link = oferta.get('link_anuncio', '-')
    link_display = link.replace('https://', '').replace('http://', '')[:50] + '...'
    draw.text((margem, y_link), "🔗 " + link_display, font=fonte_link, fill=(0, 100, 200))
    
    # 7. Timestamp (canto inferior direito)
    timestamp = datetime.now().strftime("%d/%m %H:%M")
    texto_timestamp = f"Gerado: {timestamp}"
    bbox_timestamp = draw.textbbox((0, 0), texto_timestamp, font=fonte_link)
    texto_width = bbox_timestamp[2] - bbox_timestamp[0]
    draw.text(
        (largura - texto_width - margem, altura - 40),
        texto_timestamp,
        font=fonte_link,
        fill=cor_texto_claro
    )
    
    # Salvar imagem
    id_oferta = oferta.get('id_anuncio', 'desconhecido')
    timestamp_arquivo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"feed_{id_oferta}_{timestamp_arquivo}.png"
    caminho_saida = os.path.join(pasta_saida, nome_arquivo)
    
    img.save(caminho_saida, 'PNG')
    print(f"✅ Post Feed gerado: {caminho_saida}")
    
    return caminho_saida


def gerar_post_story(
    oferta: Dict,
    tamanho: Tuple[int, int] = (1080, 1920),
    pasta_saida: Optional[str] = None,
    cor_fundo: Tuple[int, int, int] = (15, 23, 42),
) -> Optional[str]:
    """Gera imagem de post para Stories do Instagram (1080x1920).
    
    Args:
        oferta: Dicionário com dados da oferta
        tamanho: Dimensões da imagem (padrão 1080x1920)
        pasta_saida: Pasta onde salvar a imagem
        cor_fundo: RGB para cor de fundo (padrão: azul escuro)
    
    Returns:
        Caminho do arquivo gerado ou None se falha
    """
    if not PILLOW_AVAILABLE:
        print("❌ Pillow não instalado. Execute: pip install Pillow")
        return None
    
    pasta_saida = _garantir_pasta_saida(pasta_saida)
    
    # Criar imagem com gradiente (simulado com cores)
    img = Image.new('RGB', tamanho, cor_fundo)
    draw = ImageDraw.Draw(img)
    
    # Definir fontes
    fonte_categoria = _escolher_fonte_sistema(32)
    fonte_titulo = _escolher_fonte_sistema(48, negrito=True)
    fonte_desconto = _escolher_fonte_sistema(72, negrito=True)
    fonte_preco = _escolher_fonte_sistema(52, negrito=True)
    fonte_cta = _escolher_fonte_sistema(28)
    
    largura, altura = tamanho
    margem = 50
    cor_texto = (255, 255, 255)
    cor_desconto_bg = (255, 68, 68)
    
    y_atual = margem * 2
    
    # 1. Categoria (topo pequeno)
    categoria = oferta.get('categoria', '-').upper()
    draw.text((margem, y_atual), "🏷️ " + categoria, font=fonte_categoria, fill=(200, 200, 200))
    y_atual += 80
    
    # 2. Título descritivo
    descricao = oferta.get('descricao', '-')
    linhas = textwrap.wrap(descricao, width=20)
    for linha in linhas[:2]:
        draw.text((margem, y_atual), linha, font=fonte_titulo, fill=cor_texto)
        y_atual += 70
    
    y_atual += 40
    
    # 3. Grande destaque do desconto
    desconto = oferta.get('desconto', '-')
    # Fundo redondo para desconto (simulado com retângulo)
    bbox_desc = draw.textbbox((largura // 2 - 100, y_atual), desconto, font=fonte_desconto)
    draw.rectangle(
        [(bbox_desc[0] - 20, bbox_desc[1] - 20),
         (bbox_desc[2] + 20, bbox_desc[3] + 20)],
        fill=cor_desconto_bg
    )
    draw.text(
        (largura // 2 - (bbox_desc[2] - bbox_desc[0]) // 2 - 10, y_atual),
        desconto,
        font=fonte_desconto,
        fill=cor_texto
    )
    y_atual += 140
    
    # 4. Preços
    preco_antes = oferta.get('antes', '-')
    preco_depois = oferta.get('depois', '-')
    
    texto_antes = f"De: {preco_antes}"
    draw.text((margem, y_atual), texto_antes, font=fonte_preco, fill=(180, 180, 180))
    y_atual += 70
    
    texto_depois = f"Por: {preco_depois}"
    draw.text((margem, y_atual), texto_depois, font=fonte_preco, fill=(100, 255, 100))
    y_atual += 100
    
    # 5. CTA (Call-To-Action)
    link = oferta.get('link_anuncio', '-')
    cta_text = "👉 TAP PARA VER OFERTA"
    bbox_cta = draw.textbbox((margem, y_atual), cta_text, font=fonte_cta)
    # Fundo para CTA
    draw.rectangle(
        [(bbox_cta[0] - 15, bbox_cta[1] - 15),
         (bbox_cta[2] + 15, bbox_cta[3] + 15)],
        fill=(255, 150, 0)
    )
    draw.text((margem, y_atual), cta_text, font=fonte_cta, fill=(255, 255, 255))
    
    # Salvar imagem
    id_oferta = oferta.get('id_anuncio', 'desconhecido')
    timestamp_arquivo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"story_{id_oferta}_{timestamp_arquivo}.png"
    caminho_saida = os.path.join(pasta_saida, nome_arquivo)
    
    img.save(caminho_saida, 'PNG')
    print(f"✅ Post Story gerado: {caminho_saida}")
    
    return caminho_saida


def gerar_posts_em_lote(
    caminho_json: str,
    formatos: List[str] = ["feed", "story"],
    pasta_saida: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Gera posts para todas as ofertas em um JSON.
    
    Retorna:
    - Imagens PNG (visuais para Instagram)
    - Arquivo de captions (descricoes + links para postar)
    
    Args:
        caminho_json: Caminho do JSON gerado por salvar_resultado_relampago_json()
        formatos: Lista de formatos a gerar ['feed', 'story'] ou ambos
        pasta_saida: Pasta de saída (padrão: dist-interface/instagram_posts)
    
    Returns:
        Dicionário com chaves 'feed' e 'story' contendo listas de caminhos gerados
    """
    pasta_saida = _garantir_pasta_saida(pasta_saida)
    
    # Carregar ofertas
    dados = _carregar_ofertas_json(caminho_json)
    ofertas = dados.get('ofertas', [])
    timestamp = dados.get('timestamp', 'desconhecido')
    
    if not ofertas:
        print("⚠️ Nenhuma oferta encontrada no JSON")
        return {'feed': [], 'story': []}
    
    print(f"\n📸 Gerando {len(ofertas)} posts Instagram...")
    print(f"   Formatos: {', '.join(formatos).upper()}")
    print(f"   Saída: {pasta_saida}\n")
    
    resultado = {'feed': [], 'story': []}
    captions_feed = []
    captions_story = []
    
    for idx, oferta in enumerate(ofertas, 1):
        descricao_curta = oferta.get('descricao', 'Sem descrição')[:40]
        print(f"[{idx}/{len(ofertas)}] Processando: {descricao_curta}...")
        
        # Gerar imagens
        if 'feed' in formatos:
            caminho_feed = gerar_post_feed(oferta, pasta_saida=pasta_saida)
            if caminho_feed:
                resultado['feed'].append(caminho_feed)
                # Guardar caption para este feed
                captions_feed.append(_gerar_caption_feed(oferta, idx))
        
        if 'story' in formatos:
            caminho_story = gerar_post_story(oferta, pasta_saida=pasta_saida)
            if caminho_story:
                resultado['story'].append(caminho_story)
                # Guardar caption para este story
                captions_story.append(_gerar_caption_story(oferta, idx))
    
    # Salvar arquivo com captions e links
    _salvar_captions(captions_feed, captions_story, pasta_saida, timestamp)
    
    print(f"\n✅ Processo concluído!")
    print(f"   Posts Feed gerados: {len(resultado['feed'])}")
    print(f"   Posts Story gerados: {len(resultado['story'])}")
    print(f"   Total de imagens: {len(resultado['feed']) + len(resultado['story'])}")
    print(f"\n📝 Arquivo de captions criado: {pasta_saida}/captions_{timestamp}.txt")
    print("   ↳ Copie os links de lá para postar no Instagram!")
    
    return resultado


def _gerar_caption_feed(oferta: Dict, numero: int) -> str:
    """Gera caption para post Feed com link clicável."""
    descricao = oferta.get('descricao', 'Produto em promoção')
    desconto = oferta.get('desconto', '')
    depois = oferta.get('depois', '')
    link = oferta.get('link_anuncio', '')
    
    caption = f"""
🔥 PRODUTO #{numero}

{descricao}

💰 {desconto}
💵 Apenas {depois}

🔗 Link: {link}

#promoção #desconto #oferta #mercadolivre #melhorpreco #compre #ecommerce
"""
    return caption.strip()


def _gerar_caption_story(oferta: Dict, numero: int) -> str:
    """Gera caption para post Story com link clicável."""
    descricao = oferta.get('descricao', 'Produto em promoção')
    desconto = oferta.get('desconto', '')
    depois = oferta.get('depois', '')
    link = oferta.get('link_anuncio', '')
    
    caption = f"""
📱 STORY #{numero}

{descricao}

{desconto} | {depois}

Link (copie): {link}
"""
    return caption.strip()


def _salvar_captions(captions_feed: List[str], captions_story: List[str], 
                     pasta_saida: str, timestamp: str) -> str:
    """Salva todos os captions e links em arquivo texto para copiar."""
    
    arquivo_captions = os.path.join(pasta_saida, f"captions_{timestamp}.txt")
    
    conteudo = f"""================================================================================
📸 CAPTIONS PARA INSTAGRAM
================================================================================
Timestamp: {timestamp}
Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

INSTRUÇÕES:
1. Copie cada caption abaixo
2. Selecione a imagem correspondente no seu telefone/computador
3. Cole a caption na descrição do post
4. Cole o link nos comentários (com shortlink para encurtar)
5. Use "link na bio" nas Stories

================================================================================
📷 POSTS FEED ({len(captions_feed)} imagens)
================================================================================

"""
    
    for idx, caption in enumerate(captions_feed, 1):
        conteudo += f"""--- FEED #{idx} ---
{caption}

"""
    
    conteudo += f"""
================================================================================
📱 POSTS STORY ({len(captions_story)} imagens)
================================================================================

"""
    
    for idx, caption in enumerate(captions_story, 1):
        conteudo += f"""--- STORY #{idx} ---
{caption}

"""
    
    conteudo += f"""
================================================================================
💡 DICAS:
- Para encurtar URLs, use: https://bit.ly ou https://short.link
- No Instagram, links longos aparecem como: [link no comentário]
- Em Stories, use o sticker "Link" para redirecionar ao clicar
- Melhor momento para postar: 18h-21h (horário de pico)
================================================================================
"""
    
    with open(arquivo_captions, 'w', encoding='utf-8') as f:
        f.write(conteudo)
    
    print(f"✅ Captions salvos: {arquivo_captions}")
    return arquivo_captions



# ============================================================================
# Interface CLI para usar diretamente
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUso:")
        print("  python generators/instagram_post_generator.py <arquivo.json> [feed|story|ambos]")
        print("\nExemplo:")
        print("  python generators/instagram_post_generator.py dist-interface/ofertas_relampago/Historico\\ de\\ anuncios/ofertas_20260719_143052.json ambos")
        sys.exit(1)
    
    caminho_json = sys.argv[1]
    formatos = ['feed', 'story']
    
    if len(sys.argv) > 2:
        arg_formato = sys.argv[2].lower()
        if arg_formato == 'feed':
            formatos = ['feed']
        elif arg_formato == 'story':
            formatos = ['story']
    
    if not os.path.exists(caminho_json):
        print(f"❌ Arquivo não encontrado: {caminho_json}")
        sys.exit(1)
    
    gerar_posts_em_lote(caminho_json, formatos=formatos)
