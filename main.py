from playwright.sync_api import sync_playwright

from parsers.mercadolivre import (
    buscar_produto_por_descricao,
    coletar_produtos_com_desconto,
    obter_link_encurtado_por_descricao,
    processar_produtos_home_por_pesquisa,
    processar_ofertas_relampago,
    salvar_saida_execucao_modalidade,
    salvar_resultado_relampago,
    salvar_resultado_relampago_json,
    salvar_resultado_produto_json,
    salvar_saida_execucao_modalidade_json,
)

import argparse
import ast
import json
import mimetypes
import os
import pdb
import random
import re
import sys
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path
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

LIMITE_PAGINAS_PESQUISA_PADRAO = 15

CATEGORIA_PADRAO = "Acessórios para Veículos"

HISTORICO_ANUNCIOS_ARQUIVO = "historico_anuncios.txt"
HISTORICO_RETENCAO_DIAS = 20

ARQUIVO_PRODUTOS_PREFIXO = "ofertas_consolidadas"

WHATSAPP_DESTINO_FIXO = "whatsapp:+5519991133269"

AUTH_MARKER_REQUIRED_ML = "[AUTH_REQUIRED_ML]"
AUTH_MARKER_STILL_PENDING_ML = "[AUTH_STILL_PENDING_ML]"
LOGIN_OK_SIGNAL_FILE = os.path.join(os.path.dirname(__file__), ".ml_login_ok.signal")
MODO_INTERFACE = os.getenv("PROMOS_GUI_MODE", "0") == "1"

DEBUG_BREAKPOINTS = os.getenv("ENABLE_DEBUG_BREAKPOINTS", "0") == "1"
DEBUG_BREAKPOINT_TARGET = os.getenv("DEBUG_BREAKPOINT_TARGET", "").strip()

load_dotenv()

TWILIO_STATUS_CHECK_TENTATIVAS = 1
TWILIO_STATUS_CHECK_INTERVALO_SEGUNDOS = 1
TWILIO_FORCAR_TEXTO_SOMENTE = os.getenv("TWILIO_FORCAR_TEXTO_SOMENTE", "0") == "1"
TWILIO_ENVIAR_MIDIA_WEBP = os.getenv("TWILIO_ENVIAR_MIDIA_WEBP", "0") == "1"
TWILIO_PAUSA_ENTRE_ENVIOS_SEGUNDOS = (0.2, 0.6)
TWILIO_USAR_GOOGLE_DRIVE_IMAGENS = os.getenv("TWILIO_USAR_GOOGLE_DRIVE_IMAGENS", "0") == "1"
GOOGLE_DRIVE_IMAGENS_FOLDER_ID = os.getenv("GOOGLE_DRIVE_IMAGENS_FOLDER_ID", "").strip()
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE",
    "credentials/google-service-account.json",
).strip()

BASE_DIR = Path(__file__).resolve().parent
PASTA_IMAGENS_ANUNCIOS = BASE_DIR / "dist-interface" / "instagram_anuncios"
ARQUIVO_CACHE_DRIVE_IMAGENS = BASE_DIR / "integracao_drive_imagens_cache.json"



def parse_args():

    parser = argparse.ArgumentParser(
        description="Executa a coleta de ofertas do Mercado Livre."
    )

    parser.add_argument(
        "--categoria",
        default=None,
        help="Categoria principal a filtrar na coleta.",
    )

    parser.add_argument(
        "--fonte",
        choices=["mercadolivre"],
        default="mercadolivre",
        help="Fonte do marketplace para busca de produtos on-demand.",
    )

    parser.add_argument(
        "--categoria-id",
        default=None,
        help="ID da categoria principal do Mercado Livre (ex.: MLB1055).",
    )

    parser.add_argument(
        "--subcategoria-id",
        default=None,
        help="ID da subcategoria do Mercado Livre (ex.: MLB1743).",
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
        "--url-produto",
        action="append",
        default=None,
        help=(
            "URL direta de produto para priorizar na busca do hub. "
            "Pode ser informado ate 5 vezes."
        ),
    )

    parser.add_argument(
        "--limite-paginas-pesquisa",
        type=int,
        default=LIMITE_PAGINAS_PESQUISA_PADRAO,
        help="Quantidade maxima de paginas a analisar na busca de produtos (links diretos e pesquisa generica).",
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
            "Executa o fluxo de procurar produto pela pesquisa da home do Mercado Livre, "
            "aplicando os filtros passados por parâmetros."
        ),
    )

    parser.add_argument(
        "--url-relampago",
        default=None,
        help="URL customizada para o fluxo de ofertas relampago do Mercado Livre.",
    )

    parser.add_argument(
        "--pasta-saida",
        default=None,
        help="Diretório onde o arquivo lista_anuncios.txt será salvo (escolhido pelo usuário na interface).",
    )
    parser.add_argument(
        "--modalidade-execucao",
        choices=["alerta", "campanha", "ondemand"],
        default=None,
        help="Origem da execucao para gravacao consolidada por modalidade.",
    )
    parser.add_argument(
        "--mensagem-complementar",
        default=None,
        help="Texto complementar enviado em negrito antes do texto padrao do anuncio.",
    )

    return parser.parse_args()


