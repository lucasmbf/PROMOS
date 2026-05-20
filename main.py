from playwright.sync_api import sync_playwright

from parsers.mercadolivre import mercado_livre

import os
import random
import time
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

URL_LISTAGEM = "https://www.mercadolivre.com.br/afiliados/hub"

DESCONTO_MINIMO = 50

PRECO_MINIMO = None

PRECO_MAXIMO = 300

LIMITE_PRODUTOS = 3

LIMITE_CANDIDATOS = 10

CATEGORIA_PADRAO = "Casa, Móveis e Decoração"

load_dotenv()


def ler_variavel_ambiente(nome):

    valor = os.getenv(nome, "")

    # Remove espacos e aspas comuns em .env para evitar erro de autenticacao.
    return valor.strip().strip('"').strip("'")


def converter_preco(texto_preco):

    texto_limpo = (texto_preco or "").strip()

    if not texto_limpo.startswith("R$"):

        return None

    numero = texto_limpo.replace("R$", "").strip().replace(".", "").replace(",", ".")

    try:

        return float(numero)

    except ValueError:

        return None


def produto_esta_no_intervalo(produto, preco_minimo, preco_maximo):

    valor = converter_preco(produto.get("depois"))

    if valor is None:

        return False

    if preco_minimo is not None and valor < preco_minimo:

        return False

    return valor <= preco_maximo


def formatar_faixa_preco(preco_minimo, preco_maximo):

    if preco_minimo is None:

        return f"ate R$ {preco_maximo:.2f}"

    return f"entre R$ {preco_minimo:.2f} e R$ {preco_maximo:.2f}"


def carregar_historico_precos(caminho_arquivo):

    historico = {}

    try:

        with open(

            caminho_arquivo,

            "r",

            encoding="utf-8"

        ) as arquivo:

            link_atual = None
            preco_atual = None

            for linha in arquivo:

                linha_limpa = linha.strip()

                if not linha_limpa:

                    continue

                if linha_limpa.lower().startswith("link:"):

                    link_atual = linha_limpa.split(":", 1)[1].strip()

                    continue

                if linha_limpa.lower().startswith("depois:"):

                    preco_atual = converter_preco(
                        linha_limpa.split(":", 1)[1].strip().strip("*")
                    )

                    continue

                if linha_limpa.startswith("-----------------------------"):

                    if link_atual and preco_atual is not None:

                        preco_salvo = historico.get(link_atual)

                        if preco_salvo is None or preco_atual < preco_salvo:

                            historico[link_atual] = preco_atual

                    link_atual = None

                    preco_atual = None

                    continue

            if link_atual and preco_atual is not None:

                preco_salvo = historico.get(link_atual)

                if preco_salvo is None or preco_atual < preco_salvo:

                    historico[link_atual] = preco_atual

    except FileNotFoundError:

        pass

    return historico


def produto_deve_ser_enviado(produto, historico_precos):

    link = produto.get("link")
    preco_novo = converter_preco(produto.get("depois"))

    if not link or preco_novo is None:

        return False

    preco_antigo = historico_precos.get(link)

    if preco_antigo is None:

        return True

    return preco_novo < preco_antigo


def atualizar_historico_precos(historico_precos, produtos):

    for produto in produtos:

        link = produto.get("link")
        preco = converter_preco(produto.get("depois"))

        if not link or preco is None:

            continue

        preco_atual = historico_precos.get(link)

        if preco_atual is None or preco < preco_atual:

            historico_precos[link] = preco

        else:

            historico_precos.setdefault(link, preco_atual)

    return historico_precos


def salvar_produtos_em_arquivo(caminho_arquivo, produtos):

    if not produtos:

        return

    with open(

        caminho_arquivo,

        "a",

        encoding="utf-8"

    ) as arquivo:

        for produto in produtos:

            arquivo.write(

                f"{produto['descricao']}\n\n"
            )

            arquivo.write(

                f"Antes: ~{produto['antes']}~\n"
            )

            arquivo.write(

                f"Depois: *{produto['depois']}*\n"
            )

            arquivo.write(

                f"Desconto: {produto['desconto']}\n\n"
            )

            arquivo.write(

                f"Link: {produto['link']}\n"
            )

            arquivo.write(

                "\n-----------------------------\n\n"
            )


