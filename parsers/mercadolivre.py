import os
import re
import random
import time
import json
from math import ceil
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import datetime
from bs4 import BeautifulSoup


def debug_pausa(rotulo):

    return


def registrar_card_ignorado(descricao, motivo, detalhe=""):

    print(
        f"\n[CARD IGNORADO] {descricao or 'Descrição não encontrada'}"
    )

    print(
        f"Motivo: {motivo}"
    )

    if detalhe:

        print(
            f"Detalhe: {detalhe}"
        )


def normalizar_descricao(texto_descricao):

    return " ".join((texto_descricao or "").split()).strip()


def _montar_url_anuncio(metadata):

    url = (metadata or {}).get("url", "").strip()
    if not url:
        return None

    url_params = (metadata or {}).get("url_params", "").strip()
    url_fragments = (metadata or {}).get("url_fragments", "").strip()

    if url.startswith("http://") or url.startswith("https://"):
        base = url
    else:
        base = f"https://{url.lstrip('/')}"

    return f"{base}{url_params}{url_fragments}"


def _extrair_ctx_rendering(html):

    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NORDIC_RENDERING_CTX__")

    if not script:
        return None

    texto = script.get_text("", strip=True)
    prefixo = "_n.ctx.r="

    if prefixo not in texto:
        return None

    trecho_json = texto.split(prefixo, 1)[1].strip()

    if ";_n.ctx.r.assets" in trecho_json:
        trecho_json = trecho_json.split(";_n.ctx.r.assets", 1)[0].strip()

    if trecho_json.endswith(";"):
        trecho_json = trecho_json[:-1]

    try:
        return json.loads(trecho_json)
    except json.JSONDecodeError:
        return None


def _extrair_paging_do_html(html):

    ctx = _extrair_ctx_rendering(html)
    if not ctx:
        return None

    return (
        ctx.get("appProps", {})
        .get("pageProps", {})
        .get("data", {})
        .get("paging", {})
    )


def _montar_url_paginada(url_base, pagina):

    partes = urlsplit(url_base)
    parametros = dict(parse_qsl(partes.query, keep_blank_values=True))
    parametros["page"] = str(pagina)

    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            partes.path,
            urlencode(parametros),
            "",
        )
    )


def _extrair_desconto_valor(texto_desconto, preco_anterior=None, preco_atual=None):

    if texto_desconto:

        encontrado = re.search(r"(\d+)", texto_desconto)
        if encontrado:
            return int(encontrado.group(1))

    if preco_anterior is None or preco_atual is None:
        return None

    if preco_anterior <= 0 or preco_atual < 0 or preco_atual > preco_anterior:
        return None

    return int(round(((preco_anterior - preco_atual) / preco_anterior) * 100))


def _formatar_preco(valor):

    if valor is None:
        return "Preço não encontrado"

    valor_formatado = f"{float(valor):.2f}".replace(".", ",")
    if valor_formatado.endswith(",00"):
        valor_formatado = valor_formatado[:-3]

    return f"R$ {valor_formatado}"


def _normalizar_filtro_categoria(texto_categoria):

    return normalizar_descricao(texto_categoria).casefold()


def _extrair_id_anuncio_de_texto(texto):

    texto_limpo = (texto or "").strip()

    if not texto_limpo:

        return ""

    encontrado = re.search(r"(MLB[A-Z]?[0-9]+|MLBU[0-9]+)", texto_limpo, re.IGNORECASE)

    if encontrado:

        return encontrado.group(1).upper()

    return texto_limpo