ARGS = parse_args()

RAW_ARGS = sys.argv[1:]
ARG_CATEGORIA_INFORMADA = "--categoria" in RAW_ARGS
ARG_CATEGORIA_ID_INFORMADA = "--categoria-id" in RAW_ARGS
ARG_SUBCATEGORIA_ID_INFORMADA = "--subcategoria-id" in RAW_ARGS
ARG_PRECO_MAXIMO_INFORMADO = "--preco-maximo" in RAW_ARGS
ARG_PRECO_MINIMO_INFORMADO = "--preco-minimo" in RAW_ARGS
ARG_DESCONTO_MINIMO_INFORMADO = "--desconto-minimo" in RAW_ARGS
ARG_LIMITE_CANDIDATOS_INFORMADO = "--limite-candidatos" in RAW_ARGS
ARG_DESCRICAO_PRODUTO_INFORMADA = "--descricao-produto" in RAW_ARGS
ARG_URL_PRODUTO_INFORMADA = "--url-produto" in RAW_ARGS

MODO_SOMENTE_RELAMPAGO = ARGS.somente_relampago or os.getenv("RUN_ONLY_RELAMPAGO", "0") == "1"
MODO_RELAMPAGO_PADRAO = ARGS.relampago_padrao
MODO_BUSCA_DESCRICAO = bool((ARGS.descricao_produto or "").strip())
MODO_PRODUTO_POR_HTML = ARGS.produto_por_html
PRIORIZAR_MENOR_PRECO = ARGS.menor_preco or MODO_BUSCA_DESCRICAO
LIMITE_PAGINAS_PESQUISA = max(1, ARGS.limite_paginas_pesquisa)
FONTE_BUSCA = (ARGS.fonte or "mercadolivre").strip().lower()
URL_RELAMPAGO_ALVO = (ARGS.url_relampago or "").strip() or URL_OFERTAS_RELAMPAGO
MENSAGEM_COMPLEMENTAR = (ARGS.mensagem_complementar or "").strip()

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

            pdb.set_trace()

    return


def ler_variavel_ambiente(nome):

    valor = os.getenv(nome, "")

    # Remove espacos e aspas comuns em .env para evitar erro de autenticacao.
    return valor.strip().strip('"').strip("'")


def _normalizar_id_anuncio(valor):

    return "".join(
        caractere for caractere in str(valor or "").strip().upper() if caractere.isalnum()
    )


def _extrair_id_anuncio_produto(produto):

    if not isinstance(produto, dict):
        return ""

    id_campo = _normalizar_id_anuncio(produto.get("id_anuncio"))
    if id_campo:
        return id_campo

    texto_link = str(produto.get("link_anuncio") or produto.get("link") or "").strip().upper()
    match = re.search(r"\b(MLBU?\d{6,})\b", texto_link)
    if match:
        return _normalizar_id_anuncio(match.group(1))

    return ""


def _ids_equivalentes_anuncio(id_anuncio):

    id_limpo = _normalizar_id_anuncio(id_anuncio)
    if not id_limpo:
        return []

    candidatos = [id_limpo]

    if id_limpo.startswith("MLB") and id_limpo[3:].isdigit():
        candidatos.append(id_limpo[3:])
    elif id_limpo.isdigit():
        candidatos.append(f"MLB{id_limpo}")

    if id_limpo.startswith("MLBU") and id_limpo[4:].isdigit():
        sufixo = id_limpo[4:]
        candidatos.append(sufixo)
        candidatos.append(f"MLB{sufixo}")

    vistos = set()
    unicos = []
    for candidato in candidatos:
        if candidato in vistos:
            continue
        vistos.add(candidato)
        unicos.append(candidato)

    return unicos