def aplicar_filtro_categoria(page, categoria):

    categoria = categoria.strip()

    if not categoria:

        return

    print(
        f"\nAplicando filtro de categoria: {categoria}"
    )

    page.get_by_text(
        "Filtrar",
        exact=True
    ).click()

    page.locator(
        "div.andes-accordion-header-container__title"
    ).filter(
        has_text="Categorias"
    ).click()

    page.locator(
        "label.andes-radio__label"
    ).filter(
        has_text=categoria
    ).first.click()

    page.get_by_role(
        "button",
        name="Aplicar"
    ).click()

    time.sleep(
        random.uniform(2, 4)
    )


def usuario_esta_logado_mercado_livre(page):

    try:

        if page.get_by_text("Entre", exact=True).count() > 0:

            return False

        if page.get_by_text("Cadastro", exact=True).count() > 0:

            return False

        if page.locator("a[href*='login']").count() > 0:

            return False

    except Exception:

        return False

    return True


def aguardar_login_mercado_livre(page):

    if usuario_esta_logado_mercado_livre(page):

        print(
            "\nMercado Livre ja esta autenticado."
        )

        return

    print(
        "\nMercado Livre nao esta autenticado. Faça login manualmente e depois pressione ENTER."
    )

    input()


def montar_mensagem_produto(produto):

    return (
        f"{produto['descricao']}\n\n"
        f"Antes: {produto['antes']}\n"
        f"Depois: {produto['depois']}\n"
        f"Desconto: {produto['desconto']}\n"
        f"Link: {produto['link']}"
    )


def enviar_produtos_por_whatsapp(produtos):

    if not produtos:

        print(
            "\nNenhum produto para enviar no WhatsApp."
        )

        return

    account_sid = ler_variavel_ambiente("TWILIO_ACCOUNT_SID")
    auth_token = ler_variavel_ambiente("TWILIO_AUTH_TOKEN")
    whatsapp_from = ler_variavel_ambiente("TWILIO_WHATSAPP_FROM")
    whatsapp_to = ler_variavel_ambiente("TWILIO_WHATSAPP_TO")

    variaveis_obrigatorias = {
        "TWILIO_ACCOUNT_SID": account_sid,
        "TWILIO_AUTH_TOKEN": auth_token,
        "TWILIO_WHATSAPP_FROM": whatsapp_from,
        "TWILIO_WHATSAPP_TO": whatsapp_to
    }

    faltantes = [
        nome for nome, valor in variaveis_obrigatorias.items() if not valor
    ]

    if faltantes:

        raise ValueError(
            "Variaveis ausentes no .env: " + ", ".join(faltantes)
        )

    if not account_sid.startswith("AC"):

        raise ValueError(
            "TWILIO_ACCOUNT_SID invalido. Ele deve comecar com 'AC'."
        )

    client = Client(
        account_sid,
        auth_token
    )

    for produto in produtos:

        mensagem = montar_mensagem_produto(produto)

        try:

            resposta = client.messages.create(
                from_=whatsapp_from,
                to=whatsapp_to,
                body=mensagem
            )

        except TwilioRestException as exc:

            if exc.code == 20003:

                raise RuntimeError(
                    "Falha de autenticacao Twilio (20003). Verifique se SID e Auth Token pertencem a mesma conta e se o token nao foi revogado."
                ) from exc

            raise

        print(
            f"\nMensagem enviada para {whatsapp_to}:\n{produto['descricao']}"
        )

        print(
            f"SID Twilio: {resposta.sid}"
        )

        time.sleep(
            random.uniform(3, 5)
        )


