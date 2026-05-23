from playwright.sync_api import sync_playwright

from parsers.mercadolivre import (
    buscar_produto_por_descricao,
    coletar_produtos_com_desconto,
    obter_link_encurtado_por_descricao,
    processar_produtos_hub_por_html,
    processar_ofertas_relampago,
    salvar_resultado_hub,
    salvar_resultado_relampago,
)

import argparse
import ast
import os
import random
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

URL_LISTAGEM = "https://www.mercadolivre.com.br/afiliados/hub"

URL_OFERTAS_RELAMPAGO = (
    "https://www.mercadolivre.com.br/ofertas"
    "?promotion_type=lightning"
    "#filter_applied=promotion_type&filter_position=3&origin=qcat"
)

DESCONTO_MINIMO = 30

PRECO_MINIMO = None

PRECO_MAXIMO = 400

LIMITE_PRODUTOS = 5

LIMITE_CANDIDATOS = 50

LIMITE_VALIDOS_RELAMPAGO_PADRAO = 10

PRECO_MAXIMO_RELAMPAGO_PADRAO = 400

DESCONTO_MINIMO_RELAMPAGO_PADRAO = 30

LIMITE_PAGINAS_PESQUISA_PADRAO = 5

CATEGORIA_PADRAO = "Acessórios para Veículos"

HISTORICO_ANUNCIOS_ARQUIVO = "historico_anuncios.txt"

ARQUIVO_PRODUTOS_PREFIXO = "ofertas_consolidadas"

WHATSAPP_DESTINO_FIXO = "whatsapp:+5519991133269"

DEBUG_BREAKPOINTS = os.getenv("ENABLE_DEBUG_BREAKPOINTS", "0") == "1"
DEBUG_BREAKPOINT_TARGET = os.getenv("DEBUG_BREAKPOINT_TARGET", "").strip()

load_dotenv()



def parse_args():

    parser = argparse.ArgumentParser(
        description="Executa a coleta de ofertas do Mercado Livre."
    )

    parser.add_argument(
        "--categoria",
        default=None,
        help="Categoria do Mercado Livre a filtrar na coleta principal.",
    )

    parser.add_argument(
        "--preco-maximo",
        type=float,
        default=PRECO_MAXIMO,
        help="Preço máximo aceito para os produtos.",
    )

    parser.add_argument(
        "--preco-minimo",
        type=float,
        default=PRECO_MINIMO,
        help="Preço mínimo aceito para os produtos.",
    )

    parser.add_argument(
        "--menor-preco",
        action="store_true",
        help="Prioriza o produto com menor preço dentro dos resultados encontrados.",
    )

    parser.add_argument(
        "--descricao-produto",
        default=None,
        help=(
            "Ativa busca manual por descrição na pesquisa genérica do Mercado Livre "
            "e retorna um candidato com link de afiliado."
        ),
    )

    parser.add_argument(
        "--limite-paginas-pesquisa",
        type=int,
        default=LIMITE_PAGINAS_PESQUISA_PADRAO,
        help="Quantidade de páginas da pesquisa genérica para analisar na busca manual.",
    )

    parser.add_argument(
        "--limite-produtos",
        type=int,
        default=LIMITE_PRODUTOS,
        help="Quantidade máxima de produtos aceitos por execução.",
    )

    parser.add_argument(
        "--limite-candidatos",
        type=int,
        default=LIMITE_CANDIDATOS,
        help="Quantidade máxima de candidatos buscados por tentativa.",
    )

    parser.add_argument(
        "--desconto-minimo",
        type=int,
        default=DESCONTO_MINIMO,
        help="Desconto mínimo aceito na coleta principal e no fluxo relâmpago.",
    )

    parser.add_argument(
        "--somente-relampago",
        action="store_true",
        help="Ignora o hub/Twilio e executa apenas o fluxo de ofertas relâmpago.",
    )

    parser.add_argument(
        "--relampago-padrao",
        action="store_true",
        help=(
            "Executa somente ofertas relâmpago no modo padrão: todas as categorias, "
            "preço máximo R$ 400, desconto mínimo 30% e até 10 anúncios inéditos."
        ),
    )

    parser.add_argument(
        "--produto-por-html",
        action="store_true",
        help=(
            "Executa o fluxo de produto via HTML salvo do hub de afiliados, "
            "aplicando os filtros passados por parâmetros."
        ),
    )

    parser.add_argument(
        "--pasta-saida",
        default=None,
        help="Diretório onde o arquivo lista_anuncios.txt será salvo (escolhido pelo usuário na interface).",
    )

    return parser.parse_args()