def _extrair_ofertas_do_ctx(html, desconto_minimo=30):

    ctx = _extrair_ctx_rendering(html)
    if not ctx:
        return []

    items = (
        ctx.get("appProps", {})
        .get("pageProps", {})
        .get("data", {})
        .get("items", [])
    )

    ofertas = []

    for item in items:

        card = item.get("card", {})
        metadata = card.get("metadata", {})
        componentes = card.get("components", [])

        if not metadata:
            continue

        titulo = metadata.get("title") or metadata.get("sanitized_title") or "Sem descrição"
        for componente in componentes:
            if componente.get("type") == "title":
                titulo = componente.get("title", {}).get("text", titulo)
                break

        preco_anterior = None
        preco_atual = None
        texto_desconto = None
        categoria = "Sem categoria"

        for componente in componentes:
            tipo = componente.get("type")
            if tipo == "price":
                bloco_preco = componente.get("price", {})
                preco_antigo = bloco_preco.get("previous_price", {})
                preco_novo = bloco_preco.get("current_price", {})
                preco_anterior = preco_antigo.get("value", preco_anterior)
                preco_atual = preco_novo.get("value", preco_atual)
                desconto_label = bloco_preco.get("discount_label", {})
                texto_desconto = desconto_label.get("text", texto_desconto)
            elif tipo == "brand" and categoria == "Sem categoria":
                categoria = componente.get("brand", {}).get("text", categoria)
            elif tipo == "variations_text" and categoria == "Sem categoria":
                categoria = componente.get("variations_text", {}).get("text", categoria)

        desconto_valor = _extrair_desconto_valor(texto_desconto, preco_anterior, preco_atual)

        if desconto_valor is None or desconto_valor < desconto_minimo:
            continue

        link_anuncio = _montar_url_anuncio(metadata)
        id_anuncio = _extrair_id_anuncio_de_texto(
            metadata.get("id") or metadata.get("user_product_id") or metadata.get("product_id") or link_anuncio
        )

        ofertas.append(
            {
                "id_anuncio": id_anuncio,
                "categoria": categoria,
                "descricao": titulo,
                "antes": _formatar_preco(preco_anterior),
                "antes_valor": preco_anterior,
                "desconto": f"{desconto_valor}% OFF",
                "depois": _formatar_preco(preco_atual),
                "depois_valor": preco_atual,
                "link_anuncio": link_anuncio,
            }
        )

    print(f"{len(ofertas)} oferta(s) com {desconto_minimo}% ou mais de desconto extraída(s) do JSON.")

    return ofertas


def extrair_dados_do_card(card):

    try:

        descricao = card.locator(
            "a.poly-component__title"
        ).first.inner_text(timeout=1500).strip()

    except Exception:

        try:

            descricao = card.locator(
                "h2, h3, h1"
            ).first.inner_text(timeout=1500).strip()

        except Exception:

            descricao = "Descrição não encontrada"

    try:

        preco_atual = card.locator(
            ".poly-component__price .poly-price__current span.andes-money-amount[data-andes-money-amount='true']"
        ).first

        reais = preco_atual.locator(
            "[data-andes-money-amount-fraction='true']"
        ).first.inner_text(timeout=1500).strip()

        centavos = ""

        try:

            centavos = preco_atual.locator(
                "[data-andes-money-amount-cents='true']"
            ).first.inner_text(timeout=1500).strip()

        except Exception:

            centavos = ""

        depois = f"R$ {reais},{centavos}" if centavos else f"R$ {reais}"

    except Exception:

        try:

            aria_preco = card.locator(
                ".poly-price__current [aria-label*='Agora:']"
            ).first.get_attribute("aria-label", timeout=1500) or ""

            encontrado = re.search(r"Agora:\s*(\d+)\s*reais?\s*com\s*(\d+)\s*centavos?", aria_preco, re.IGNORECASE)

            if encontrado:

                depois = f"R$ {encontrado.group(1)},{encontrado.group(2)}"

            else:

                depois = "Preço atual não encontrado"

        except Exception:

            depois = "Preço atual não encontrado"

    try:

        preco_antigo = card.locator(
            "s.andes-money-amount--previous"
        ).first

        reais_antigo = preco_antigo.locator(
            "[data-andes-money-amount-fraction='true']"
        ).first.inner_text(timeout=1500).strip()

        centavos_antigo = ""

        try:

            centavos_antigo = preco_antigo.locator(
                "[data-andes-money-amount-cents='true']"
            ).first.inner_text(timeout=1500).strip()

        except Exception:

            centavos_antigo = ""

        antes = f"R$ {reais_antigo},{centavos_antigo}" if centavos_antigo else f"R$ {reais_antigo}"

    except Exception:

        antes = "Sem preço anterior"

    try:

        desconto = card.locator(
            ".poly-component__price .poly-price__current [data-andes-money-amount-discount='true']"
        ).first.inner_text(timeout=1500).strip()

    except Exception:

        desconto = "Sem desconto"

    try:

        destaque = card.locator(
            "span.poly-component__highlight"
        ).first.inner_text(timeout=1500).strip()

        destaque_normalizado = destaque.upper()

        oferta_imperdivel = (
            "OFERTA IMPERDÍVEL" in destaque_normalizado
            or "OFERTA IMPERDIVEL" in destaque_normalizado
        )

    except Exception:

        oferta_imperdivel = False

    try:

        link_original = card.locator(
            "a.poly-component__title[href], a[href*='mercadolivre.com.br'][href*='polycard_client=affiliates']"
        ).first.get_attribute("href", timeout=1500)

        link_original = (link_original or "").strip()

    except Exception:

        link_original = ""

    id_anuncio = ""

    try:

        id_anuncio = _extrair_id_anuncio_de_texto(link_original)

    except Exception:

        id_anuncio = ""

    # Teste sem imagem: nao capturamos o src do card neste momento.
    # try:
    #
    #     imagem = card.locator(
    #         "img.poly-component__picture, img[data-testid='picture']"
    #     ).first.get_attribute("src", timeout=1500)
    #
    #     imagem = (imagem or "").strip()
    #
    # except Exception:
    #
    #     imagem = ""

    # imagem = ""

    return {
        "descricao": descricao,
        "antes": antes,
        "depois": depois,
        "desconto": desconto,
        "oferta_imperdivel": oferta_imperdivel,
        "id_anuncio": id_anuncio,
        "link": link_original,
        # "imagem": imagem,
    }