def _resolver_caminho_imagem_local_por_id(id_anuncio):

    if not id_anuncio:
        return ""

    if not PASTA_IMAGENS_ANUNCIOS.exists():
        return ""

    for id_candidato in _ids_equivalentes_anuncio(id_anuncio):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidato = PASTA_IMAGENS_ANUNCIOS / f"anuncio_{id_candidato}{ext}"
            if candidato.exists():
                return str(candidato)

    for id_candidato in _ids_equivalentes_anuncio(id_anuncio):
        candidatos = sorted(PASTA_IMAGENS_ANUNCIOS.glob(f"anuncio_{id_candidato}.*"))
        if candidatos:
            return str(candidatos[0])

    return ""


def _carregar_cache_drive_imagens():

    vazio = {"por_arquivo": {}, "por_id": {}}

    if not ARQUIVO_CACHE_DRIVE_IMAGENS.exists():
        return vazio

    try:
        with open(ARQUIVO_CACHE_DRIVE_IMAGENS, "r", encoding="utf-8") as arquivo:
            conteudo = json.load(arquivo)
    except Exception:
        return vazio

    if not isinstance(conteudo, dict):
        return vazio

    por_arquivo = conteudo.get("por_arquivo")
    por_id = conteudo.get("por_id")

    if not isinstance(por_arquivo, dict):
        por_arquivo = {}
    if not isinstance(por_id, dict):
        por_id = {}

    return {
        "por_arquivo": {
            str(chave): str(valor)
            for chave, valor in por_arquivo.items()
            if str(valor).startswith(("http://", "https://"))
        },
        "por_id": {
            str(chave): str(valor)
            for chave, valor in por_id.items()
            if str(valor).startswith(("http://", "https://"))
        },
    }


def _salvar_cache_drive_imagens(cache):

    payload = {
        "por_arquivo": cache.get("por_arquivo", {}),
        "por_id": cache.get("por_id", {}),
    }

    with open(ARQUIVO_CACHE_DRIVE_IMAGENS, "w", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False, indent=2)


def _resolver_caminho_credencial_drive():

    caminho = Path(GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE)
    if not caminho.is_absolute():
        caminho = BASE_DIR / caminho

    return caminho.resolve()


def _carregar_cliente_google_drive():

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    caminho_credencial = _resolver_caminho_credencial_drive()
    if not caminho_credencial.exists():
        raise FileNotFoundError(
            f"Arquivo de service account nao encontrado: {caminho_credencial}"
        )

    scopes = ["https://www.googleapis.com/auth/drive.file"]
    credenciais = Credentials.from_service_account_file(str(caminho_credencial), scopes=scopes)

    return build("drive", "v3", credentials=credenciais, cache_discovery=False)


def _inicializar_contexto_drive_imagens():

    contexto = {
        "habilitado": False,
        "cliente": None,
        "folder_id": "",
        "cache": {"por_arquivo": {}, "por_id": {}},
        "cache_alterado": False,
    }

    if not TWILIO_USAR_GOOGLE_DRIVE_IMAGENS:
        return contexto

    if not GOOGLE_DRIVE_IMAGENS_FOLDER_ID:
        print("[WARN] Upload de imagens no Drive desativado: GOOGLE_DRIVE_IMAGENS_FOLDER_ID nao configurado.")
        return contexto

    try:
        cliente = _carregar_cliente_google_drive()
        contexto["cliente"] = cliente
        contexto["folder_id"] = GOOGLE_DRIVE_IMAGENS_FOLDER_ID
        contexto["cache"] = _carregar_cache_drive_imagens()
        contexto["habilitado"] = True
        print("[DEBUG] Upload de imagens no Google Drive ativado para envio Twilio.")
        return contexto
    except Exception as exc:
        print(f"[WARN] Falha ao iniciar Google Drive para imagens: {exc}")
        return contexto


def _finalizar_contexto_drive_imagens(contexto):

    if not contexto or not contexto.get("habilitado"):
        return

    if not contexto.get("cache_alterado"):
        return

    try:
        _salvar_cache_drive_imagens(contexto.get("cache") or {})
    except Exception as exc:
        print(f"[WARN] Nao foi possivel salvar cache de imagens do Drive: {exc}")


