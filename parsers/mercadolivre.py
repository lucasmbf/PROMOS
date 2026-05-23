import os
import re
import random
import time
import json
import sys
from pathlib import Path
from math import ceil
from urllib.parse import quote
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


def _montar_url_com_filtro(url_base, nome_filtro, valor_filtro):

    partes = urlsplit(url_base)
    parametros = dict(parse_qsl(partes.query, keep_blank_values=True))
    parametros[nome_filtro] = str(valor_filtro)

    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            partes.path,
            urlencode(parametros),
            "",
        )
    )


def _extrair_available_filters_do_html(html):

    ctx = _extrair_ctx_rendering(html)
    if not ctx:
        return []

    return (
        ctx.get("appProps", {})
        .get("pageProps", {})
        .get("data", {})
        .get("availableFilters", [])
    )


def _resolver_filtro_categoria_relampago(html, categoria):

    categoria_filtro = _normalizar_filtro_categoria(categoria)
    if not categoria_filtro:
        return None

    available_filters = _extrair_available_filters_do_html(html)

    for filtro in available_filters:
        if filtro.get("id") != "category":
            continue

        for valor in filtro.get("values", []):
            nome = valor.get("name", "")
            nome_normalizado = _normalizar_filtro_categoria(nome)

            if nome_normalizado == categoria_filtro:
                return valor

    return None


def _resolver_url_base_relampago(page, url_relampago, categoria):

    categoria_filtro = _normalizar_filtro_categoria(categoria)
    if not categoria_filtro:
        return url_relampago

    print(f"\nAbrindo ofertas relâmpago para localizar a categoria lateral: {categoria}")

    page.goto(url_relampago, timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(5, 8))

    try:
        page.locator("ol.list-filter__values-list span.list-filter__list-element").filter(has_text=normalizar_descricao(categoria)).first.click(timeout=8000)
        time.sleep(random.uniform(3, 5))
        print(f"Categoria lateral clicada diretamente na página: {categoria}")
        return page.url
    except Exception:
        pass

    filtro_categoria = _resolver_filtro_categoria_relampago(page.content(), categoria)

    if not filtro_categoria or not filtro_categoria.get("id"):
        print(
            f"[AVISO] Categoria '{categoria}' não encontrada nos filtros laterais. Seguindo sem filtro prévio de categoria."
        )
        return url_relampago

    url_filtrada = _montar_url_com_filtro(
        url_relampago,
        "category",
        filtro_categoria.get("id"),
    )

    print(
        f"Categoria lateral localizada: {filtro_categoria.get('name')} ({filtro_categoria.get('id')}). Navegando antes de iniciar a paginação."
    )

    return url_filtrada


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


def _normalizar_chave_historico(valor):

    return " ".join((valor or "").split()).strip().lower()


def _normalizar_url_resultado(href):

    href = (href or "").strip()

    if not href:
        return ""

    if href.startswith("http://") or href.startswith("https://"):
        return href

    if href.startswith("//"):
        return f"https:{href}"

    return f"https://www.mercadolivre.com.br{href}"


def _montar_url_pesquisa_generica(descricao, pagina=1):

    slug = re.sub(r"\s+", "-", (descricao or "").strip())
    slug = quote(slug, safe="-")
    base = f"https://lista.mercadolivre.com.br/{slug}"

    if pagina <= 1:
        return base

    inicio = ((pagina - 1) * 50) + 1

    return f"{base}_Desde_{inicio}"


def _converter_preco_em_float(texto_preco):

    texto_limpo = (texto_preco or "").strip()

    if not texto_limpo.startswith("R$"):
        return None

    numero = texto_limpo.replace("R$", "").strip().replace(".", "").replace(",", ".")

    try:
        return float(numero)
    except ValueError:
        return None


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
        categoria = "Sem categoria"
        preco_anterior = None
        preco_atual = None
        texto_desconto = None

        for componente in componentes:

            tipo = componente.get("type")

            if tipo == "title":
                titulo = componente.get("title", {}).get("text", titulo)
                continue

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

def _obter_diretorio_saida():

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path.cwd()


BASE_SAIDA = _obter_diretorio_saida()
PASTA_OFERTAS_RELAMPAGO = str(BASE_SAIDA / "ofertas_relampago")
PASTA_OFERTAS_HUB = str(BASE_SAIDA / "ofertas_afiliados")
PASTA_RELAMPAGO_HTML = str(Path(PASTA_OFERTAS_RELAMPAGO) / "html")
PASTA_RELAMPAGO_HISTORICO = str(Path(PASTA_OFERTAS_RELAMPAGO) / "Historico de anuncios")
PASTA_AFILIADOS_HTML = str(Path(PASTA_OFERTAS_HUB) / "html")
PASTA_AFILIADOS_HISTORICO = str(Path(PASTA_OFERTAS_HUB) / "Historico de anuncios")
PASTA_METADADOS_COLETA = str(BASE_SAIDA / "metadados_coleta")
ARQUIVO_CONTROLE_EXECUCOES = str(Path(PASTA_METADADOS_COLETA) / "controle_execucoes.json")
TOTAL_SNAPSHOTS_HUB = 10

os.makedirs(PASTA_OFERTAS_RELAMPAGO, exist_ok=True)
os.makedirs(PASTA_OFERTAS_HUB, exist_ok=True)
os.makedirs(PASTA_RELAMPAGO_HTML, exist_ok=True)
os.makedirs(PASTA_RELAMPAGO_HISTORICO, exist_ok=True)
os.makedirs(PASTA_AFILIADOS_HTML, exist_ok=True)
os.makedirs(PASTA_AFILIADOS_HISTORICO, exist_ok=True)
os.makedirs(PASTA_METADADOS_COLETA, exist_ok=True)