def obter_link_encurtado_do_card(page, card, url_original):

    try:

        botao_compartilhar = card.locator(
            "button:has-text('Compartilhar'), button[aria-label*='Compartilhar'], button:has(.andes-button__text[data-andes-button-text='true'])"
        ).first

        botao_compartilhar.wait_for(state="visible", timeout=8000)

        botao_compartilhar.click()

        page.locator(
            "div.andes-modal__scroll"
        ).first.wait_for(state="visible", timeout=8000)

        botao_copiar = page.locator(
            "button[data-testid='copy-button__label_link'], button#copy_link, button.share-button"
        ).first

        botao_copiar.wait_for(state="visible", timeout=5000)

        botao_copiar.click()

        time.sleep(random.uniform(1, 2))

        link_encurtado = page.evaluate(
            "navigator.clipboard.readText()"
        ).strip()

        if link_encurtado and "meli.la" in link_encurtado:

            page.keyboard.press("Escape")

            return link_encurtado

        page.keyboard.press("Escape")

    except Exception as exc:

        print(f"\nNao foi possivel obter link encurtado do card: {exc}")

        try:

            page.keyboard.press("Escape")

        except Exception:

            pass

    return url_original


def obter_link_encurtado_por_descricao(page, descricao, url_original):

    if not descricao:

        return url_original

    try:

        titulo = page.locator(
            "div.polycards__container li.poly-card a.poly-component__title",
            has_text=descricao
        ).first

        titulo.wait_for(state="visible", timeout=3000)

        card = titulo.locator(
            "xpath=ancestor::li[1]"
        ).first

        card.scroll_into_view_if_needed(timeout=5000)

        return obter_link_encurtado_do_card(
            page,
            card,
            url_original
        )

    except Exception:

        return url_original


def coletar_produtos_com_desconto(page, url, desconto_minimo, limite):

    print(
        f"\nBuscando produtos em:\n{url}"
    )

    debug_pausa("Antes de procurar os produtos no hub")

    time.sleep(
        random.uniform(3, 5)
    )

    produtos = []
    vistos = set()

    while len(produtos) < limite:

        cards = page.locator("div.polycards__container li.poly-card").count()
        novos_na_rodada = 0

        for indice in range(cards):

            card = page.locator("div.polycards__container li.poly-card").nth(indice)

            try:

                dados = extrair_dados_do_card(card)

            except Exception:

                registrar_card_ignorado(
                    "Descrição não encontrada",
                    f"Falha ao extrair dados do card na posição {indice}"
                )

                continue

            desconto_texto = dados.get("desconto", "")
            encontrado = re.search(r"(\d+)", desconto_texto)

            if not encontrado:

                registrar_card_ignorado(
                    dados.get("descricao"),
                    "Desconto não encontrado no card",
                    f"Texto lido: {desconto_texto or 'vazio'}"
                )

                continue

            desconto = int(encontrado.group(1))

            if desconto < desconto_minimo:

                registrar_card_ignorado(
                    dados.get("descricao"),
                    "Desconto abaixo do mínimo",
                    f"Desconto lido: {desconto}% | mínimo exigido: {desconto_minimo}%"
                )

                continue

            chave = f"{dados.get('descricao', '').strip().lower()}|{dados.get('depois', '').strip()}"

            if chave in vistos:

                registrar_card_ignorado(
                    dados.get("descricao"),
                    "Card já visto nesta execução",
                    f"Chave repetida: {chave}"
                )

                continue

            vistos.add(chave)
            novos_na_rodada += 1

            produtos.append(dados)

            if len(produtos) >= limite:

                break

        if len(produtos) >= limite:

            break

        if novos_na_rodada == 0:

            break

        page.mouse.wheel(0, 2500)

        time.sleep(
            random.uniform(1, 2)
        )

    print(
        f"{len(produtos)} produtos com desconto de {desconto_minimo}% ou mais encontrados."
    )

    return produtos