def _publicar_imagem_local_no_drive(contexto, id_anuncio, caminho_local):

    if not contexto or not contexto.get("habilitado"):
        return ""

    caminho_resolvido = str(Path(caminho_local).resolve())
    cache = contexto.get("cache") or {"por_arquivo": {}, "por_id": {}}

    url_em_cache = str(cache.get("por_arquivo", {}).get(caminho_resolvido) or "").strip()
    if url_em_cache.startswith(("http://", "https://")):
        return url_em_cache

    from googleapiclient.http import MediaFileUpload

    mime_type = mimetypes.guess_type(caminho_resolvido)[0] or "application/octet-stream"
    nome_arquivo = Path(caminho_resolvido).name

    corpo = {
        "name": nome_arquivo,
        "parents": [contexto["folder_id"]],
    }

    arquivo_midia = MediaFileUpload(caminho_resolvido, mimetype=mime_type, resumable=False)
    resposta = contexto["cliente"].files().create(
        body=corpo,
        media_body=arquivo_midia,
        fields="id",
        supportsAllDrives=True,
    ).execute()

    file_id = str(resposta.get("id") or "").strip()
    if not file_id:
        return ""

    contexto["cliente"].permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        sendNotificationEmail=False,
        supportsAllDrives=True,
    ).execute()

    url_publica = f"https://drive.google.com/uc?export=view&id={file_id}"

    cache.setdefault("por_arquivo", {})[caminho_resolvido] = url_publica
    if id_anuncio:
        cache.setdefault("por_id", {})[id_anuncio] = url_publica
    contexto["cache_alterado"] = True

    return url_publica


def _resolver_imagem_para_twilio(produto, contexto_drive):

    imagem_remota = str(
        produto.get("imagem_principal")
        or produto.get("url_imagem")
        or produto.get("imagem")
        or produto.get("secure_thumbnail")
        or produto.get("thumbnail")
        or ""
    ).strip()

    if not contexto_drive or not contexto_drive.get("habilitado"):
        return imagem_remota

    id_anuncio = _extrair_id_anuncio_produto(produto)
    if not id_anuncio:
        return imagem_remota

    cache = contexto_drive.get("cache") or {}
    url_por_id = str((cache.get("por_id") or {}).get(id_anuncio) or "").strip()
    if url_por_id.startswith(("http://", "https://")):
        return url_por_id

    caminho_local = _resolver_caminho_imagem_local_por_id(id_anuncio)
    if not caminho_local:
        return imagem_remota

    try:
        url_publica = _publicar_imagem_local_no_drive(contexto_drive, id_anuncio, caminho_local)
        if url_publica:
            print(f"[DEBUG] imagem_publicada_drive id={id_anuncio} arquivo={Path(caminho_local).name}")
            return url_publica
    except Exception as exc:
        print(f"[WARN] Falha ao publicar imagem no Drive para id={id_anuncio}: {exc}")

    return imagem_remota


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


def _parse_timestamp_historico(valor):

    texto = str(valor or "").strip()

    if not texto:

        return None

    formatos = (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d_%H%M%S",
    )

    for formato in formatos:

        try:

            return datetime.strptime(texto, formato)

        except ValueError:

            continue

    return None


def _montar_tupla_historico(produto, timestamp=None):

    instante = timestamp or datetime.now()

    return (
        normalizar_chave_historico(produto.get("id_anuncio")),
        normalizar_descricao(produto.get("descricao")),
        (produto.get("antes") or "").strip(),
        (produto.get("depois") or "").strip(),
        (produto.get("desconto") or "").strip(),
        (produto.get("link_original") or produto.get("link") or "").strip(),
        instante.isoformat(timespec="seconds"),
    )


def _normalizar_tupla_historico_existente(anuncio, timestamp):

    base = list(anuncio[:6])

    while len(base) < 6:

        base.append("")

    base[0] = normalizar_chave_historico(base[0])
    base[1] = normalizar_descricao(base[1])

    return tuple(base[:6] + [timestamp.isoformat(timespec="seconds")])