ARGS = parse_args()

RAW_ARGS = sys.argv[1:]
ARG_CATEGORIA_INFORMADA = "--categoria" in RAW_ARGS
ARG_PRECO_MAXIMO_INFORMADO = "--preco-maximo" in RAW_ARGS
ARG_PRECO_MINIMO_INFORMADO = "--preco-minimo" in RAW_ARGS
ARG_DESCONTO_MINIMO_INFORMADO = "--desconto-minimo" in RAW_ARGS
ARG_LIMITE_CANDIDATOS_INFORMADO = "--limite-candidatos" in RAW_ARGS

MODO_SOMENTE_RELAMPAGO = ARGS.somente_relampago or os.getenv("RUN_ONLY_RELAMPAGO", "0") == "1"
MODO_RELAMPAGO_PADRAO = ARGS.relampago_padrao
MODO_BUSCA_DESCRICAO = bool((ARGS.descricao_produto or "").strip())
MODO_PRODUTO_POR_HTML = ARGS.produto_por_html
PRIORIZAR_MENOR_PRECO = ARGS.menor_preco or MODO_BUSCA_DESCRICAO
LIMITE_PAGINAS_PESQUISA = max(1, ARGS.limite_paginas_pesquisa)

if ARGS.categoria:
    CATEGORIA_PADRAO = ARGS.categoria.strip()

PRECO_MINIMO = ARGS.preco_minimo
PRECO_MAXIMO = ARGS.preco_maximo
LIMITE_PRODUTOS = ARGS.limite_produtos
LIMITE_CANDIDATOS = ARGS.limite_candidatos
DESCONTO_MINIMO = ARGS.desconto_minimo

if MODO_RELAMPAGO_PADRAO:

    MODO_SOMENTE_RELAMPAGO = True
    CATEGORIA_PADRAO = ""
    PRECO_MINIMO = None
    PRECO_MAXIMO = PRECO_MAXIMO_RELAMPAGO_PADRAO
    DESCONTO_MINIMO = DESCONTO_MINIMO_RELAMPAGO_PADRAO
    LIMITE_CANDIDATOS = None


def debug_pausa(rotulo):

    if DEBUG_BREAKPOINTS:

        print(f"\n[DEBUG] {rotulo}")

        if not DEBUG_BREAKPOINT_TARGET or DEBUG_BREAKPOINT_TARGET == rotulo:

            breakpoint()

    return


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


def normalizar_descricao(texto_descricao):

    return " ".join((texto_descricao or "").split()).strip()


def normalizar_chave_historico(valor):

    return " ".join((valor or "").split()).strip().lower()


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
            descricao_atual = None

            for linha in arquivo:

                linha_limpa = linha.strip()

                if not linha_limpa:

                    continue

                if linha_limpa.lower().startswith("link:"):

                    link_atual = linha_limpa.split(":", 1)[1].strip()

                    continue

                if linha_limpa.lower().startswith("antes:"):

                    continue

                if linha_limpa.lower().startswith("depois:"):

                    preco_atual = converter_preco(
                        linha_limpa.split(":", 1)[1].strip().strip("*")
                    )

                    continue

                if linha_limpa.startswith("-----------------------------"):

                    if descricao_atual and preco_atual is not None:

                        chave_descricao = normalizar_descricao(descricao_atual)
                        preco_salvo = historico.get(chave_descricao)

                        if preco_salvo is None or preco_atual < preco_salvo:

                            historico[chave_descricao] = preco_atual

                    link_atual = None

                    preco_atual = None

                    descricao_atual = None

                    continue

                if descricao_atual is None:

                    descricao_atual = linha_limpa

            if descricao_atual and preco_atual is not None:

                chave_descricao = normalizar_descricao(descricao_atual)
                preco_salvo = historico.get(chave_descricao)

                if preco_salvo is None or preco_atual < preco_salvo:

                    historico[chave_descricao] = preco_atual

    except FileNotFoundError:

        pass

    return historico