def obter_link_encurtado(page, url_original):

    try:

        # Clica no botão Compartilhar
        debug_pausa("Antes de clicar em Compartilhar")

        botao = page.locator(
            "button:has-text('Compartilhar'), button[aria-label*='ompartilhar']"
        ).first

        botao.wait_for(state="visible", timeout=8000)

        botao.click()

        debug_pausa("Depois de abrir o modal de compartilhar")

        time.sleep(random.uniform(1, 2))

        # Aguarda o modal abrir
        page.wait_for_selector(
            "[data-andes-thumbnail='true']",
            timeout=8000
        )

        # Clica no ícone de link (corrente) dentro do modal
        icone_link = page.locator(
            "[data-andes-thumbnail='true']"
        ).first

        debug_pausa("Antes de clicar no icone de link no modal")

        icone_link.click()

        debug_pausa("Depois de clicar no icone de link no modal")

        time.sleep(random.uniform(1, 2))

        # Aciona o botao de copiar o link do produto para gerar/copiar a URL curta.
        botao_copiar = page.locator(
            "button[data-testid='copy-button__label_link'], button#copy_link, button.share-button"
        ).first

        botao_copiar.wait_for(state="visible", timeout=5000)

        botao_copiar.click()

        time.sleep(random.uniform(1, 2))

        # Tenta ler a URL encurtada do botão/campo identificado no modal.
        botao_link = page.locator(
            "button[data-testid='copy-button__label_link']"
        ).first

        try:

            botao_link.wait_for(state="visible", timeout=5000)

            texto_botao = botao_link.inner_text().strip()

            print(f"\n[DEBUG] Texto do botao de link: {texto_botao}")

            debug_pausa("Depois de ler o botao de link do produto")

        except Exception as e:

            print(f"\n[DEBUG] Erro ao ler botao de link: {e}")

        # Mantem compatibilidade com a variacao antiga baseada em textarea.
        campo = page.locator(
            "textarea[data-testid='text-field__label_link']"
        ).first

        try:

            campo.wait_for(state="visible", timeout=5000)

            link_encurtado = campo.input_value().strip()

            print(f"\n[DEBUG] Link do textarea: {link_encurtado}")

            debug_pausa("Depois de ler o textarea do link encurtado")

            if link_encurtado and "meli.la" in link_encurtado:

                print(f"\n✓ Link encurtado validado: {link_encurtado}")

                # Fecha o modal se possível
                page.keyboard.press("Escape")

                return link_encurtado

        except Exception as e:

            print(f"\n[DEBUG] Erro ao ler textarea: {e}")

            pass

        # Fallback: tenta ler do clipboard via JS
        try:

            link_encurtado = page.evaluate(
                "navigator.clipboard.readText()"
            ).strip()

            print(f"\n[DEBUG] Link do clipboard: {link_encurtado}")

            debug_pausa("Depois de tentar ler o clipboard")

            if link_encurtado and "meli.la" in link_encurtado:

                print(f"\n✓ Link encurtado do clipboard validado: {link_encurtado}")

                page.keyboard.press("Escape")

                return link_encurtado

        except Exception as e:

            print(f"\n[DEBUG] Erro ao ler clipboard: {e}")

            pass

        print(f"\n⚠ Nenhum link encurtado encontrado. Usando URL original.")

        page.keyboard.press("Escape")

    except Exception as exc:

        print(f"\nNão foi possível obter link encurtado: {exc}")

    return url_original