def _carregar_registros_historico_anuncios(caminho_arquivo):

    registros_por_id = {}
    precisa_regravar = False
    limite = datetime.now() - timedelta(days=HISTORICO_RETENCAO_DIAS)

    try:

        mtime_arquivo = datetime.fromtimestamp(os.path.getmtime(caminho_arquivo))

        with open(caminho_arquivo, "r", encoding="utf-8") as arquivo:

            for linha in arquivo:

                linha_limpa = linha.strip()

                if not linha_limpa:

                    continue

                try:

                    anuncio = ast.literal_eval(linha_limpa)

                except Exception:

                    precisa_regravar = True
                    continue

                if not isinstance(anuncio, tuple) or not anuncio:

                    precisa_regravar = True
                    continue

                anuncio_id = normalizar_chave_historico(str(anuncio[0]))

                if not anuncio_id:

                    precisa_regravar = True
                    continue

                timestamp = None
                if len(anuncio) >= 7:

                    timestamp = _parse_timestamp_historico(anuncio[6])

                if timestamp is None:

                    timestamp = mtime_arquivo
                    precisa_regravar = True

                if timestamp < limite:

                    precisa_regravar = True
                    continue

                registro = {"id": anuncio_id, "anuncio": anuncio, "timestamp": timestamp}
                existente = registros_por_id.get(anuncio_id)

                if existente is None or timestamp >= existente["timestamp"]:

                    registros_por_id[anuncio_id] = registro

                if len(anuncio) < 7:

                    precisa_regravar = True

    except FileNotFoundError:

        return []

    registros = sorted(
        registros_por_id.values(),
        key=lambda item: (item["timestamp"], item["id"]),
    )

    if precisa_regravar:

        with open(caminho_arquivo, "w", encoding="utf-8") as arquivo:

            for registro in registros:

                tupla_normalizada = _normalizar_tupla_historico_existente(
                    registro["anuncio"],
                    registro["timestamp"],
                )
                arquivo.write(f"{tupla_normalizada!r}\n")

    return registros


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

    return {
        registro["id"]
        for registro in _carregar_registros_historico_anuncios(caminho_arquivo)
    }


def carregar_historico_precos_por_anuncio(caminho_arquivo):

    historico = {}

    for registro in _carregar_registros_historico_anuncios(caminho_arquivo):

        anuncio = registro["anuncio"]

        if len(anuncio) < 4:
            continue

        anuncio_id = registro["id"]
        preco_atual = converter_preco(str(anuncio[3]))

        if not anuncio_id or preco_atual is None:
            continue

        preco_salvo = historico.get(anuncio_id)
        if preco_salvo is None or preco_atual < preco_salvo:
            historico[anuncio_id] = preco_atual

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

    return _montar_tupla_historico(produto)


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


def sessao_ml_ativa_por_marcador_header(page):

    try:
        marcador = page.locator(
            "nav#nav-header-menu .nav-header-profile-evolution__user-initials"
        ).first

        if marcador.count() == 0:
            return False

        iniciais = (marcador.inner_text(timeout=1500) or "").strip().upper()
        return iniciais == "LM"
    except Exception:
        return False


def usuario_esta_logado_mercado_livre(page):

    try:

        url_atual = (page.url or "").lower()
        if "/login" in url_atual:
            return False

        # Marcador explícito informado: se houver 'LM' no menu do usuário,
        # considera sessão autenticada.
        if sessao_ml_ativa_por_marcador_header(page):
            return True

        # Seletores positivos comuns em sessão autenticada (podem variar conforme UI/AB tests).
        if page.locator(
            "button[aria-label*='menu'], a[aria-label*='menu'], button:has-text('menu'), a[href*='logout'], a[href*='my-account']"
        ).count() > 0:
            return True

        # Seletor nominal do perfil pode variar por conta/idioma.
        if page.locator("button:has-text('menu')").count() > 0:
            return True

        # Sinais explícitos de sessão deslogada.
        if page.locator("a[href*='login'], a[href*='registration']").count() > 0:
            return False

        if page.get_by_role("link", name="Entre").count() > 0:
            return False

        if page.get_by_role("link", name="Crie a sua conta").count() > 0:
            return False

    except Exception:

        # Durante navegação/redirecionamento o estado pode oscilar; trata como "ainda não logado".
        return False

    return False


def url_em_fluxo_autenticacao_ml(url):

    url_atual = (url or "").lower()

    marcadores = [
        "/login",
        "identity",
        "authentication",
        "challenges",
        "chooser/callback",
        "phone-validation",
        "enter-code",
        "otp",
        "mfa",
        "challenge",
    ]

    return any(marcador in url_atual for marcador in marcadores)


def sessao_ml_ativa_via_requisicao(page):

    try:
        resposta = page.context.request.get(URL_LISTAGEM, timeout=5000)
        url_final = (resposta.url or "").lower()

        if any(parte in url_final for parte in ["/login", "identity", "authentication"]):
            return False

        return bool(resposta.ok)
    except Exception:
        return False