def _formatar_preco_txt(valor):

    texto = str(valor or "-").strip()
    if not texto:
        return "-"

    if texto != "-" and not texto.startswith("R$"):
        texto = f"R$ {texto}"

    return texto


def _proxima_execucao_fluxo(fluxo, arquivo_controle=ARQUIVO_CONTROLE_EXECUCOES):

    os.makedirs(Path(arquivo_controle).parent, exist_ok=True)

    controle = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "fluxos": {},
    }

    if Path(arquivo_controle).exists():
        try:
            controle_lido = json.loads(Path(arquivo_controle).read_text(encoding="utf-8"))
            if isinstance(controle_lido, dict):
                controle.update(controle_lido)
        except Exception:
            pass

    fluxos = controle.get("fluxos") if isinstance(controle.get("fluxos"), dict) else {}
    atual = fluxos.get(fluxo) if isinstance(fluxos.get(fluxo), int) else 0
    proximo = atual + 1
    fluxos[fluxo] = proximo

    controle["fluxos"] = fluxos
    controle["atualizado_em"] = datetime.now().isoformat(timespec="seconds")

    with open(arquivo_controle, "w", encoding="utf-8") as arquivo:
        json.dump(controle, arquivo, ensure_ascii=False, indent=2)

    return proximo


def _salvar_metadados_ofertas(
    ofertas,
    fluxo,
    pasta=PASTA_METADADOS_COLETA,
    id_execucao=None,
    contexto_execucao=None,
):

    ofertas = ofertas or []

    if not fluxo:
        raise ValueError("Fluxo de metadados deve ser informado.")

    os.makedirs(pasta, exist_ok=True)

    if id_execucao is None:
        id_execucao = _proxima_execucao_fluxo(fluxo)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, f"metadados_{fluxo}_exec_{id_execucao:04d}_{timestamp}.json")

    campos_base = [
        "id_anuncio",
        "descricao",
        "categoria",
        "antes",
        "depois",
        "desconto",
        "link",
        "link_original",
        "link_anuncio",
    ]

    campos_origem = [
        "pagina_origem_url",
        "pagina_origem_numero",
        "arquivo_origem_html",
        "snapshot_origem_indice",
        "scrolls_estimados",
        "posicao_html",
    ]

    metadados = []
    for indice, oferta in enumerate(ofertas, start=1):
        item = {"ordem": indice}

        for campo in campos_base + campos_origem:
            item[campo] = oferta.get(campo)

        metadados.append(item)

    payload = {
        "fluxo": fluxo,
        "id_execucao": id_execucao,
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "total_ofertas": len(metadados),
        "contexto_execucao": contexto_execucao or {},
        "ofertas": metadados,
    }

    with open(caminho, "w", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False, indent=2)

    print(f"Metadados salvos em: {caminho}")
    return caminho