def mercado_livre(page, url):

    try:

        print(f"\nAbrindo:\n{url}")

        page.goto(

            url,

            timeout=90000,

            wait_until="domcontentloaded"
        )

        # delay humano
        time.sleep(random.uniform(5, 8))

        # scroll humano
        page.mouse.wheel(0, 1200)

        time.sleep(random.uniform(2, 4))

        html = page.content().lower()

        # =========================
        # CAPTCHA
        # =========================

        if "captcha" in html:

            return {

                "link": url,

                "descricao": "CAPTCHA DETECTADO",

                "antes": "-",

                "depois": "-",

                "desconto": "-"
            }

        # =========================
        # DESCRIÇÃO
        # =========================

        try:

            descricao = page.locator(

                ".poly-component__title"

            ).first.inner_text()

        except:

            try:

                descricao = page.locator(

                    "h1"

                ).first.inner_text()

            except:

                descricao = "Descrição não encontrada"

        # =========================
        # PREÇO ATUAL
        # =========================

        try:

            preco_atual = page.locator(

                "span.andes-money-amount:not(.andes-money-amount--previous)"

            ).first

            reais = preco_atual.locator(

                "[data-andes-money-amount-fraction='true']"

            ).inner_text()

            centavos = preco_atual.locator(

                "[data-andes-money-amount-cents='true']"

            ).inner_text()

            depois = f"R$ {reais},{centavos}"

        except:

            try:

                reais = page.locator(

                    "span.andes-money-amount__fraction[data-andes-money-amount-fraction='true']"

                ).first.inner_text()

                centavos = page.locator(

                    "span.andes-money-amount__cents[data-andes-money-amount-cents='true']"

                ).first.inner_text()

                depois = f"R$ {reais},{centavos}"

            except:

                depois = "Preço atual não encontrado"

        # =========================
        # PREÇO ANTIGO
        # =========================

        try:

            preco_antigo = page.locator(

                "s.andes-money-amount--previous"

            ).first

            reais_antigo = preco_antigo.locator(

                "[data-andes-money-amount-fraction='true']"

            ).inner_text()

            centavos_antigo = preco_antigo.locator(

                "[data-andes-money-amount-cents='true']"

            ).inner_text()

            antes = f"R$ {reais_antigo},{centavos_antigo}"

        except:

            try:

                reais_antigo = page.locator(

                    "span.andes-money-amount__fraction[data-andes-money-amount-fraction='true']"

                ).first.inner_text()

                centavos_antigo = page.locator(

                    "span.andes-money-amount__cents[data-andes-money-amount-cents='true']"

                ).first.inner_text()

                antes = f"R$ {reais_antigo},{centavos_antigo}"

            except:

                antes = "Sem preço anterior"

        # =========================
        # DESCONTO
        # =========================

        try:

            desconto = page.locator(

                "[data-andes-money-amount-discount='true']"

            ).first.inner_text()

        except:

            desconto = "Sem desconto"

        # =========================
        # LINK ENCURTADO
        # =========================

        link_final = obter_link_encurtado(page, url)

        debug_pausa("Depois de validar e definir o link final")

        resultado = {

            "link": link_final,

            "descricao": descricao,

            "antes": antes,

            "depois": depois,

            "desconto": desconto
        }

        print("\nRESULTADO:")

        print(resultado)

        return resultado

    except Exception as e:

        erro = {

            "link": url,

            "descricao": f"ERRO: {str(e)}",

            "antes": "-",

            "depois": "-",

            "desconto": "-"
        }

        print("\nERRO:")

        print(erro)

        return erro


# =============================================================================
# OFERTAS RELÂMPAGO — nova abordagem via HTML salvo
# =============================================================================

PASTA_OFERTAS_RELAMPAGO = "ofertas_relampago"