def aguardar_login_mercado_livre(page):

    if usuario_esta_logado_mercado_livre(page):

        print(
            "\nMercado Livre ja esta autenticado."
        )

        return

    print(
        "\nMercado Livre nao esta autenticado. Faça login manualmente no navegador aberto."
    )

    if MODO_INTERFACE:

        print(
            f"{AUTH_MARKER_REQUIRED_ML} Mercado Livre não autenticado, realize o login e clique em 'Continuar'."
        )

        timeout_segundos = 900
        inicio_espera = time.time()

        while (time.time() - inicio_espera) < timeout_segundos:

            if not os.path.exists(LOGIN_OK_SIGNAL_FILE):
                time.sleep(1)
                continue

            try:
                os.remove(LOGIN_OK_SIGNAL_FILE)
            except Exception:
                pass

            print("\nConfirmacao recebida da interface. Validando sessao...")

            if usuario_esta_logado_mercado_livre(page) or sessao_ml_ativa_via_requisicao(page):
                print("\nLogin confirmado. Continuando execução.")
                return

            print(
                f"{AUTH_MARKER_STILL_PENDING_ML} Login ainda nao confirmado. Continue no navegador e clique em 'Continuar' novamente."
            )

        raise RuntimeError(
            "Sessao do Mercado Livre nao autenticada apos aguardar 900s. "
            "Entre na conta e execute novamente."
        )

    timeout_segundos = 300
    inicio_espera = time.time()

    while (time.time() - inicio_espera) < timeout_segundos:

        if usuario_esta_logado_mercado_livre(page):

            print("\nLogin confirmado. Continuando execução.")
            return

        # Não interfere no fluxo de login/MFA enquanto ele está em andamento.
        if url_em_fluxo_autenticacao_ml(page.url):
            if sessao_ml_ativa_via_requisicao(page):
                print("\nLogin confirmado. Continuando execução.")
                return

            time.sleep(2)
            continue

        # Valida sessão em background sem interromper a tela atual (MFA/login).
        if sessao_ml_ativa_via_requisicao(page):
            print("\nLogin confirmado. Continuando execução.")
            return

        time.sleep(2)

    raise RuntimeError(
        "Sessao do Mercado Livre nao autenticada apos aguardar 300s. "
        "Entre na conta e execute novamente."
    )


def montar_mensagem_produto(produto, incluir_banner_relampago=False):

    categoria = produto.get("categoria", "-")
    descricao = produto.get("descricao", "-")
    antes = produto.get("antes", "-")
    depois = produto.get("depois", "-")
    desconto = produto.get("desconto", "-")
    link = produto.get("link", "-")

    linhas = []

    if MENSAGEM_COMPLEMENTAR:
        for linha in MENSAGEM_COMPLEMENTAR.splitlines():
            linha_limpa = linha.strip()
            if linha_limpa:
                linhas.append(f"*{linha_limpa}*")
        if linhas:
            linhas.append("")

    if incluir_banner_relampago:
        linhas.append("*⚡⚡ OFERTA RELAMPAGO ⚡⚡*")
        linhas.append("")

    linhas.extend(
        [
            f"*{categoria}*",
            "",
            f"{descricao}",
            "",
            f"~Antes: {antes}~",
            f"*Desconto: {desconto}*",
            f"*Depois: {depois}*",
            f"{link}",
        ]
    )

    return "\n".join(linhas)


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


def _aguardar_status_final_twilio(client, message_sid, tentativas=4, intervalo_segundos=2):

    status_final = ""
    erro_codigo = None
    erro_mensagem = ""

    for _ in range(max(1, int(tentativas))):

        try:
            mensagem = client.messages(message_sid).fetch()
        except Exception:
            break

        status_final = str(getattr(mensagem, "status", "") or "").strip().lower()
        erro_codigo = getattr(mensagem, "error_code", None)
        erro_mensagem = str(getattr(mensagem, "error_message", "") or "").strip()

        if status_final in {"delivered", "sent", "read", "failed", "undelivered", "canceled"}:
            break

        time.sleep(max(1, int(intervalo_segundos)))

    return status_final, erro_codigo, erro_mensagem