def carregar_historico_anuncios(caminho_arquivo):

    historico = set()

    try:

        with open(caminho_arquivo, "r", encoding="utf-8") as arquivo:

            for linha in arquivo:

                linha_limpa = linha.strip()

                if not linha_limpa:

                    continue

                try:

                    anuncio = ast.literal_eval(linha_limpa)

                except Exception:

                    continue

                if isinstance(anuncio, tuple) and anuncio:

                    anuncio_id = normalizar_chave_historico(str(anuncio[0]))

                    if anuncio_id:

                        historico.add(anuncio_id)

    except FileNotFoundError:

        pass

    return historico


def carregar_historico_precos_por_anuncio(caminho_arquivo):

    historico = {}

    try:

        with open(caminho_arquivo, "r", encoding="utf-8") as arquivo:

            for linha in arquivo:

                linha_limpa = linha.strip()
                if not linha_limpa:
                    continue

                try:
                    anuncio = ast.literal_eval(linha_limpa)
                except Exception:
                    continue

                if not isinstance(anuncio, tuple) or len(anuncio) < 4:
                    continue

                anuncio_id = normalizar_chave_historico(str(anuncio[0]))
                preco_atual = converter_preco(str(anuncio[3]))

                if not anuncio_id or preco_atual is None:
                    continue

                preco_salvo = historico.get(anuncio_id)
                if preco_salvo is None or preco_atual < preco_salvo:
                    historico[anuncio_id] = preco_atual

    except FileNotFoundError:

        pass

    return historico


def filtrar_anuncios_ineditos_ou_com_reducao(produtos, historico_precos_por_anuncio):

    aprovados = []

    for produto in produtos:

        anuncio_id = normalizar_chave_historico(produto.get("id_anuncio"))
        preco_atual = converter_preco(produto.get("depois"))

        if not anuncio_id or preco_atual is None:
            continue

        preco_historico = historico_precos_por_anuncio.get(anuncio_id)

        if preco_historico is not None and preco_atual >= preco_historico:
            print(
                f"[IGNORADO] Anúncio {anuncio_id} já foi usado antes com preço melhor ou igual. Atual: {preco_atual:.2f} | histórico: {preco_historico:.2f}"
            )
            continue

        historico_precos_por_anuncio[anuncio_id] = preco_atual
        aprovados.append(produto)

    return aprovados


def produto_ja_foi_enviado(produto, historico_anuncios):

    anuncio_id = normalizar_chave_historico(
        produto.get("id_anuncio")
    )

    if not anuncio_id:

        return False

    return anuncio_id in historico_anuncios


def montar_tupla_anuncio(produto):

    return (
        normalizar_chave_historico(produto.get("id_anuncio")),
        normalizar_descricao(produto.get("descricao")),
        (produto.get("antes") or "").strip(),
        (produto.get("depois") or "").strip(),
        (produto.get("desconto") or "").strip(),
        (produto.get("link_original") or produto.get("link") or "").strip(),
    )


def produto_deve_ser_enviado(produto, historico_precos):

    descricao = normalizar_descricao(produto.get("descricao"))
    preco_novo = converter_preco(produto.get("depois"))

    if not descricao or preco_novo is None:

        return False

    preco_antigo = historico_precos.get(descricao)

    if preco_antigo is None:

        return True

    return preco_novo < preco_antigo


def atualizar_historico_precos(historico_precos, produtos):

    for produto in produtos:

        descricao = normalizar_descricao(produto.get("descricao"))
        preco = converter_preco(produto.get("depois"))

        if not descricao or preco is None:

            continue

        preco_atual = historico_precos.get(descricao)

        if preco_atual is None or preco < preco_atual:

            historico_precos[descricao] = preco

        else:

            historico_precos.setdefault(descricao, preco_atual)

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


def montar_nome_arquivo_produtos():

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return f"{ARQUIVO_PRODUTOS_PREFIXO}_{timestamp}.txt"