def salvar_html_ofertas_relampago(page, url):
    """Navega até a URL de ofertas relâmpago, aguarda carregamento,
    faz scroll para expor mais cards e salva o HTML completo em arquivo texto.
    Retorna o caminho do arquivo salvo."""

    os.makedirs(PASTA_OFERTAS_RELAMPAGO, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(PASTA_OFERTAS_RELAMPAGO, f"html_relampago_{timestamp}.txt")

    print(f"\nNavegando para ofertas relâmpago:\n{url}")

    page.goto(url, timeout=90000, wait_until="domcontentloaded")

    time.sleep(random.uniform(5, 8))

    for _ in range(6):
        page.mouse.wheel(0, 2000)
        time.sleep(random.uniform(1.5, 2.5))

    html = page.content()

    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML salvo em: {caminho}")

    return caminho


def extrair_ofertas_do_html(caminho_arquivo, desconto_minimo=30):
    """Lê o HTML salvo em caminho_arquivo, localiza os poly-cards e retorna
    a lista de ofertas com desconto >= desconto_minimo.

    Cada oferta é um dicionário com as chaves:
        categoria, descricao, antes, desconto, depois
    """

    print(f"\nAnalisando HTML de: {caminho_arquivo}")

    with open(caminho_arquivo, "r", encoding="utf-8") as f:
        html = f.read()

    ofertas_ctx = _extrair_ofertas_do_ctx(html, desconto_minimo)
    if ofertas_ctx:
        return ofertas_ctx

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.poly-card")

    print(f"{len(cards)} card(s) encontrado(s) no HTML.")

    ofertas = []

    for card in cards:

        # --- Desconto ---
        desconto_el = card.select_one("[data-andes-money-amount-discount='true']")
        if not desconto_el:
            continue

        texto_desconto = desconto_el.get_text(strip=True)
        encontrado = re.search(r"(\d+)", texto_desconto)
        if not encontrado:
            continue

        desconto_val = int(encontrado.group(1))
        if desconto_val < desconto_minimo:
            continue

        # --- Descrição ---
        titulo_el = card.select_one("a.poly-component__title")
        descricao = titulo_el.get_text(strip=True) if titulo_el else "Sem descrição"

        # --- Preço atual ---
        preco_atual_el = card.select_one(".poly-price__current")
        if preco_atual_el:
            frac = preco_atual_el.select_one("[data-andes-money-amount-fraction='true']")
            cents = preco_atual_el.select_one("[data-andes-money-amount-cents='true']")
            reais = frac.get_text(strip=True) if frac else ""
            centavos = cents.get_text(strip=True) if cents else ""
            depois = f"R$ {reais},{centavos}" if centavos else f"R$ {reais}"
        else:
            depois = "Preço não encontrado"

        # --- Preço anterior ---
        antes_el = card.select_one("s.andes-money-amount--previous")
        if antes_el:
            frac_a = antes_el.select_one("[data-andes-money-amount-fraction='true']")
            cents_a = antes_el.select_one("[data-andes-money-amount-cents='true']")
            reais_a = frac_a.get_text(strip=True) if frac_a else ""
            centavos_a = cents_a.get_text(strip=True) if cents_a else ""
            antes = f"R$ {reais_a},{centavos_a}" if centavos_a else f"R$ {reais_a}"
        else:
            antes = "Sem preço anterior"

        # --- Categoria ---
        categoria_el = card.select_one(
            "span.poly-component__brand, "
            "span.poly-component__category, "
            "span.poly-component__highlight"
        )
        categoria = categoria_el.get_text(strip=True) if categoria_el else "Sem categoria"

        ofertas.append({
            "categoria": categoria,
            "descricao": descricao,
            "antes": antes,
            "desconto": texto_desconto,
            "depois": depois,
        })

    print(f"{len(ofertas)} oferta(s) com {desconto_minimo}% ou mais de desconto extraída(s).")

    return ofertas


def _localizar_card_na_pagina(page, descricao):
    """Percorre os cards da página atual e retorna o href do card
    cujo título corresponde a descricao. Retorna None se não encontrar."""

    cards = page.locator("li.poly-card")
    count = cards.count()

    descricao_norm = " ".join(descricao.split()).lower()

    for i in range(count):
        card = cards.nth(i)
        try:
            titulo = card.locator("a.poly-component__title").first.inner_text(timeout=1000).strip()
        except Exception:
            continue

        titulo_norm = " ".join(titulo.split()).lower()

        if descricao_norm[:60] in titulo_norm or titulo_norm[:60] in descricao_norm:
            try:
                href = card.locator("a.poly-component__title").first.get_attribute("href", timeout=1000)
                if href:
                    return href
            except Exception:
                continue

    return None


def _obter_link_via_botao_afiliados(page, url_original):
    """Com a página do anúncio aberta, clica no botão 'Compartilhar' do nav
    Afiliados e tenta extrair o link encurtado gerado.
    Retorna o link encurtado ou url_original em caso de falha."""

    try:
        botao = page.locator(
            "nav[aria-label='Afiliados'] button[data-testid='generate_link_button']"
        ).first

        botao.wait_for(state="visible", timeout=10000)
        botao.click()

        time.sleep(random.uniform(1.5, 2.5))

        # Tenta ler de textarea
        try:
            campo = page.locator(
                "textarea[data-testid='text-field__label_link']"
            ).first
            campo.wait_for(state="visible", timeout=5000)
            link = campo.input_value().strip()
            if link and "meli.la" in link:
                print(f"✓ Link de afiliado: {link}")
                page.keyboard.press("Escape")
                return link
        except Exception:
            pass

        # Tenta clicar no botão de copiar e ler do clipboard
        try:
            botao_copiar = page.locator(
                "button[data-testid='copy-button__label_link']"
            ).first
            botao_copiar.wait_for(state="visible", timeout=5000)
            botao_copiar.click()
            time.sleep(random.uniform(1, 2))

            link = page.evaluate("navigator.clipboard.readText()").strip()
            if link and "meli.la" in link:
                print(f"✓ Link de afiliado via clipboard: {link}")
                page.keyboard.press("Escape")
                return link
        except Exception:
            pass

        # Tenta ler de qualquer input/textarea que contenha meli.la
        try:
            link = page.locator("input[value*='meli.la'], textarea").evaluate_all(
                "els => { for (const el of els) { const v = el.value || ''; if (v.includes('meli.la')) return v; } return ''; }"
            )
            if link and "meli.la" in link:
                print(f"✓ Link de afiliado via busca genérica: {link}")
                page.keyboard.press("Escape")
                return link
        except Exception:
            pass

        print("[AVISO] Não foi possível extrair o link encurtado do modal de afiliado.")
        page.keyboard.press("Escape")

    except Exception as exc:
        print(f"[ERRO] Falha ao clicar no botão Afiliados/Compartilhar: {exc}")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    return url_original


def _extrair_categoria_do_breadcrumb(page):
    """Extrai a categoria do breadcrumb da página do anúncio já aberta.
    Retorna a última categoria significativa encontrada, ou 'Sem categoria'."""

    seletores = [
        "ol.andes-breadcrumb li a",
        "nav[aria-label='breadcrumb'] li a",
        "nav[aria-label='Breadcrumb'] li a",
        ".ui-pdp-breadcrumb__item a",
        ".andes-breadcrumb__item a",
    ]

    for seletor in seletores:
        try:
            itens = page.locator(seletor).all_inner_texts()
            # Filtra itens vazios e remove o último (normalmente é o próprio produto)
            itens_limpos = [i.strip() for i in itens if i.strip()]
            if len(itens_limpos) >= 2:
                # Retorna os dois últimos níveis de categoria (ex: "Eletrônicos > Celulares")
                return " > ".join(itens_limpos[-2:])
            if itens_limpos:
                return itens_limpos[-1]
        except Exception:
            continue

    return "Sem categoria"


def obter_link_afiliado_relampago(page, oferta, url_relampago):
    """Reabre a página de ofertas relâmpago, localiza o card correspondente
    à oferta, abre o anúncio, extrai a categoria do breadcrumb e obtém o
    link de afiliado via botão Compartilhar do nav Afiliados.
    Retorna tupla (link, categoria)."""

    descricao = oferta.get("descricao", "")
    link_anuncio = oferta.get("link_anuncio")

    print(f"\n--- Buscando link de afiliado para: {descricao[:70]}...")

    if not link_anuncio:

        page.goto(url_relampago, timeout=90000, wait_until="domcontentloaded")
        time.sleep(random.uniform(4, 6))

        for _ in range(10):
            link_anuncio = _localizar_card_na_pagina(page, descricao)
            if link_anuncio:
                break
            page.mouse.wheel(0, 2500)
            time.sleep(random.uniform(1, 2))

    if not link_anuncio:
        print("[AVISO] Card não localizado na página de ofertas relâmpago.")
        return None, "Sem categoria"

    print(f"Abrindo anúncio: {link_anuncio[:80]}...")

    page.goto(link_anuncio, timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(3, 5))

    categoria = _extrair_categoria_do_breadcrumb(page)
    print(f"Categoria extraída do breadcrumb: {categoria}")

    link = _obter_link_via_botao_afiliados(page, link_anuncio)

    return link, categoria


def processar_ofertas_relampago(
    page,
    url_relampago,
    desconto_minimo=30,
    categoria=None,
    preco_minimo=None,
    preco_maximo=None,
    limite_candidatos=None,
):
    """Fluxo completo de ofertas relâmpago:

    1. Navega até a URL e salva o HTML completo em ofertas_relampago/.
    2. Analisa o HTML e extrai ofertas com desconto >= desconto_minimo.
    3. Para cada oferta, reabre a página, localiza o card, abre o anúncio
       e obtém o link de afiliado encurtado.
    4. Retorna a lista de ofertas enriquecida com o campo 'link'.
    """

    ofertas_consolidadas = []
    descricoes_vistas = set()
    categoria_filtro = _normalizar_filtro_categoria(categoria)

    pagina_inicial_html = salvar_html_ofertas_relampago(page, url_relampago)
    paging = _extrair_paging_do_html(pagina_inicial_html) or {}

    limite = paging.get("limit", 48) or 48
    total = paging.get("total", 0) or 0

    if total and limite:
        total_paginas = max(1, ceil(total / limite))
    else:
        total_paginas = 1

    print(f"Paginação detectada: {total_paginas} página(s) com limite de {limite} item(ns) por página.")

    for pagina in range(total_paginas):
        url_pagina = _montar_url_paginada(url_relampago, pagina)
        caminho_html = pagina_inicial_html if pagina == 0 else salvar_html_ofertas_relampago(page, url_pagina)

        ofertas_pagina = extrair_ofertas_do_html(caminho_html, desconto_minimo)

        if not ofertas_pagina:
            print(f"Sem ofertas elegíveis na página {pagina + 1}.")
            continue

        for oferta in ofertas_pagina:
            chave = normalizar_descricao(oferta.get("descricao"))
            if not chave or chave in descricoes_vistas:
                continue

            if categoria_filtro and _normalizar_filtro_categoria(oferta.get("categoria")) != categoria_filtro:
                continue

            preco_atual = oferta.get("depois_valor")
            if preco_atual is None:
                continue

            if preco_minimo is not None and preco_atual < preco_minimo:
                continue

            if preco_maximo is not None and preco_atual > preco_maximo:
                continue

            descricoes_vistas.add(chave)

            link, categoria = obter_link_afiliado_relampago(page, oferta, url_pagina)
            oferta["link"] = link or "Link não obtido"
            oferta["categoria"] = categoria
            ofertas_consolidadas.append(oferta)

            if limite_candidatos is not None and len(ofertas_consolidadas) >= limite_candidatos:
                print(
                    f"Limite de candidatos atingido no relâmpago: {limite_candidatos}."
                )
                return ofertas_consolidadas

            time.sleep(random.uniform(3, 6))

    if not ofertas_consolidadas:
        print("\nNenhuma oferta elegível encontrada.")
        return []

    return ofertas_consolidadas


def salvar_resultado_relampago(ofertas, pasta=PASTA_OFERTAS_RELAMPAGO):
    """Salva em texto formatado as ofertas relâmpago com seus links de afiliado."""

    if not ofertas:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, f"resultado_{timestamp}.txt")

    with open(caminho, "w", encoding="utf-8") as f:
        for oferta in ofertas:
            f.write(f"Categoria: {oferta.get('categoria', '-')}\n")
            f.write(f"Descrição: {oferta.get('descricao', '-')}\n")
            f.write(f"Antes: {oferta.get('antes', '-')}\n")
            f.write(f"Desconto: {oferta.get('desconto', '-')}\n")
            f.write(f"Depois: {oferta.get('depois', '-')}\n")
            f.write(f"Link: {oferta.get('link', '-')}\n")
            f.write("\n-----------------------------\n\n")

    print(f"\nResultado salvo em: {caminho}")

    return caminho