def coletar_links_com_desconto(page, url, desconto_minimo, limite):

    print(
        f"\nBuscando produtos em:\n{url}"
    )

    time.sleep(
        random.uniform(3, 5)
    )

    for _ in range(4):

        page.mouse.wheel(0, 2500)

        time.sleep(
            random.uniform(1, 2)
        )

    links_filtrados = page.evaluate(

        """(parametros) => {
            const { descontoMinimo, limite } = parametros;
            const links = [];
            const vistos = new Set();

            const spans = document.querySelectorAll(
                "[data-andes-money-amount-discount='true']"
            );

            for (const span of spans) {
                const texto = (span.textContent || "").trim();
                const encontrado = texto.match(/(\d+)/);

                if (!encontrado) {
                    continue;
                }

                const desconto = Number.parseInt(encontrado[1], 10);

                if (desconto < descontoMinimo) {
                    continue;
                }

                const card = span.closest(
                    "article, li, .ui-search-result, .poly-card, .andes-card"
                );

                if (!card) {
                    continue;
                }

                const ancora = Array.from(card.querySelectorAll("a[href]")).find(
                    (link) => {
                        const href = link.href || "";

                        return href.includes("mercadolivre.com") && !href.includes("/perfil/");
                    }
                );

                if (!ancora || vistos.has(ancora.href)) {
                    continue;
                }

                vistos.add(ancora.href);

                links.push(ancora.href);

                if (links.length === limite) {
                    break;
                }
            }

            return links;
        }""",

        {
            "descontoMinimo": desconto_minimo,
            "limite": limite
        }
    )

    print(
        f"{len(links_filtrados)} links com desconto de {desconto_minimo}% ou mais encontrados."
    )

    return links_filtrados


lista_produtos = []

historico_precos = carregar_historico_precos(
    "produtos.txt"
)


with sync_playwright() as p:

    context = p.chromium.launch_persistent_context(

        user_data_dir="perfil_ml",

        headless=False,

        slow_mo=800,

        locale="pt-BR",

        timezone_id="America/Sao_Paulo",

        viewport={

            "width": 1400,

            "height": 900
        },

        args=[

            "--disable-blink-features=AutomationControlled",

            "--start-maximized",

            "--disable-dev-shm-usage",

            "--no-sandbox"
        ]
    )

    page = context.new_page()

    page.goto(
        URL_LISTAGEM
    )

    aguardar_login_mercado_livre(
        page
    )

    categoria_alvo = CATEGORIA_PADRAO

    aplicar_filtro_categoria(
        page,
        categoria_alvo
    )

    links = coletar_links_com_desconto(
        page,
        URL_LISTAGEM,
        DESCONTO_MINIMO,
        LIMITE_CANDIDATOS
    )

    if not links:

        print(
            "\nNenhum produto com desconto dentro do filtro foi encontrado."
        )

    for link in links:

        if len(lista_produtos) >= LIMITE_PRODUTOS:

            break

        print(
            f"\n=============================="
        )

        print(
            f"LENDO PRODUTO:\n{link}"
        )

        produto = mercado_livre(
            page,
            link
        )

        if produto_esta_no_intervalo(
            produto,
            PRECO_MINIMO,
            PRECO_MAXIMO
        ):

            lista_produtos.append(
                produto
            )

            print(
                f"Produto aceito por estar {formatar_faixa_preco(PRECO_MINIMO, PRECO_MAXIMO)}."
            )

        else:

            print(
                "Produto ignorado por estar fora da faixa de preco."
            )

        time.sleep(
            random.uniform(5, 10)
        )

    produtos_para_enviar = []

    for produto in lista_produtos:

        if produto_deve_ser_enviado(
            produto,
            historico_precos
        ):

            produtos_para_enviar.append(
                produto
            )

            print(
                f"\nProduto liberado para envio por ter menor preco que o historico:\n{produto['link']}"
            )

            continue

        print(
            f"\nProduto ignorado por ja existir no historico com preco menor ou igual:\n{produto['link']}"
        )

    print(
        "\nDigite o número de WhatsApp no formato internacional, somente números. Ex.: 5511999999999"
    )

    telefone_whatsapp = input().strip()

    enviar_produtos_por_whatsapp(
        produtos_para_enviar
    )

    atualizar_historico_precos(
        historico_precos,
        produtos_para_enviar
    )

    salvar_produtos_em_arquivo(
        "produtos.txt",
        produtos_para_enviar
    )

    context.close()

print(

    "\nEnvio pelo WhatsApp finalizado com sucesso!"
)