def salvar_historico_anuncios_em_arquivo(caminho_arquivo, produtos):

    if not produtos:

        return

    with open(
        caminho_arquivo,
        "a",
        encoding="utf-8"
    ) as arquivo:

        for produto in produtos:

            arquivo.write(f"{montar_tupla_anuncio(produto)!r}\n")


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


def validar_txt_e_historico(caminho_arquivo):

    debug_pausa("Antes de ler o historico do TXT")

    historico = carregar_historico_precos(caminho_arquivo)

    debug_pausa("Depois de ler o historico do TXT")

    return historico


def usuario_esta_logado_mercado_livre(page):

    try:

        if "login" in (page.url or "").lower():

            return False

        if page.locator("button[aria-label*='menu'], button:has-text('menu')").count() > 0:

            return True

        if page.get_by_role("link", name="Entre").first.is_visible():

            return False

        if page.get_by_role("link", name="Crie a sua conta").first.is_visible():

            return False

        if page.locator("a[href*='login']").first.is_visible():

            return False

        if page.locator("button:has-text('Lucas, menu')").count() > 0:

            return True

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
        "\nMercado Livre nao esta autenticado. Faça login manualmente no navegador aberto."
    )

    timeout_segundos = 180
    inicio_espera = time.time()

    while (time.time() - inicio_espera) < timeout_segundos:

        if usuario_esta_logado_mercado_livre(page):

            print("\nLogin confirmado. Continuando execução.")
            return

        time.sleep(2)

    raise RuntimeError(
        "Sessao do Mercado Livre nao autenticada apos aguardar 180s. "
        "Entre na conta e execute novamente."
    )


def montar_mensagem_produto(produto):

    return (
        f"{produto['descricao']}\n\n"
        f"Antes: {produto['antes']}\n"
        f"Depois: {produto['depois']}\n"
        f"Desconto: {produto['desconto']}\n"
        f"Link: {produto['link']}"
    )


def registrar_produto_ignorado(produto, motivo, detalhe=""):

    print(
        f"\n[PRODUTO IGNORADO] {produto.get('descricao', 'Descrição não encontrada')}"
    )

    print(
        f"Motivo: {motivo}"
    )

    if detalhe:

        print(
            f"Detalhe: {detalhe}"
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
    whatsapp_to = WHATSAPP_DESTINO_FIXO

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

    print(
        f"\n[DEBUG] Twilio Account SID: {account_sid[:4]}...{account_sid[-4:]}"
    )

    for produto in produtos:

        mensagem = montar_mensagem_produto(produto)
        # Teste sem imagem: o envio fica somente no texto da mensagem.
        # imagem = (produto.get("imagem") or "").strip()
        parametros_envio = {
            "from_": whatsapp_from,
            "to": whatsapp_to,
            "body": mensagem,
        }

        # Comentado para testar se a mídia estava afetando o envio no Twilio.
        # if imagem.startswith("http://") or imagem.startswith("https://"):
        #
        #     # O Twilio usa media_url para enviar a imagem junto com a mensagem.
        #     parametros_envio["media_url"] = [imagem]

        # print(
        #     f"\n[DEBUG] media_url={'SIM' if 'media_url' in parametros_envio else 'NAO'}"
        # )

        # print(
        #     f"[DEBUG] imagem={imagem if imagem else 'SEM IMAGEM'}"
        # )

        debug_pausa("Antes de enviar para a API do Twilio")

        try:

            resposta = client.messages.create(**parametros_envio)

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
            f"Message SID Twilio: {resposta.sid}"
        )

        time.sleep(
            random.uniform(3, 5)
        )


def coletar_links_com_desconto(page, url, desconto_minimo, limite):

    print(
        f"\nBuscando produtos em:\n{url}"
    )

    debug_pausa("Antes de procurar os produtos no hub")

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

produtos_para_enviar = []

historico_precos = validar_txt_e_historico(
    "produtos.txt"
)

historico_anuncios = carregar_historico_anuncios(
    HISTORICO_ANUNCIOS_ARQUIVO
)

historico_precos_por_anuncio = carregar_historico_precos_por_anuncio(
    HISTORICO_ANUNCIOS_ARQUIVO
)