def _salvar_html_atual(page, pasta, prefixo, indice=None):

    os.makedirs(pasta, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    sufixo = f"_{indice:02d}" if indice is not None else ""
    caminho = os.path.join(pasta, f"{prefixo}_{timestamp}{sufixo}.txt")

    with open(caminho, "w", encoding="utf-8") as arquivo:
        arquivo.write(page.content())

    print(f"HTML salvo em: {caminho}")
    return caminho


def _salvar_html_consolidado(entradas_html, pasta, prefixo):

    if not entradas_html:
        return None

    os.makedirs(pasta, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, f"{prefixo}_{timestamp}.txt")

    with open(caminho, "w", encoding="utf-8") as arquivo:
        for indice, entrada in enumerate(entradas_html, start=1):
            arquivo.write(f"\n===== INICIO HTML {indice} | URL: {entrada.get('url', '-')} =====\n")
            arquivo.write(Path(entrada["path"]).read_text(encoding="utf-8"))
            arquivo.write(f"\n===== FIM HTML {indice} =====\n")

    print(f"HTML consolidado salvo em: {caminho}")
    return caminho


def _limpar_htmls_relampago_antigos(pasta, caminhos_manter):

    pasta_path = Path(pasta)
    if not pasta_path.exists():
        return

    caminhos_validos = {
        str(Path(caminho).resolve())
        for caminho in (caminhos_manter or [])
        if caminho
    }

    removidos = 0
    for arquivo in pasta_path.glob("html_relampago*.txt"):
        caminho_resolvido = str(arquivo.resolve())
        if caminho_resolvido in caminhos_validos:
            continue

        try:
            arquivo.unlink()
            removidos += 1
        except Exception as exc:
            print(f"[AVISO] Não foi possível remover HTML antigo '{arquivo}': {exc}")

    if removidos:
        print(f"Limpeza de HTML relâmpago: {removidos} arquivo(s) antigo(s) removido(s).")


def salvar_html_ofertas_relampago(page, url, indice=None, pasta=PASTA_RELAMPAGO_HTML):
    """Navega até uma página de ofertas relâmpago, faz scroll e salva o HTML."""

    print(f"\nNavegando para ofertas relâmpago:\n{url}")

    page.goto(url, timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(4, 6))

    for _ in range(6):
        page.mouse.wheel(0, 2000)
        time.sleep(random.uniform(1.2, 2.0))

    return _salvar_html_atual(page, pasta, "html_relampago", indice=indice)


def extrair_ofertas_do_html(caminho_arquivo, desconto_minimo=None):
    """Lê o HTML salvo em caminho_arquivo, localiza os poly-cards e retorna
    a lista de ofertas compatíveis com o desconto mínimo, quando informado.

    Cada oferta é um dicionário com as chaves:
        categoria, descricao, antes, desconto, depois
    """

    print(f"\nAnalisando HTML de: {caminho_arquivo}")

    with open(caminho_arquivo, "r", encoding="utf-8") as f:
        html = f.read()

    ofertas_ctx = _extrair_ofertas_do_ctx(html, desconto_minimo or 0)
    if ofertas_ctx:
        return ofertas_ctx

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.poly-card")

    print(f"{len(cards)} card(s) encontrado(s) no HTML.")

    ofertas = []

    for posicao_html, card in enumerate(cards, start=1):

        # --- Desconto ---
        desconto_el = card.select_one("[data-andes-money-amount-discount='true']")
        if not desconto_el:
            continue

        texto_desconto = desconto_el.get_text(strip=True)
        encontrado = re.search(r"(\d+)", texto_desconto)
        if not encontrado:
            continue

        desconto_val = int(encontrado.group(1))
        if desconto_minimo is not None and desconto_val < desconto_minimo:
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

        href = titulo_el.get("href", "") if titulo_el else ""
        link_anuncio = _normalizar_url_resultado(href)
        id_anuncio = _extrair_id_anuncio_de_texto(link_anuncio or descricao)

        ofertas.append({
            "id_anuncio": id_anuncio,
            "categoria": categoria,
            "descricao": descricao,
            "antes": antes,
            "desconto": texto_desconto,
            "depois": depois,
            "depois_valor": _converter_preco_em_float(depois),
            "link_anuncio": link_anuncio,
            "posicao_html": posicao_html,
        })

    print(f"{len(ofertas)} oferta(s) extraída(s) do HTML.")

    return ofertas


def _tem_filtros_ativos(desconto_minimo=None, preco_minimo=None, preco_maximo=None, descricao=None):

    return any(
        [
            desconto_minimo is not None,
            preco_minimo is not None,
            preco_maximo is not None,
            bool(normalizar_descricao(descricao or "")),
        ]
    )


def _aplicar_filtro_categoria_hub(page, categoria):

    categoria_limpa = normalizar_descricao(categoria)
    if not categoria_limpa:
        return page.url

    try:
        page.locator("span.tag-icon__text").filter(has_text="Filtrar").first.click(timeout=8000)
        time.sleep(random.uniform(1, 2))
        page.locator("div.andes-accordion-header-container__title").filter(has_text="Categorias").first.click(timeout=5000)
        time.sleep(random.uniform(1, 2))
        page.locator("label.andes-radio__label").filter(has_text=categoria_limpa).first.click(timeout=5000)
        time.sleep(random.uniform(1, 2))
        page.get_by_role("button", name="Aplicar").click(timeout=5000)
        time.sleep(random.uniform(3, 5))
    except Exception as exc:
        print(f"[AVISO] Não foi possível aplicar o filtro de categoria no hub: {exc}")

    return page.url


def _coletar_htmls_hub_afiliados(
    page,
    url_hub,
    categoria=None,
    pasta=PASTA_AFILIADOS_HTML,
    total_snapshots=TOTAL_SNAPSHOTS_HUB,
    usar_scroll=True,
):

    print(f"\nNavegando para o hub de afiliados:\n{url_hub}")

    page.goto(url_hub, timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(4, 6))

    url_base = _aplicar_filtro_categoria_hub(page, categoria) if categoria else page.url
    entradas_html = []

    total_snapshots = max(1, int(total_snapshots or 1))

    for indice in range(total_snapshots):
        caminho_html = _salvar_html_atual(page, pasta, "html_afiliados", indice=indice + 1)
        entradas_html.append({
            "path": caminho_html,
            "url": page.url or url_base,
            "indice": indice + 1,
        })

        if usar_scroll and indice < total_snapshots - 1:
            page.mouse.wheel(0, 2500)
            time.sleep(random.uniform(1.2, 2.0))

    _salvar_html_consolidado(entradas_html, pasta, "html_afiliados_consolidado")
    return entradas_html, url_base


def _selecionar_ofertas_validas(
    entradas_html,
    desconto_minimo=None,
    preco_minimo=None,
    preco_maximo=None,
    descricao=None,
    limite_validos=10,
    ids_descartados=None,
):

    descricao_filtro = normalizar_descricao(descricao).casefold() if descricao else ""
    usar_filtros = _tem_filtros_ativos(
        desconto_minimo=desconto_minimo,
        preco_minimo=preco_minimo,
        preco_maximo=preco_maximo,
        descricao=descricao,
    )

    selecionadas = []
    ids_vistos = set()
    descricoes_vistas = set()
    ids_descartados = set(
        _normalizar_chave_historico(item)
        for item in (ids_descartados or set())
        if item
    )

    for entrada in entradas_html:
        ofertas = extrair_ofertas_do_html(
            entrada["path"],
            desconto_minimo=desconto_minimo if usar_filtros else None,
        )

        if not ofertas:
            continue

        for oferta in ofertas:
            descricao_oferta = normalizar_descricao(oferta.get("descricao"))
            chave_descricao = descricao_oferta.casefold()
            id_anuncio = _normalizar_chave_historico(oferta.get("id_anuncio"))

            if not descricao_oferta or not id_anuncio:
                continue

            if id_anuncio in ids_descartados:
                print(
                    f"[DESCARTADO - HISTORICO] Anúncio {id_anuncio} marcado como anuncio_inedito=false no histórico."
                )
                continue

            if id_anuncio in ids_vistos or chave_descricao in descricoes_vistas:
                continue

            preco_atual = oferta.get("depois_valor")
            if preco_atual is None:
                continue

            if descricao_filtro and descricao_filtro not in chave_descricao:
                continue

            if preco_minimo is not None and preco_atual < preco_minimo:
                continue

            if preco_maximo is not None and preco_atual > preco_maximo:
                continue

            ids_vistos.add(id_anuncio)
            descricoes_vistas.add(chave_descricao)

            oferta["pagina_origem_url"] = entrada.get("url")
            oferta["arquivo_origem_html"] = entrada.get("path")
            oferta["pagina_origem_numero"] = entrada.get("pagina")
            oferta["snapshot_origem_indice"] = entrada.get("indice")

            indice_origem = entrada.get("indice")
            if indice_origem is not None:
                try:
                    oferta["scrolls_estimados"] = max(0, int(indice_origem) - 1)
                except (TypeError, ValueError):
                    pass

            oferta["link_original"] = oferta.get("link_anuncio") or ""
            oferta["link"] = oferta.get("link_anuncio") or "Link não obtido"
            selecionadas.append(oferta)

            if limite_validos is not None and len(selecionadas) >= limite_validos:
                return selecionadas

    return selecionadas


def processar_produtos_hub_por_html(
    page,
    url_hub,
    desconto_minimo=30,
    categoria=None,
    preco_minimo=None,
    preco_maximo=None,
    descricao=None,
    limite_candidatos=None,
    historico_anuncios=None,
    limite_validos=10,
):
    """Fluxo do hub/afiliados em duas etapas: snapshots HTML e enriquecimento por ID."""

    id_execucao = _proxima_execucao_fluxo("afiliados")

    modo_sem_parametros = (
        not _tem_filtros_ativos(
            desconto_minimo=desconto_minimo,
            preco_minimo=preco_minimo,
            preco_maximo=preco_maximo,
            descricao=descricao,
        )
        and not normalizar_descricao(categoria or "")
        and limite_candidatos is None
    )

    total_snapshots = 1 if modo_sem_parametros else TOTAL_SNAPSHOTS_HUB
    usar_scroll_snapshots = not modo_sem_parametros

    entradas_html, url_base = _coletar_htmls_hub_afiliados(
        page,
        url_hub,
        categoria=categoria,
        pasta=PASTA_AFILIADOS_HTML,
        total_snapshots=total_snapshots,
        usar_scroll=usar_scroll_snapshots,
    )

    candidatos = _selecionar_ofertas_validas(
        entradas_html,
        desconto_minimo=desconto_minimo,
        preco_minimo=preco_minimo,
        preco_maximo=preco_maximo,
        descricao=descricao,
        limite_validos=limite_validos if limite_candidatos is None else min(limite_validos, limite_candidatos),
    )

    if not candidatos:
        _salvar_metadados_ofertas(
            [],
            "afiliados",
            id_execucao=id_execucao,
            contexto_execucao={
                "status": "sem_ofertas",
                "pasta_html": PASTA_AFILIADOS_HTML,
                "pasta_historico": PASTA_AFILIADOS_HISTORICO,
                "categoria": categoria,
                "desconto_minimo": desconto_minimo,
                "preco_minimo": preco_minimo,
                "preco_maximo": preco_maximo,
                "descricao": descricao,
                "limite_candidatos": limite_candidatos,
                "limite_validos": limite_validos,
            },
        )
        print("\nNenhuma oferta encontrada no HTML do hub/afiliados.")
        return []

    ofertas_enriquecidas = _enriquecer_ofertas_hub_com_links(
        page,
        url_base,
        categoria,
        candidatos,
        permitir_scroll=not modo_sem_parametros,
    )

    for oferta in ofertas_enriquecidas:
        oferta["id_execucao_fluxo"] = id_execucao

    _salvar_metadados_ofertas(
        ofertas_enriquecidas,
        "afiliados",
        id_execucao=id_execucao,
        contexto_execucao={
            "status": "ok",
            "pasta_html": PASTA_AFILIADOS_HTML,
            "pasta_historico": PASTA_AFILIADOS_HISTORICO,
            "categoria": categoria,
            "desconto_minimo": desconto_minimo,
            "preco_minimo": preco_minimo,
            "preco_maximo": preco_maximo,
            "descricao": descricao,
            "limite_candidatos": limite_candidatos,
            "limite_validos": limite_validos,
            "modo_sem_parametros": modo_sem_parametros,
        },
    )

    return ofertas_enriquecidas


def salvar_resultado_hub(ofertas, pasta=None):
    """Registra as ofertas de afiliados em um único arquivo histórico."""

    if not ofertas:
        return None

    if not pasta:
        pasta = PASTA_AFILIADOS_HISTORICO

    os.makedirs(pasta, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, "historico_afiliados.txt")

    with open(caminho, "a", encoding="utf-8") as file:
        file.write(f"===== EXECUCAO {timestamp} | TOTAL {len(ofertas)} =====\n\n")
        for oferta in ofertas:
            file.write(f"Categoria: {oferta.get('categoria', '-') }\n")
            file.write(f"Descrição: {oferta.get('descricao', '-') }\n")
            file.write(f"Antes: ~{_formatar_preco_txt(oferta.get('antes', '-'))}~\n")
            file.write(f"*Desconto: {oferta.get('desconto', '-')}*\n")
            file.write(f"*Depois: {_formatar_preco_txt(oferta.get('depois', '-'))}*\n")
            file.write(f"Link: {oferta.get('link', '-') }\n")
            file.write("\n-----------------------------\n\n")

    print(f"\nHistórico de afiliados atualizado em: {caminho}")

    return caminho


def _coletar_links_visiveis_por_id(page):

    cards = page.locator("li.poly-card")
    total = cards.count()
    links = {}

    for indice in range(total):
        card = cards.nth(indice)

        try:
            href = card.locator("a.poly-component__title[href]").first.get_attribute("href", timeout=1000)
        except Exception:
            continue

        href_normalizado = _normalizar_url_resultado(href or "")
        id_anuncio = _normalizar_chave_historico(_extrair_id_anuncio_de_texto(href_normalizado))

        if id_anuncio and href_normalizado:
            links[id_anuncio] = href_normalizado

    return links


def _abrir_anuncio_em_nova_aba(page, url_anuncio):

    detalhe_page = page.context.new_page()

    try:
        detalhe_page.goto(url_anuncio, timeout=90000, wait_until="domcontentloaded")
        time.sleep(random.uniform(3, 5))

        categoria = _extrair_categoria_do_breadcrumb(detalhe_page)
        link = _obter_link_via_botao_afiliados(detalhe_page, url_anuncio)
        return link, categoria
    finally:
        detalhe_page.close()


def _enriquecer_ofertas_hub_com_links(page, url_base, categoria, ofertas, permitir_scroll=True):

    pendentes = {}

    for oferta in ofertas:
        href_direto = _normalizar_url_resultado(
            oferta.get("link_anuncio") or oferta.get("link_original") or ""
        )

        if href_direto:
            link_afiliado, categoria_breadcrumb = _abrir_anuncio_em_nova_aba(page, href_direto)
            oferta["link_original"] = href_direto
            oferta["link"] = link_afiliado or href_direto
            if categoria_breadcrumb and categoria_breadcrumb != "Sem categoria":
                oferta["categoria"] = categoria_breadcrumb
            continue

        id_anuncio = _normalizar_chave_historico(oferta.get("id_anuncio"))
        if id_anuncio:
            pendentes[id_anuncio] = oferta

    if not pendentes:
        return ofertas

    page.goto(url_base, timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(4, 6))

    if categoria:
        url_base = _aplicar_filtro_categoria_hub(page, categoria)

    max_varreduras = TOTAL_SNAPSHOTS_HUB + 2 if permitir_scroll else 1

    for _ in range(max_varreduras):
        links_visiveis = _coletar_links_visiveis_por_id(page)

        for id_anuncio in list(pendentes.keys()):
            href = links_visiveis.get(id_anuncio)
            if not href:
                continue

            oferta = pendentes.pop(id_anuncio)
            link_afiliado, categoria_breadcrumb = _abrir_anuncio_em_nova_aba(page, href)
            oferta["link_original"] = href
            oferta["link"] = link_afiliado or href
            if categoria_breadcrumb and categoria_breadcrumb != "Sem categoria":
                oferta["categoria"] = categoria_breadcrumb

        if not pendentes:
            break

        if permitir_scroll:
            page.mouse.wheel(0, 2500)
            time.sleep(random.uniform(1.2, 2.0))

    for id_anuncio, oferta in pendentes.items():
        href = oferta.get("link_anuncio") or oferta.get("link_original")
        if not href:
            continue

        link_afiliado, categoria_breadcrumb = _abrir_anuncio_em_nova_aba(page, href)
        oferta["link_original"] = href
        oferta["link"] = link_afiliado or href
        if categoria_breadcrumb and categoria_breadcrumb != "Sem categoria":
            oferta["categoria"] = categoria_breadcrumb

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

        if botao.count() == 0:
            url_atual = (page.url or "").lower()
            try:
                pagina_tem_link_login = page.locator("a[href*='login']").count() > 0
            except Exception:
                pagina_tem_link_login = False

            if "login" in url_atual or pagina_tem_link_login:
                raise RuntimeError(
                    "Sessao do Mercado Livre nao autenticada: botao de Afiliados indisponivel. "
                    "Faça login e execute novamente."
                )

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
        if isinstance(exc, RuntimeError):
            raise

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


def _coletar_resultados_pesquisa_da_pagina(page):

    return page.evaluate(
        """() => {
            const cards = Array.from(document.querySelectorAll('li.ui-search-layout__item, li.poly-card'));
            const resultados = [];

            for (const card of cards) {
                const titleEl = card.querySelector('a.poly-component__title, a.ui-search-item__group__element--title, a[href*="/MLB-"]');
                if (!titleEl) {
                    continue;
                }

                const descricao = (titleEl.textContent || '').trim();
                const href = (titleEl.getAttribute('href') || '').trim();

                const fraction = card.querySelector('[data-andes-money-amount-fraction="true"]');
                const cents = card.querySelector('[data-andes-money-amount-cents="true"]');

                let precoTexto = '';
                if (fraction) {
                    const reais = (fraction.textContent || '').trim();
                    const centavos = cents ? (cents.textContent || '').trim() : '';
                    precoTexto = centavos ? `R$ ${reais},${centavos}` : `R$ ${reais}`;
                }

                resultados.push({
                    descricao,
                    href,
                    precoTexto,
                });
            }

            return resultados;
        }"""
    )


def buscar_produto_por_descricao(
    page,
    descricao,
    preco_minimo=None,
    preco_maximo=None,
    menor_preco=False,
    limite_paginas=5,
    historico_anuncios=None,
):
    """Busca por descrição na pesquisa genérica do Mercado Livre e retorna um
    candidato válido com link de afiliado.

    Quando menor_preco=True, escolhe o item com menor preço dentre os
    resultados coletados.
    """

    descricao = normalizar_descricao(descricao)
    if not descricao:
        return None

    historico_ids = set(
        _normalizar_chave_historico(item) for item in (historico_anuncios or set()) if item
    )

    candidatos = []
    ids_vistos = set()

    for pagina in range(1, max(1, limite_paginas) + 1):

        url = _montar_url_pesquisa_generica(descricao, pagina)

        print(f"\n[Busca genérica] Página {pagina}: {url}")

        page.goto(url, timeout=90000, wait_until="domcontentloaded")
        time.sleep(random.uniform(3, 5))

        resultados = _coletar_resultados_pesquisa_da_pagina(page)

        if not resultados:
            print("Sem resultados nessa página.")
            continue

        for resultado in resultados:

            url_anuncio = _normalizar_url_resultado(resultado.get("href"))
            id_anuncio = _normalizar_chave_historico(
                _extrair_id_anuncio_de_texto(url_anuncio)
            )

            if not id_anuncio or id_anuncio in ids_vistos or id_anuncio in historico_ids:
                continue

            preco_valor = _converter_preco_em_float(resultado.get("precoTexto"))
            if preco_valor is None:
                continue

            if preco_minimo is not None and preco_valor < preco_minimo:
                continue

            if preco_maximo is not None and preco_valor > preco_maximo:
                continue

            ids_vistos.add(id_anuncio)

            candidatos.append(
                {
                    "id_anuncio": id_anuncio,
                    "categoria": "Pesquisa genérica",
                    "descricao": normalizar_descricao(resultado.get("descricao") or descricao),
                    "antes": "Sem preço anterior",
                    "desconto": "Sem desconto",
                    "depois": _formatar_preco(preco_valor),
                    "depois_valor": preco_valor,
                    "link_anuncio": url_anuncio,
                }
            )

    if not candidatos:
        print("\nNenhum candidato válido encontrado para a busca por descrição.")
        return None

    if menor_preco:
        candidatos.sort(key=lambda item: item.get("depois_valor", float("inf")))

    escolhido = candidatos[0]

    print(
        f"\nCandidato escolhido: {escolhido.get('descricao')} | {escolhido.get('depois')}"
    )

    page.goto(escolhido.get("link_anuncio"), timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(3, 5))

    categoria = _extrair_categoria_do_breadcrumb(page)
    link_afiliado = _obter_link_via_botao_afiliados(page, escolhido.get("link_anuncio"))

    escolhido["categoria"] = categoria or "Pesquisa genérica"
    escolhido["link_original"] = escolhido.get("link_anuncio")
    escolhido["link"] = link_afiliado or escolhido.get("link_anuncio")

    return escolhido


def obter_link_afiliado_relampago(page, oferta, url_relampago):
    """Reabre a página de ofertas relâmpago, localiza o card correspondente
    à oferta, abre o anúncio, extrai a categoria do breadcrumb e obtém o
    link de afiliado via botão Compartilhar do nav Afiliados.
    Retorna tupla (link, categoria)."""

    descricao = oferta.get("descricao", "")
    id_anuncio = _normalizar_chave_historico(oferta.get("id_anuncio"))
    link_anuncio = _normalizar_url_resultado(oferta.get("link_anuncio") or "")
    url_lista = oferta.get("pagina_origem_url") or url_relampago

    # Caminho rápido: quando o href do anúncio já veio do HTML salvo,
    # abre direto o anúncio sem percorrer novamente toda a listagem.
    if link_anuncio:
        print("Usando link direto extraído do HTML para obter link de afiliado.")
        link, categoria = _abrir_anuncio_em_nova_aba(page, link_anuncio)
        return link, categoria, link_anuncio

    print(f"\n--- Buscando link de afiliado para: {descricao[:70]}...")

    page.goto(url_lista, timeout=90000, wait_until="domcontentloaded")
    time.sleep(random.uniform(4, 6))

    for _ in range(10):
        links_visiveis = _coletar_links_visiveis_por_id(page)
        if id_anuncio and id_anuncio in links_visiveis:
            link_anuncio = links_visiveis[id_anuncio]
            break

        if not link_anuncio:
            link_anuncio = _localizar_card_na_pagina(page, descricao)
            if link_anuncio:
                break

        page.mouse.wheel(0, 2500)
        time.sleep(random.uniform(1, 2))

    if not link_anuncio:
        print("[AVISO] Card não localizado na página de ofertas relâmpago.")
        return None, "Sem categoria", ""

    print(f"Abrindo anúncio: {link_anuncio[:80]}...")

    link, categoria = _abrir_anuncio_em_nova_aba(page, link_anuncio)

    return link, categoria, link_anuncio


def _coletar_htmls_relampago(
    page,
    url_base_paginas,
    pasta=PASTA_RELAMPAGO_HTML,
    coletar_todas_paginas=True,
    salvar_consolidado=True,
    max_paginas_total=None,
):

    entradas_html = []
    caminho_inicial = salvar_html_ofertas_relampago(page, url_base_paginas, indice=1, pasta=pasta)
    entradas_html.append({"path": caminho_inicial, "url": url_base_paginas, "pagina": 1})

    if coletar_todas_paginas:
        paging = _extrair_paging_do_html(Path(caminho_inicial).read_text(encoding="utf-8")) or {}
        limite = paging.get("limit", 48) or 48
        total = paging.get("total", 0) or 0
        total_paginas = max(1, ceil(total / limite)) if total and limite else 1

        if max_paginas_total is not None:
            total_paginas = min(total_paginas, max(1, int(max_paginas_total)))

        print(f"Paginação detectada: {total_paginas} página(s) com limite de {limite} item(ns) por página.")

        for pagina in range(2, total_paginas + 1):
            url_pagina = _montar_url_paginada(url_base_paginas, pagina)
            caminho_html = salvar_html_ofertas_relampago(page, url_pagina, indice=pagina, pasta=pasta)
            entradas_html.append({"path": caminho_html, "url": url_pagina, "pagina": pagina})
    else:
        print("Modo sem parametros detectado: usando apenas o primeiro HTML de ofertas relampago.")

    caminho_consolidado = None
    if salvar_consolidado:
        caminho_consolidado = _salvar_html_consolidado(entradas_html, pasta, "html_relampago_consolidado")

    return entradas_html, caminho_consolidado


def _obter_total_paginas_relampago(caminho_html):

    try:
        html = Path(caminho_html).read_text(encoding="utf-8")
    except Exception:
        return 1

    paging = _extrair_paging_do_html(html) or {}
    limite = paging.get("limit", 48) or 48
    total = paging.get("total", 0) or 0

    if not total or not limite:
        return 1

    return max(1, ceil(total / limite))


def _enriquecer_ofertas_relampago_com_links(page, url_base_paginas, ofertas):

    for oferta in ofertas:
        link_afiliado, categoria_breadcrumb, link_original = obter_link_afiliado_relampago(
            page,
            oferta,
            url_base_paginas,
        )
        oferta["link_original"] = link_original or oferta.get("link_anuncio") or ""
        oferta["link"] = link_afiliado or oferta["link_original"] or "Link não obtido"
        if categoria_breadcrumb and categoria_breadcrumb != "Sem categoria":
            oferta["categoria"] = categoria_breadcrumb

    return ofertas


def processar_ofertas_relampago(
    page,
    url_relampago,
    desconto_minimo=30,
    categoria=None,
    preco_minimo=None,
    preco_maximo=None,
    limite_candidatos=None,
    historico_anuncios=None,
    ids_descartados=None,
    limite_validos=10,
    forcar_modo_incremental=False,
    max_paginas_incremental=None,
):
    """Fluxo completo de ofertas relâmpago:

    1. Navega até a URL e salva o HTML completo em ofertas_relampago/.
    2. Analisa o HTML e extrai ofertas com desconto >= desconto_minimo.
    3. Para cada oferta, reabre a página, localiza o card, abre o anúncio
       e obtém o link de afiliado encurtado.
    4. Retorna a lista de ofertas enriquecida com o campo 'link'.
    """

    id_execucao = _proxima_execucao_fluxo("relampago")

    categoria_filtro = _normalizar_filtro_categoria(categoria) if categoria else ""

    url_base_paginas = url_relampago

    if categoria_filtro:
        url_base_paginas = _resolver_url_base_relampago(page, url_relampago, categoria)

    if ids_descartados is None and historico_anuncios:
        ids_descartados = historico_anuncios

    modo_sem_parametros = bool(forcar_modo_incremental) or (
        not categoria_filtro
        and not _tem_filtros_ativos(
            desconto_minimo=desconto_minimo,
            preco_minimo=preco_minimo,
            preco_maximo=preco_maximo,
            descricao=None,
        )
        and limite_candidatos is None
    )

    caminho_html_consolidado = None

    # Mantém somente HTMLs da execução atual, evitando acúmulo de arquivos antigos.
    _limpar_htmls_relampago_antigos(PASTA_RELAMPAGO_HTML, caminhos_manter=[])

    limite_alvo = limite_validos if limite_candidatos is None else min(limite_validos, limite_candidatos)

    if modo_sem_parametros:
        MAX_PAGINAS_RELAMPAGO_SEM_PARAMETROS = 2 if forcar_modo_incremental else 30
        MAX_PAGINAS_SEM_PROGRESSO = 5

        entradas_html, caminho_html_consolidado = _coletar_htmls_relampago(
            page,
            url_base_paginas,
            pasta=PASTA_RELAMPAGO_HTML,
            coletar_todas_paginas=False,
            salvar_consolidado=False,
        )

        ofertas_consolidadas = _selecionar_ofertas_validas(
            entradas_html,
            desconto_minimo=desconto_minimo,
            preco_minimo=preco_minimo,
            preco_maximo=preco_maximo,
            descricao=None,
            limite_validos=limite_alvo,
            ids_descartados=ids_descartados,
        )

        total_paginas = _obter_total_paginas_relampago(entradas_html[0]["path"])
        limite_paginas_incremental = (
            max(1, int(max_paginas_incremental))
            if max_paginas_incremental is not None
            else MAX_PAGINAS_RELAMPAGO_SEM_PARAMETROS
        )
        total_paginas_planejado = min(total_paginas, limite_paginas_incremental)
        paginas_sem_progresso = 0
        pagina_atual = 1

        while len(ofertas_consolidadas) < limite_alvo and pagina_atual < total_paginas_planejado:
            pagina_atual += 1
            total_antes = len(ofertas_consolidadas)
            print(
                f"Primeira página não foi suficiente ({len(ofertas_consolidadas)}/{limite_alvo}). "
                f"Coletando página {pagina_atual}/{total_paginas_planejado}."
            )

            url_pagina = _montar_url_paginada(url_base_paginas, pagina_atual)
            caminho_html = salvar_html_ofertas_relampago(
                page,
                url_pagina,
                indice=pagina_atual,
                pasta=PASTA_RELAMPAGO_HTML,
            )
            entradas_html.append({"path": caminho_html, "url": url_pagina, "pagina": pagina_atual})

            ofertas_consolidadas = _selecionar_ofertas_validas(
                entradas_html,
                desconto_minimo=desconto_minimo,
                preco_minimo=preco_minimo,
                preco_maximo=preco_maximo,
                descricao=None,
                limite_validos=limite_alvo,
                ids_descartados=ids_descartados,
            )

            if len(ofertas_consolidadas) <= total_antes:
                paginas_sem_progresso += 1
            else:
                paginas_sem_progresso = 0

            if paginas_sem_progresso >= MAX_PAGINAS_SEM_PROGRESSO:
                print(
                    f"Parando paginação: {MAX_PAGINAS_SEM_PROGRESSO} página(s) seguidas sem novas ofertas válidas."
                )
                break

        if total_paginas > total_paginas_planejado:
            print(
                f"Paginação limitada a {total_paginas_planejado} página(s) para evitar varredura excessiva "
                f"(detecção original: {total_paginas} página(s))."
            )

        caminho_html_consolidado = _salvar_html_consolidado(
            entradas_html,
            PASTA_RELAMPAGO_HTML,
            "html_relampago_consolidado",
        )
    else:
        entradas_html, caminho_html_consolidado = _coletar_htmls_relampago(
            page,
            url_base_paginas,
            pasta=PASTA_RELAMPAGO_HTML,
            coletar_todas_paginas=True,
            max_paginas_total=25,
        )

        ofertas_consolidadas = _selecionar_ofertas_validas(
            entradas_html,
            desconto_minimo=desconto_minimo,
            preco_minimo=preco_minimo,
            preco_maximo=preco_maximo,
            descricao=None,
            limite_validos=limite_alvo,
            ids_descartados=ids_descartados,
        )

    caminhos_html_execucao = [entrada.get("path") for entrada in entradas_html if entrada.get("path")]
    if caminho_html_consolidado:
        caminhos_html_execucao.append(caminho_html_consolidado)
    _limpar_htmls_relampago_antigos(PASTA_RELAMPAGO_HTML, caminhos_html_execucao)

    if not ofertas_consolidadas:
        _salvar_metadados_ofertas(
            [],
            "relampago",
            id_execucao=id_execucao,
            contexto_execucao={
                "status": "sem_ofertas",
                "pasta_html": PASTA_RELAMPAGO_HTML,
                "pasta_historico": PASTA_RELAMPAGO_HISTORICO,
                "categoria": categoria,
                "desconto_minimo": desconto_minimo,
                "preco_minimo": preco_minimo,
                "preco_maximo": preco_maximo,
                "limite_candidatos": limite_candidatos,
                "limite_validos": limite_validos,
                "modo_sem_parametros": modo_sem_parametros,
            },
        )
        print("\nNenhuma oferta elegível encontrada.")
        return []

    ofertas_enriquecidas = _enriquecer_ofertas_relampago_com_links(page, url_base_paginas, ofertas_consolidadas)

    for oferta in ofertas_enriquecidas:
        oferta["id_execucao_fluxo"] = id_execucao

    _salvar_metadados_ofertas(
        ofertas_enriquecidas,
        "relampago",
        id_execucao=id_execucao,
        contexto_execucao={
            "status": "ok",
            "pasta_html": PASTA_RELAMPAGO_HTML,
            "pasta_historico": PASTA_RELAMPAGO_HISTORICO,
            "categoria": categoria,
            "desconto_minimo": desconto_minimo,
            "preco_minimo": preco_minimo,
            "preco_maximo": preco_maximo,
            "limite_candidatos": limite_candidatos,
            "limite_validos": limite_validos,
            "modo_sem_parametros": modo_sem_parametros,
            "url_base_paginas": url_base_paginas,
        },
    )

    return ofertas_enriquecidas


def salvar_resultado_relampago(ofertas, pasta=None):
    """Registra as ofertas relâmpago em um único arquivo histórico."""

    if not ofertas:
        return

    if not pasta:
        pasta = PASTA_RELAMPAGO_HISTORICO

    os.makedirs(pasta, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, "lista_anuncios.txt")

    def _formatar_preco_txt(valor):

        texto = str(valor or "-").strip()
        if not texto:
            return "-"

        if texto != "-" and not texto.startswith("R$"):
            texto = f"R$ {texto}"

        return texto

    with open(caminho, "a", encoding="utf-8") as f:
        f.write(f"===== EXECUCAO {timestamp} | TOTAL {len(ofertas)} =====\n\n")
        for oferta in ofertas:
            f.write(f"Categoria: {oferta.get('categoria', '-')}\n")
            f.write(f"Descrição: {oferta.get('descricao', '-')}\n")
            f.write(f"Antes: ~{_formatar_preco_txt(oferta.get('antes', '-'))}~\n")
            f.write(f"*Desconto: {oferta.get('desconto', '-')}*\n")
            f.write(f"*Depois: {_formatar_preco_txt(oferta.get('depois', '-'))}*\n")
            f.write(f"Link: {oferta.get('link', '-')}\n")
            f.write("\n-----------------------------\n\n")

    print(f"\nHistórico relâmpago atualizado em: {caminho}")

    return caminho