def _twilio_pode_enviar_midia(imagem_url):

    url = str(imagem_url or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, "url_invalida"

    if TWILIO_FORCAR_TEXTO_SOMENTE:
        return False, "modo_texto_somente"

    caminho = url.split("?", 1)[0].lower()
    if caminho.endswith(".webp") and not TWILIO_ENVIAR_MIDIA_WEBP:
        return False, "webp_desativado"

    return True, "ok"


def enviar_produtos_por_whatsapp(produtos, incluir_banner_relampago=False):

    if not produtos:

        print(
            "\nNenhum produto para enviar no WhatsApp."
        )

        return

    account_sid = ler_variavel_ambiente("TWILIO_ACCOUNT_SID")
    auth_token = ler_variavel_ambiente("TWILIO_AUTH_TOKEN")
    whatsapp_from = ler_variavel_ambiente("TWILIO_WHATSAPP_FROM")
    whatsapp_to = ler_variavel_ambiente("TWILIO_WHATSAPP_TO") or WHATSAPP_DESTINO_FIXO

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

    total_falhas = 0
    total_ok = 0

    contexto_drive = _inicializar_contexto_drive_imagens()

    try:
        for produto in produtos:

            mensagem = montar_mensagem_produto(
                produto,
                incluir_banner_relampago=incluir_banner_relampago,
            )
            imagem = _resolver_imagem_para_twilio(produto, contexto_drive)
            parametros_envio = {
                "from_": whatsapp_from,
                "to": whatsapp_to,
                "body": mensagem,
            }

            pode_enviar_midia, motivo_midia = _twilio_pode_enviar_midia(imagem)
            if pode_enviar_midia:

                # O Twilio usa media_url para enviar a imagem junto com a mensagem.
                parametros_envio["media_url"] = [imagem]

            print(
                f"\n[DEBUG] media_url={'SIM' if 'media_url' in parametros_envio else 'NAO'}"
            )

            if "media_url" not in parametros_envio:
                print(f"[DEBUG] motivo_sem_midia={motivo_midia}")

            print(
                f"[DEBUG] imagem={imagem if imagem else 'SEM IMAGEM'}"
            )

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

            status_final, erro_codigo, erro_mensagem = _aguardar_status_final_twilio(
                client,
                resposta.sid,
                tentativas=TWILIO_STATUS_CHECK_TENTATIVAS,
                intervalo_segundos=TWILIO_STATUS_CHECK_INTERVALO_SEGUNDOS,
            )

            if status_final:
                print(f"[DEBUG] status_final_twilio={status_final}")

            if status_final in {"failed", "undelivered", "canceled"}:
                total_falhas += 1
                print(
                    "[ERRO] Twilio nao entregou a mensagem "
                    f"(sid={resposta.sid}, status={status_final}, code={erro_codigo}, msg={erro_mensagem or 'sem detalhe'})."
                )

                if "media_url" in parametros_envio:
                    print("[DEBUG] Tentando reenvio sem imagem (fallback).")
                    try:
                        resposta_fallback = client.messages.create(
                            from_=whatsapp_from,
                            to=whatsapp_to,
                            body=mensagem,
                        )
                        status_fb, erro_codigo_fb, erro_mensagem_fb = _aguardar_status_final_twilio(
                            client,
                            resposta_fallback.sid,
                            tentativas=TWILIO_STATUS_CHECK_TENTATIVAS,
                            intervalo_segundos=TWILIO_STATUS_CHECK_INTERVALO_SEGUNDOS,
                        )

                        if status_fb:
                            print(f"[DEBUG] status_final_twilio_fallback={status_fb}")

                        if status_fb in {"failed", "undelivered", "canceled"}:
                            print(
                                "[ERRO] Fallback sem imagem tambem falhou "
                                f"(sid={resposta_fallback.sid}, status={status_fb}, code={erro_codigo_fb}, msg={erro_mensagem_fb or 'sem detalhe'})."
                            )
                        else:
                            total_ok += 1
                            print(f"[OK] Fallback sem imagem enviado com sid={resposta_fallback.sid}.")
                    except TwilioRestException as exc_fb:
                        print(
                            "[ERRO] Excecao no fallback sem imagem: "
                            f"code={getattr(exc_fb, 'code', '-')}, status={getattr(exc_fb, 'status', '-')}, "
                            f"msg={str(getattr(exc_fb, 'msg', exc_fb) or exc_fb).strip()}"
                        )
            else:
                total_ok += 1

            time.sleep(
                random.uniform(*TWILIO_PAUSA_ENTRE_ENVIOS_SEGUNDOS)
            )
    finally:
        _finalizar_contexto_drive_imagens(contexto_drive)

    print(
        f"\n[RESUMO_TWILIO] entregues_ou_processadas={total_ok} falhas={total_falhas} total={len(produtos)}"
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
categoria_id_parametrizada = (ARGS.categoria_id or "").strip().upper() if ARG_CATEGORIA_ID_INFORMADA else None
subcategoria_id_parametrizada = (ARGS.subcategoria_id or "").strip().upper() if ARG_SUBCATEGORIA_ID_INFORMADA else None
descricao_parametrizada = (ARGS.descricao_produto or "").strip() if ARG_DESCRICAO_PRODUTO_INFORMADA else None
urls_produto_parametrizadas = None
if ARG_URL_PRODUTO_INFORMADA:
    urls_produto_parametrizadas = [
        str(url).strip()
        for url in (ARGS.url_produto or [])
        if str(url).strip()
    ][:5]
    if not urls_produto_parametrizadas:
        urls_produto_parametrizadas = None
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

    if MODO_PRODUTO_POR_HTML:

        print("[MODO_ATIVO] PRODUTO_ONDEMAND_HOME_PESQUISA")
        print("\nModo procurar produto ativado (pesquisa pela home do Mercado Livre).")

        usar_links_diretos = bool(urls_produto_parametrizadas)
        if not usar_links_diretos:
            page.goto(
                "https://www.mercadolivre.com.br",
                timeout=90000,
                wait_until="domcontentloaded"
            )

        ofertas_hub = processar_produtos_home_por_pesquisa(
            page,
            categoria=categoria_parametrizada,
            categoria_id=categoria_id_parametrizada,
            subcategoria_id=subcategoria_id_parametrizada,
            descricao=(ARGS.descricao_produto or "").strip() or None,
            urls=urls_produto_parametrizadas,
            preco_minimo=preco_minimo_parametrizado,
            preco_maximo=preco_maximo_parametrizado,
            desconto_minimo=desconto_minimo_parametrizado,
            limite_candidatos=limite_candidatos_parametrizado,
            historico_anuncios=historico_anuncios,
            limite_validos=(limite_candidatos_parametrizado or 10),
            limite_paginas=LIMITE_PAGINAS_PESQUISA,
        )

        ofertas_hub = filtrar_anuncios_ineditos_ou_com_reducao(
            ofertas_hub,
            historico_precos_por_anuncio,
        )

        if ofertas_hub:

            salvar_resultado_relampago(
                ofertas_hub,
                pasta=ARGS.pasta_saida or None,
                incluir_banner_relampago=False,
            )
            salvar_resultado_produto_json(
                ofertas_hub,
                pasta=ARGS.pasta_saida or None,
            )
            salvar_saida_execucao_modalidade(ofertas_hub, ARGS.modalidade_execucao or "ondemand")
            salvar_saida_execucao_modalidade_json(ofertas_hub, ARGS.modalidade_execucao or "ondemand")

            enviar_produtos_por_whatsapp(ofertas_hub)

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

            print(f"\n{len(ofertas_hub)} oferta(s) processada(s) e salva(s).")

        else:

            print("\nNenhuma oferta elegível foi encontrada na pesquisa da home.")

        context.close()

        raise SystemExit(0)

    print("[MODO_ATIVO] FLUXO_HUB_AFILIADOS_LEGADO")
    page.goto(
        URL_LISTAGEM
    )

    debug_pausa("Navegador aberto e hub carregado")

    aguardar_login_mercado_livre(
        page
    )

    debug_pausa("Depois da validacao de login do Mercado Livre")

    if MODO_BUSCA_DESCRICAO and not MODO_SOMENTE_RELAMPAGO:

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

            salvar_resultado_relampago(
                [produto_manual],
                incluir_banner_relampago=False,
            )
            salvar_resultado_produto_json(
                [produto_manual],
            )
            salvar_saida_execucao_modalidade([produto_manual], ARGS.modalidade_execucao or "ondemand")
            salvar_saida_execucao_modalidade_json([produto_manual], ARGS.modalidade_execucao or "ondemand")

            enviar_produtos_por_whatsapp([produto_manual])

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
        descricao_parametrizada is None
        and preco_minimo_parametrizado is None
        and preco_maximo_parametrizado is None
        and desconto_minimo_parametrizado is None
        and limite_candidatos_parametrizado is None
    )

    limite_validos_extraidos = LIMITE_VALIDOS_RELAMPAGO_PADRAO

    ofertas_relampago = processar_ofertas_relampago(
        page,
        URL_RELAMPAGO_ALVO,
        desconto_minimo=DESCONTO_MINIMO_RELAMPAGO_PADRAO if MODO_RELAMPAGO_PADRAO else desconto_minimo_parametrizado,
        descricao=None if MODO_RELAMPAGO_PADRAO else descricao_parametrizada,
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
        salvar_resultado_relampago_json(ofertas_relampago, pasta=ARGS.pasta_saida or None)
        salvar_saida_execucao_modalidade(ofertas_relampago, ARGS.modalidade_execucao or "ondemand")
        salvar_saida_execucao_modalidade_json(ofertas_relampago, ARGS.modalidade_execucao or "ondemand")

        enviar_produtos_por_whatsapp(
            ofertas_relampago,
            incluir_banner_relampago=True,
        )

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