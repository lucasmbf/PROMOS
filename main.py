from playwright.sync_api import sync_playwright

from parsers.mercadolivre import (
    coletar_produtos_com_desconto,
    obter_link_encurtado_por_descricao,
    processar_ofertas_relampago,
    salvar_resultado_relampago,
)

import argparse
import ast
import os
import random
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

    return parser.parse_args()


ARGS = parse_args()

MODO_SOMENTE_RELAMPAGO = ARGS.somente_relampago or os.getenv("RUN_ONLY_RELAMPAGO", "0") == "1"

if ARGS.categoria:
    CATEGORIA_PADRAO = ARGS.categoria.strip()

PRECO_MINIMO = ARGS.preco_minimo
PRECO_MAXIMO = ARGS.preco_maximo
LIMITE_PRODUTOS = ARGS.limite_produtos
LIMITE_CANDIDATOS = ARGS.limite_candidatos
DESCONTO_MINIMO = ARGS.desconto_minimo


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

    debug_pausa("Navegador aberto e hub carregado")

    aguardar_login_mercado_livre(
        page
    )

    debug_pausa("Depois da validacao de login do Mercado Livre")

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

    ofertas_relampago = processar_ofertas_relampago(
        page,
        URL_OFERTAS_RELAMPAGO,
        desconto_minimo=DESCONTO_MINIMO,
        categoria=CATEGORIA_PADRAO,
        preco_minimo=PRECO_MINIMO,
        preco_maximo=PRECO_MAXIMO,
        limite_candidatos=LIMITE_CANDIDATOS,
    )

    if ofertas_relampago:

        salvar_resultado_relampago(ofertas_relampago)

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