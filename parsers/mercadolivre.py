import re
import random
import time


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

        link_original = card.locator(
            "a.poly-component__title[href], a[href*='mercadolivre.com.br'][href*='polycard_client=affiliates']"
        ).first.get_attribute("href", timeout=1500)

        link_original = (link_original or "").strip()

    except Exception:

        link_original = ""

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