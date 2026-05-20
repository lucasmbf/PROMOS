import random
import time


def obter_link_encurtado(page, url_original):

    try:

        # Clica no botão Compartilhar
        botao = page.locator(
            "button:has-text('Compartilhar'), button[aria-label*='ompartilhar']"
        ).first

        botao.wait_for(state="visible", timeout=8000)

        botao.click()

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

        icone_link.click()

        time.sleep(random.uniform(1, 2))

        # Tenta ler a URL encurtada do textarea identificado no modal
        campo = page.locator(
            "textarea[data-testid='text-field__label_link']"
        ).first

        try:

            campo.wait_for(state="visible", timeout=5000)

            link_encurtado = campo.input_value()

            if link_encurtado:

                # Fecha o modal se possível
                page.keyboard.press("Escape")

                return link_encurtado

        except Exception:

            pass

        # Fallback: tenta ler do clipboard via JS
        try:

            link_encurtado = page.evaluate(
                "navigator.clipboard.readText()"
            )

            if link_encurtado and (
                "mercadolivre" in link_encurtado or "meli.la" in link_encurtado
            ):

                page.keyboard.press("Escape")

                return link_encurtado

        except Exception:

            pass

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