categoria_parametrizada = (ARGS.categoria or "").strip() if ARG_CATEGORIA_INFORMADA else None
preco_minimo_parametrizado = PRECO_MINIMO if ARG_PRECO_MINIMO_INFORMADO else None
preco_maximo_parametrizado = PRECO_MAXIMO if ARG_PRECO_MAXIMO_INFORMADO else None
desconto_minimo_parametrizado = DESCONTO_MINIMO if ARG_DESCONTO_MINIMO_INFORMADO else None
limite_candidatos_parametrizado = LIMITE_CANDIDATOS if ARG_LIMITE_CANDIDATOS_INFORMADO else None


_FROZEN = getattr(sys, "frozen", False)

_LAUNCH_KWARGS = dict(
    user_data_dir="perfil_ml",
    headless=False,
    slow_mo=800,
    locale="pt-BR",
    timezone_id="America/Sao_Paulo",
    viewport={"width": 1400, "height": 900},
    args=[
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ],
)

if _FROZEN:
    _LAUNCH_KWARGS["channel"] = "chrome"

with sync_playwright() as p:

    context = p.chromium.launch_persistent_context(**_LAUNCH_KWARGS)

    page = context.new_page()

    page.goto(
        URL_LISTAGEM
    )

    debug_pausa("Navegador aberto e hub carregado")

    aguardar_login_mercado_livre(
        page
    )

    debug_pausa("Depois da validacao de login do Mercado Livre")

    if MODO_PRODUTO_POR_HTML:

        print("\nModo produto por HTML ativado. Fluxos antigos de hub/Twilio e relâmpago serão ignorados.")

        ofertas_hub = processar_produtos_hub_por_html(
            page,
            URL_LISTAGEM,
            desconto_minimo=desconto_minimo_parametrizado,
            categoria=categoria_parametrizada,
            preco_minimo=preco_minimo_parametrizado,
            preco_maximo=preco_maximo_parametrizado,
            descricao=(ARGS.descricao_produto or "").strip() or None,
            limite_candidatos=limite_candidatos_parametrizado,
            historico_anuncios=historico_anuncios,
            limite_validos=10,
        )

        ofertas_hub = filtrar_anuncios_ineditos_ou_com_reducao(
            ofertas_hub,
            historico_precos_por_anuncio,
        )

        if ofertas_hub:

            salvar_resultado_hub(ofertas_hub)

            salvar_historico_anuncios_em_arquivo(
                HISTORICO_ANUNCIOS_ARQUIVO,
                ofertas_hub
            )

            for produto in ofertas_hub:

                anuncio_id = normalizar_chave_historico(
                    produto.get("id_anuncio")
                )

                if anuncio_id:

                    historico_anuncios.add(anuncio_id)

            print(f"\n{len(ofertas_hub)} oferta(s) do hub processada(s) e salva(s).")

        else:

            print("\nNenhuma oferta elegível do hub foi encontrada.")

        context.close()

        raise SystemExit(0)

    if MODO_BUSCA_DESCRICAO:

        print("\nModo manual por descrição ativado. Hub/Twilio e fluxo relâmpago serão ignorados.")

        produto_manual = buscar_produto_por_descricao(
            page,
            descricao=(ARGS.descricao_produto or ""),
            preco_minimo=PRECO_MINIMO,
            preco_maximo=PRECO_MAXIMO,
            menor_preco=PRIORIZAR_MENOR_PRECO,
            limite_paginas=LIMITE_PAGINAS_PESQUISA,
            historico_anuncios=historico_anuncios,
        )

        if produto_manual:

            salvar_resultado_relampago([produto_manual])

            salvar_historico_anuncios_em_arquivo(
                HISTORICO_ANUNCIOS_ARQUIVO,
                [produto_manual]
            )

            anuncio_id = normalizar_chave_historico(
                produto_manual.get("id_anuncio")
            )

            if anuncio_id:

                historico_anuncios.add(anuncio_id)

            print("\nBusca manual concluída com sucesso.")

        else:

            print("\nBusca manual não encontrou candidato válido.")

        context.close()

        raise SystemExit(0)

    if not MODO_SOMENTE_RELAMPAGO:

        categoria_alvo = CATEGORIA_PADRAO

        debug_pausa("Antes de aplicar o filtro de categoria")

        aplicar_filtro_categoria(
            page,
            categoria_alvo
        )

        debug_pausa("Depois de aplicar o filtro de categoria")

        produtos_processados = set()
        tentativas = 0
        tentativas_max = 20

        while len(produtos_para_enviar) < LIMITE_PRODUTOS and tentativas < tentativas_max:

            tentativas += 1

            print(
                f"\n[Tentativa {tentativas}/{tentativas_max}] Coletando mais produtos..."
            )

            produtos = coletar_produtos_com_desconto(
                page,
                URL_LISTAGEM,
                DESCONTO_MINIMO,
                LIMITE_CANDIDATOS
            )

            debug_pausa("Depois de coletar os produtos candidatos")

            if not produtos:

                print(
                    "\nNenhum novo produto com desconto dentro do filtro foi encontrado."
                )

                break

            produtos = sorted(
                produtos,
                key=lambda produto: not produto.get("oferta_imperdivel", False)
            )

            ofertas_imperdiveis = sum(
                1 for produto in produtos if produto.get("oferta_imperdivel", False)
            )

            print(
                f"{ofertas_imperdiveis} produto(s) com marcador 'OFERTA IMPERDÍVEL' priorizados nesta tentativa."
            )

            novos_na_tentativa = 0

            for produto in produtos:

                chave_produto = f"{normalizar_descricao(produto.get('descricao'))}|{(produto.get('depois') or '').strip()}"

                if not chave_produto or chave_produto in produtos_processados:

                    continue

                produtos_processados.add(chave_produto)
                novos_na_tentativa += 1

                if len(produtos_para_enviar) >= LIMITE_PRODUTOS:

                    break

                print(
                    f"\n=============================="
                )

                print(
                    f"LENDO PRODUTO:\n{produto.get('descricao', 'Descrição não encontrada')}"
                )

                debug_pausa("Depois de validar os dados do card")

                if produto_esta_no_intervalo(
                    produto,
                    PRECO_MINIMO,
                    PRECO_MAXIMO
                ):

                    debug_pausa(
                        "Produto encontrado com mais de 40% de desconto e ate R$ 300"
                    )

                    debug_pausa("Antes de comparar com o historico do TXT")

                    if not produto_deve_ser_enviado(
                        produto,
                        historico_precos
                    ):

                        preco_novo = converter_preco(produto.get("depois"))
                        preco_antigo = historico_precos.get(normalizar_descricao(produto.get("descricao")))

                        registrar_produto_ignorado(
                            produto,
                            "Já existe no histórico com preço menor ou igual",
                            f"Preço novo: {preco_novo:.2f} | preço no histórico: {preco_antigo:.2f}" if preco_novo is not None and preco_antigo is not None else "Não foi possível comparar os preços"
                        )

                        time.sleep(
                            random.uniform(2, 4)
                        )

                        continue

                    produto["link_original"] = produto.get("link", "")

                    produto["link"] = obter_link_encurtado_por_descricao(
                        page,
                        produto.get("descricao", ""),
                        produto.get("link_original", "")
                    )

                    if produto_ja_foi_enviado(
                        produto,
                        historico_anuncios
                    ):

                        registrar_produto_ignorado(
                            produto,
                            "Já existe no histórico de anúncios",
                            f"ID do anúncio: {produto.get('id_anuncio', '')}"
                        )

                        time.sleep(
                            random.uniform(2, 4)
                        )

                        continue

                    lista_produtos.append(
                        produto
                    )

                    produtos_para_enviar.append(
                        produto
                    )

                    print(
                        f"Produto aceito por estar {formatar_faixa_preco(PRECO_MINIMO, PRECO_MAXIMO)} e ser elegivel no historico."
                    )

                else:

                    registrar_produto_ignorado(
                        produto,
                        "Fora da faixa de preço",
                        f"Preço atual: {produto.get('depois', 'indisponível')} | limite máximo: R$ {PRECO_MAXIMO:.2f}"
                    )

                time.sleep(
                    random.uniform(5, 10)
                )

            if novos_na_tentativa == 0:

                print(
                    "\nNenhum novo produto inedito nesta tentativa. Encerrando busca para evitar loop."
                )

                break

            page.mouse.wheel(0, 3000)

            time.sleep(
                random.uniform(2, 4)
            )

        if len(produtos_para_enviar) < LIMITE_PRODUTOS:

            print(
                f"\nForam encontrados {len(produtos_para_enviar)} produtos elegiveis para envio apos validacao de historico."
            )

        debug_pausa("Antes de enviar os produtos aprovados para o Twilio")

        enviar_produtos_por_whatsapp(
            produtos_para_enviar
        )

        debug_pausa("Antes de gravar as novas informacoes no TXT")

        atualizar_historico_precos(
            historico_precos,
            produtos_para_enviar
        )

        salvar_produtos_em_arquivo(
            montar_nome_arquivo_produtos(),
            produtos_para_enviar
        )

        salvar_historico_anuncios_em_arquivo(
            HISTORICO_ANUNCIOS_ARQUIVO,
            produtos_para_enviar
        )

        for produto in produtos_para_enviar:

            anuncio_id = normalizar_chave_historico(
                produto.get("id_anuncio")
            )

            if anuncio_id:

                historico_anuncios.add(anuncio_id)

        debug_pausa("Depois de gravar as informacoes novas no TXT")

    else:

        print("\nModo somente ofertas relâmpago ativado. Fluxo do hub/Twilio foi ignorado.")

    # =========================================================================
    # NOVO FLUXO: Ofertas Relâmpago
    # =========================================================================

    debug_pausa("Iniciando fluxo de ofertas relâmpago")

    modo_relampago_sem_parametros = (
        categoria_parametrizada is None
        and preco_minimo_parametrizado is None
        and preco_maximo_parametrizado is None
        and desconto_minimo_parametrizado is None
        and limite_candidatos_parametrizado is None
    )

    limite_validos_extraidos = LIMITE_VALIDOS_RELAMPAGO_PADRAO

    ofertas_relampago = processar_ofertas_relampago(
        page,
        URL_OFERTAS_RELAMPAGO,
        desconto_minimo=DESCONTO_MINIMO_RELAMPAGO_PADRAO if MODO_RELAMPAGO_PADRAO else desconto_minimo_parametrizado,
        categoria=None if MODO_RELAMPAGO_PADRAO else categoria_parametrizada,
        preco_minimo=None if MODO_RELAMPAGO_PADRAO else preco_minimo_parametrizado,
        preco_maximo=PRECO_MAXIMO_RELAMPAGO_PADRAO if MODO_RELAMPAGO_PADRAO else preco_maximo_parametrizado,
        limite_candidatos=limite_candidatos_parametrizado,
        historico_anuncios=historico_anuncios,
        ids_descartados=historico_anuncios if modo_relampago_sem_parametros else None,
        limite_validos=limite_validos_extraidos,
        forcar_modo_incremental=(MODO_RELAMPAGO_PADRAO or modo_relampago_sem_parametros),
        max_paginas_incremental=2 if MODO_RELAMPAGO_PADRAO else None,
    )

    ofertas_relampago = filtrar_anuncios_ineditos_ou_com_reducao(
        ofertas_relampago,
        historico_precos_por_anuncio,
    )

    if len(ofertas_relampago) > LIMITE_VALIDOS_RELAMPAGO_PADRAO:
        ofertas_relampago = ofertas_relampago[:LIMITE_VALIDOS_RELAMPAGO_PADRAO]

    if ofertas_relampago:

        salvar_resultado_relampago(ofertas_relampago, pasta=ARGS.pasta_saida or None)

        salvar_historico_anuncios_em_arquivo(
            HISTORICO_ANUNCIOS_ARQUIVO,
            ofertas_relampago
        )

        for produto in ofertas_relampago:

            anuncio_id = normalizar_chave_historico(
                produto.get("id_anuncio")
            )

            if anuncio_id:

                historico_anuncios.add(anuncio_id)

        print(
            f"\n{len(ofertas_relampago)} oferta(s) relâmpago processada(s) e salvas."
        )

    else:

        print(
            "\nNenhuma oferta relâmpago elegível foi encontrada nesta execução."
        )

    debug_pausa("Fluxo de ofertas relâmpago concluído")

    context.close()

print(

    "\nEnvio pelo WhatsApp finalizado com sucesso!"
)