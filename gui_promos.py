import argparse
import calendar
import contextlib
import hashlib
import importlib
import json
import os
import queue
import re
import smtplib
import subprocess
import sys
import threading
import unicodedata
import webbrowser
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests
from bs4 import BeautifulSoup
from parsers.mercadolivre import salvar_saida_execucao_modalidade

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client as TwilioClient
except Exception:
    TwilioRestException = Exception
    TwilioClient = None


def _resolve_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _resolve_base_dir()
ALERTS_CONFIG_FILE = BASE_DIR / "alertas_preco.json"
HUB_SCHEDULES_CONFIG_FILE = BASE_DIR / "agendamentos_hub.json"
SHEETS_ALERTS_CONFIG_FILE = BASE_DIR / "integracao_planilha_alertas.json"
LOGS_DIR = BASE_DIR / "logs_execucao"
ALERT_LOGS_DIR = LOGS_DIR / "alertas"
SHEETS_SYNC_LOGS_DIR = LOGS_DIR / "planilha"
LOGIN_OK_SIGNAL_FILE = BASE_DIR / ".ml_login_ok.signal"
AUTH_MARKER_REQUIRED_ML = "[AUTH_REQUIRED_ML]"
AUTH_MARKER_STILL_PENDING_ML = "[AUTH_STILL_PENDING_ML]"
SCHEDULER_TICK_MS = 60000
ALERTS_IMPORT_INTERVAL_MINUTES = 10
ALERT_INTERVAL_HOURS_FIXED = 3
ALERT_ACTIVE_DAYS_DEFAULT = 30
ALERT_EXECUTION_DAYS_AFTER_FIRST_TRIGGER = 7
TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS = True
TWILIO_TRIAL_DESTINO_PADRAO = "19991133269"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

if load_dotenv is not None:
    load_dotenv()


def _ler_variavel_ambiente(nome):
    return os.getenv(nome, "").strip().strip('"').strip("'")


def _maybe_breakpoint(tag):
    flag = os.getenv("PROMOS_BREAKPOINTS", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        print(f"[DEBUG BREAKPOINT] {tag}")
        breakpoint()


def _split_destinos(valor):
    texto = (valor or "").strip()
    if not texto:
        return []
    return [p.strip() for p in re.split(r"[;,]", texto) if p.strip()]


def _single_destino(valor):
    destinos = _split_destinos(valor)
    if not destinos:
        return "", []
    return destinos[0], [destinos[0]]


def _normalizar_telefone_whatsapp(numero):
    bruto = (numero or "").strip()
    if not bruto:
        return ""

    # Aceita numero puro, com +, com espacos, ou ja no formato whatsapp:.
    digitos = re.sub(r"\D", "", bruto)
    if not digitos:
        return ""

    # Twilio WhatsApp exige E.164 com codigo do pais.
    if not digitos.startswith("55"):
        digitos = f"55{digitos}"

    return f"whatsapp:+{digitos}"


def _mascarar_destino_whatsapp(destino):
    digitos = re.sub(r"\D", "", destino or "")
    if not digitos:
        return "invalido"

    if len(digitos) <= 4:
        return f"***{digitos}"

    return f"***{digitos[-4:]}"


def _str_to_bool(value):
    texto = ("" if value is None else str(value)).strip().casefold()
    return texto in {"1", "true", "verdadeiro", "sim", "yes", "y"}


def _formatar_preco_brl(valor):
    return f"R$ {float(valor):.2f}"


def _load_sheets_alerts_config(config_path):
    default_cfg = {
        "enabled": False,
        "auth_mode": "oauth_user",
        "spreadsheet_id": "",
        "spreadsheet_url": "",
        "worksheet_name": "RespostasForm",
        "oauth_client_file": "credentials/google-oauth-client-secret.json",
        "oauth_token_file": "credentials/google-oauth-token.json",
        "service_account_file": "credentials/google-service-account.json",
    }

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict):
                default_cfg.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return default_cfg


def _save_sheets_alerts_config(config_path, config):
    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)


def _spreadsheet_id_from_url(url):
    texto = (url or "").strip()
    if not texto:
        return ""

    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", texto)
    if not match:
        return ""

    return match.group(1)


def _resolve_config_file_path(path_value):
    path_str = (path_value or "").strip()
    if not path_str:
        return None

    path_obj = Path(path_str)
    if not path_obj.is_absolute():
        path_obj = BASE_DIR / path_obj

    return path_obj


def _load_google_sheets_client(sheets_config, progress_callback=None):
    discovery_module = importlib.import_module("googleapiclient.discovery")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    auth_mode = (sheets_config.get("auth_mode") or "oauth_user").strip().lower()

    if auth_mode == "service_account":
        credentials_module = importlib.import_module("google.oauth2.service_account")
        service_account_path = _resolve_config_file_path(sheets_config.get("service_account_file"))
        if service_account_path is None or not service_account_path.exists():
            raise FileNotFoundError(
                f"Arquivo de service account nao encontrado: {service_account_path or '[vazio]'}"
            )

        credentials = credentials_module.Credentials.from_service_account_file(
            str(service_account_path), scopes=scopes
        )
    else:
        credentials_module = importlib.import_module("google.oauth2.credentials")
        requests_module = importlib.import_module("google.auth.transport.requests")
        oauth_flow_module = importlib.import_module("google_auth_oauthlib.flow")

        def _obter_novas_credenciais_via_oauth():
            flow = oauth_flow_module.InstalledAppFlow.from_client_secrets_file(
                str(oauth_client_path), scopes
            )
            try:
                if progress_callback:
                    progress_callback("Aguardando autorizacao do Google no navegador para sincronizar a planilha.")
                return flow.run_local_server(port=0, open_browser=True)
            except Exception as exc:
                auth_url, _ = flow.authorization_url(
                    access_type="offline",
                    include_granted_scopes="true",
                    prompt="consent",
                )
                raise RuntimeError(
                    "Nao foi possivel abrir o navegador automaticamente para OAuth. "
                    f"Abra manualmente esta URL e autorize: {auth_url}"
                ) from exc

        oauth_client_path = _resolve_config_file_path(sheets_config.get("oauth_client_file"))
        oauth_token_path = _resolve_config_file_path(sheets_config.get("oauth_token_file"))

        if oauth_client_path is None or not oauth_client_path.exists():
            raise FileNotFoundError(
                f"Arquivo OAuth client secret nao encontrado: {oauth_client_path or '[vazio]'}"
            )

        if oauth_token_path is None:
            raise FileNotFoundError("Caminho do arquivo de token OAuth nao configurado.")

        credentials = None
        if oauth_token_path.exists():
            credentials = credentials_module.Credentials.from_authorized_user_file(
                str(oauth_token_path), scopes
            )

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                if progress_callback:
                    progress_callback("Atualizando token OAuth da planilha.")
                try:
                    credentials.refresh(requests_module.Request())
                except Exception as exc:
                    erro_refresh = str(exc).casefold()
                    if "invalid_grant" in erro_refresh or "expired or revoked" in erro_refresh:
                        if progress_callback:
                            progress_callback(
                                "Token OAuth expirado/revogado. Solicitando nova autorizacao no navegador."
                            )

                        with contextlib.suppress(Exception):
                            if oauth_token_path.exists():
                                oauth_token_path.unlink()

                        credentials = _obter_novas_credenciais_via_oauth()
                    else:
                        raise
            else:
                credentials = _obter_novas_credenciais_via_oauth()

            oauth_token_path.parent.mkdir(parents=True, exist_ok=True)
            oauth_token_path.write_text(credentials.to_json(), encoding="utf-8")

    return discovery_module.build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _sheet_a1_range(worksheet_name, cell_range):
    nome = str(worksheet_name or "").strip()
    nome_escapado = nome.replace("'", "''")
    return f"'{nome_escapado}'!{cell_range}"


def _sheet_nome_normalizado(nome):
    texto = str(nome or "").strip().strip("'").strip('"')
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"\s+", " ", texto)
    return texto.casefold().strip()


def _sheet_resolver_nome_aba(client, spreadsheet_id, worksheet_name):
    desejado = str(worksheet_name or "").strip().strip("'").strip('"')
    if not desejado:
        raise ValueError("Nome da aba (worksheet_name) nao informado.")

    metadata = (
        client.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title))")
        .execute()
    )
    titulos = [
        str((sheet.get("properties") or {}).get("title") or "").strip()
        for sheet in metadata.get("sheets", [])
    ]
    titulos = [t for t in titulos if t]

    if not titulos:
        raise RuntimeError("Nao foi possivel listar as abas da planilha.")

    # 1) Match exato
    for titulo in titulos:
        if titulo == desejado:
            return titulo

    # 2) Match case-insensitive
    desejado_cf = desejado.casefold()
    for titulo in titulos:
        if titulo.casefold() == desejado_cf:
            return titulo

    # 3) Match normalizado (acentos/espacos)
    desejado_norm = _sheet_nome_normalizado(desejado)
    for titulo in titulos:
        if _sheet_nome_normalizado(titulo) == desejado_norm:
            return titulo

    raise RuntimeError(
        "Nao foi possivel localizar a aba configurada. "
        f"worksheet_name='{desejado}'. Abas disponiveis: {', '.join(titulos)}"
    )

DEFAULT_CATEGORIES = [
    "Acessórios para Veículos",
    "Agro",
    "Alimentos e Bebidas",
    "Antiguidades e Coleções",
    "Arte, Papelaria e Armarinho",
    "Bebês",
    "Beleza e Cuidado Pessoal",
    "Brinquedos e Hobbies",
    "Calçados, Roupas e Bolsas",
    "Casa, Móveis e Decoração",
    "Celulares e Telefones",
    "Construção",
    "Câmeras e Acessórios",
    "Eletrodomésticos",
    "Eletrônicos, Áudio e Vídeo",
    "Esportes e Fitness",
    "Ferramentas",
    "Festas e Lembrancinhas",
    "Games",
    "Indústria e Comércio",
    "Informática",
    "Instrumentos Musicais",
    "Joias e Relógios",
    "Livros, Revistas e Comics",
    "Mais Categorias",
    "Pet Shop",
    "Saúde",
]

ML_CATEGORIES_ALL_URL = "https://api.mercadolibre.com/sites/MLB/categories/all"
ML_CATEGORY_DETAIL_URL_TEMPLATE = "https://api.mercadolibre.com/categories/{category_id}"
ML_CATEGORIES_CACHE_FILE = BASE_DIR / "ml_categories_cache.json"


def _slugify_categoria_nome(texto):
    normalizado = unicodedata.normalize("NFKD", str(texto or ""))
    ascii_only = normalizado.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug


def _chave_nome_categoria(texto):
    return " ".join(str(texto or "").split()).strip().casefold()


def _normalizar_raizes_categoria(roots, categorias_fallback):
    normalizadas = []
    vistos = set()

    for item in roots or []:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("name") or "").strip()
        if not nome:
            continue
        cid = str(item.get("id") or "").strip().upper()
        chave = nome.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        normalizadas.append({"id": cid, "name": nome, "slug": _slugify_categoria_nome(nome)})

    if normalizadas:
        return sorted(normalizadas, key=lambda c: c.get("name", "").casefold())

    for nome in categorias_fallback or []:
        nome_limpo = str(nome or "").strip()
        if not nome_limpo:
            continue
        chave = nome_limpo.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        normalizadas.append({"id": "", "name": nome_limpo, "slug": _slugify_categoria_nome(nome_limpo)})

    return sorted(normalizadas, key=lambda c: c.get("name", "").casefold())


def _ml_get_json(url, timeout=15):
    resposta = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    resposta.raise_for_status()
    return resposta.json()


def _salvar_cache_categorias_ml(payload):
    try:
        with open(ML_CATEGORIES_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _carregar_cache_categorias_ml():
    try:
        with open(ML_CATEGORIES_CACHE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict):
                return data
    except Exception:
        pass

    return {"roots": [], "children": {}}


def _load_ml_categories_catalog(categorias_fallback):
    cache = _carregar_cache_categorias_ml()
    cache_children = cache.get("children") if isinstance(cache.get("children"), dict) else {}

    roots = []
    try:
        raw_roots = _ml_get_json(ML_CATEGORIES_ALL_URL)
        raw_items = []
        if isinstance(raw_roots, list):
            raw_items = raw_roots
        elif isinstance(raw_roots, dict):
            raw_items = list(raw_roots.values())

        children_map = {}
        all_has_path = bool(raw_items) and all(isinstance(item, dict) and isinstance(item.get("path_from_root"), list) for item in raw_items)

        if all_has_path:
            for item in raw_items:
                cid = str(item.get("id") or "").strip().upper()
                nome = str(item.get("name") or "").strip()
                if not cid or not nome:
                    continue

                path = item.get("path_from_root") if isinstance(item.get("path_from_root"), list) else []
                if len(path) <= 1:
                    roots.append(
                        {
                            "id": cid,
                            "name": nome,
                            "slug": _slugify_categoria_nome(nome),
                        }
                    )

                raw_children = item.get("children_categories") if isinstance(item.get("children_categories"), list) else []
                children = []
                for child in raw_children:
                    if not isinstance(child, dict):
                        continue
                    child_id = str(child.get("id") or "").strip().upper()
                    child_nome = str(child.get("name") or "").strip()
                    if not child_id or not child_nome:
                        continue
                    children.append({"id": child_id, "name": child_nome, "slug": _slugify_categoria_nome(child_nome)})

                children_map[cid] = sorted(children, key=lambda c: c.get("name", "").casefold())
        else:
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("id") or "").strip().upper()
                nome = str(item.get("name") or "").strip()
                if not cid or not nome:
                    continue
                roots.append(
                    {
                        "id": cid,
                        "name": nome,
                        "slug": _slugify_categoria_nome(nome),
                    }
                )

            roots = _normalizar_raizes_categoria(roots, categorias_fallback)
            for root in roots:
                rid = str(root.get("id") or "").strip().upper()
                if not rid:
                    continue

                filhos_cache = cache_children.get(rid)
                if isinstance(filhos_cache, list) and filhos_cache:
                    children_map[rid] = filhos_cache
                    continue

                children = []
                try:
                    url = ML_CATEGORY_DETAIL_URL_TEMPLATE.format(category_id=rid)
                    detalhe = _ml_get_json(url)
                    raw_children = detalhe.get("children_categories") if isinstance(detalhe, dict) else []
                    if isinstance(raw_children, list):
                        for item in raw_children:
                            cid = str(item.get("id") or "").strip().upper()
                            nome = str(item.get("name") or "").strip()
                            if not cid or not nome:
                                continue
                            children.append({"id": cid, "name": nome, "slug": _slugify_categoria_nome(nome)})
                except Exception:
                    children = []

                children_map[rid] = sorted(children, key=lambda c: c.get("name", "").casefold())

        roots = _normalizar_raizes_categoria(roots, categorias_fallback)

        payload = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "roots": roots,
            "children": children_map,
        }
        _salvar_cache_categorias_ml(payload)
        return payload
    except Exception:
        if isinstance(cache.get("roots"), list) and cache.get("roots"):
            cache_roots = _normalizar_raizes_categoria(cache.get("roots"), categorias_fallback)
            return {
                "roots": cache_roots,
                "children": cache_children,
            }

    fallback_roots = _normalizar_raizes_categoria([], categorias_fallback)
    return {"roots": fallback_roots, "children": {}}


def _ensure_ml_subcategories(catalog, parent_id):
    pid = str(parent_id or "").strip().upper()
    if not pid:
        return []

    children_map = catalog.setdefault("children", {})
    return children_map.get(pid) or []


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tipwindow is not None:
            return

        texto = self.text() if callable(self.text) else self.text
        if not texto:
            texto = "Sem informacoes disponiveis."

        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 18
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=texto,
            justify=tk.LEFT,
            background="#fffff0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=8,
            pady=5,
        )
        label.pack(ipadx=1)

    def hide(self, _event=None):
        tw = self.tipwindow
        self.tipwindow = None
        if tw is not None:
            tw.destroy()


def parse_float(value, field_name):
    text = ("" if value is None else str(value)).strip()
    if not text:
        return None

    # Aceita formatos como: 52,0 | 52.0 | 1.234,56 | 1,234.56 | R$ 52,00
    cleaned = re.sub(r"[^0-9,\.\-]", "", text)
    if cleaned in {"", "-", ".", ","}:
        raise ValueError(f"Campo '{field_name}' deve ser numerico.")

    negative = cleaned.startswith("-")
    cleaned = cleaned.replace("-", "")

    has_comma = "," in cleaned
    has_dot = "." in cleaned

    if has_comma and has_dot:
        # Usa o separador mais a direita como decimal e remove o outro como milhar.
        if cleaned.rfind(",") > cleaned.rfind("."):
            normalized = cleaned.replace(".", "").replace(",", ".")
        else:
            normalized = cleaned.replace(",", "")
    elif has_comma:
        if cleaned.count(",") > 1:
            head, tail = cleaned.rsplit(",", 1)
            normalized = head.replace(",", "") + "." + tail
        else:
            normalized = cleaned.replace(",", ".")
    elif has_dot:
        if cleaned.count(".") > 1:
            head, tail = cleaned.rsplit(".", 1)
            normalized = head.replace(".", "") + "." + tail
        else:
            # Heuristica BR: 1.234 geralmente representa milhar, nao decimal.
            inteiro, decimal = cleaned.split(".", 1)
            if len(decimal) == 3 and len(inteiro) >= 1:
                normalized = inteiro + decimal
            else:
                normalized = cleaned
    else:
        normalized = cleaned

    if negative:
        normalized = f"-{normalized}"

    try:
        return float(normalized)
    except ValueError as exc:
        raise ValueError(f"Campo '{field_name}' deve ser numerico.") from exc


def parse_int(value, field_name):
    text = (value or "").strip()
    if not text:
        return None

    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"Campo '{field_name}' deve ser inteiro.") from exc


def load_categories(categorias_arquivo):
    categorias = list(DEFAULT_CATEGORIES)

    try:
        with open(categorias_arquivo, "r", encoding="utf-8") as file:
            for line in file:
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue

                parts = raw.split("|", 1)
                if len(parts) != 2:
                    continue

                categoria = parts[1].strip()
                if categoria:
                    categorias.append(categoria)
    except FileNotFoundError:
        return sorted(categorias, key=str.casefold)

    seen = set()
    unique = []
    for categoria in categorias:
        key = categoria.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(categoria)

    return sorted(unique, key=str.casefold)


def _parse_brl_price(text):
    raw = (text or "").strip()
    if not raw:
        return None

    match = re.search(r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+[\.,]\d{2}|\d+)", raw)
    if not match:
        return None

    number = match.group(1)
    if "," in number and "." in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", number):
        number = number.replace(".", "")

    try:
        return float(number)
    except ValueError:
        return None


def _detect_marketplace_from_url(url):
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if "mercadolivre.com" in host or "mercadolibre.com" in host:
        return "mercadolivre"

    return "generic"


def _classes_of_tag(tag):
    return [str(c).strip() for c in (tag.get("class") or []) if str(c).strip()]


def _has_price_old_markers(tag):
    classes = _classes_of_tag(tag)
    joined = " ".join(classes).casefold()
    return (
        "previous" in joined
        or "original-value" in joined
        or "price-old" in joined
        or "ui-pdp-price__part--original-value" in classes
        or "andes-money-amount--previous" in classes
    )


def _extract_value_from_money_amount(money_tag):
    if money_tag is None:
        return None

    fraction = (
        money_tag.select_one("span.andes-money-amount__fraction")
        or money_tag.select_one("[data-andes-money-amount-fraction='true']")
    )
    cents = (
        money_tag.select_one("span.andes-money-amount__cents")
        or money_tag.select_one("[data-andes-money-amount-cents='true']")
    )
    fraction_text = fraction.get_text("", strip=True) if fraction else ""
    cents_text = cents.get_text("", strip=True) if cents else ""

    raw = (fraction_text or "").strip()
    if cents_text:
        raw = f"{raw},{cents_text.strip()}"

    return _parse_brl_price(raw)


def _resolve_ml_main_price_scope(soup):
    return soup.select_one("div.ui-pdp-price__main-container")


def _extract_price_pair_from_soup_mercadolivre(soup):
    price_scope = _resolve_ml_main_price_scope(soup)
    source_root = price_scope if price_scope is not None else soup

    price_before = None
    previous_money_selectors = [
        ".ui-pdp-price__part--original-value .andes-money-amount",
        ".ui-pdp-price__original-value .andes-money-amount",
        ".andes-money-amount--previous",
    ]
    for selector in previous_money_selectors:
        for money in source_root.select(selector):
            value = _extract_value_from_money_amount(money)
            if value is not None:
                price_before = value
                break
        if price_before is not None:
            break

    price_after = None

    if price_scope is not None:
        meta_price = price_scope.select_one(
            ".ui-pdp-price__second-line meta[itemprop='price'], meta[itemprop='price']"
        )
        if meta_price is not None:
            price_after = _parse_brl_price(meta_price.get("content", ""))

    preferred_money_selectors = [
        ".ui-pdp-price__second-line .andes-money-amount",
        "[data-testid='price-part']:not(.ui-pdp-price__part--original-value) .andes-money-amount",
        ".ui-pdp-price .andes-money-amount",
    ]
    for selector in preferred_money_selectors:
        for money in source_root.select(selector):
            if any(_has_price_old_markers(parent) for parent in [money] + list(money.parents)):
                continue

            value = _extract_value_from_money_amount(money)
            if value is not None:
                price_after = value
                break
        if price_after is not None:
            break

    if price_before is None or price_after is None:
        old_values = []
        current_values = []

        for element in source_root.select("span.andes-money-amount__fraction"):
            value = _parse_brl_price(element.get_text(" ", strip=True))
            if value is None:
                continue

            if any(_has_price_old_markers(parent) for parent in [element] + list(element.parents)):
                old_values.append(value)
            else:
                current_values.append(value)

        if price_before is None and old_values:
            price_before = old_values[0]

        if price_after is None and current_values:
            price_after = current_values[0]

        if (
            price_scope is None
            and (price_before is None or price_after is None)
            and not old_values
            and len(current_values) >= 2
        ):
            maiores = sorted(current_values, reverse=True)
            if price_before is None:
                price_before = maiores[0]
            if price_after is None:
                price_after = maiores[-1]

    if price_before is not None and price_after is not None and price_before < price_after:
        price_before, price_after = price_after, price_before

    return price_after, price_before


def _extract_price_from_soup_mercadolivre(soup):
    price_after, _ = _extract_price_pair_from_soup_mercadolivre(soup)
    return price_after


def _extract_price_from_soup_generic(soup):
    meta_candidates = [
        "meta[property='product:price:amount']",
        "meta[itemprop='price']",
    ]
    for selector in meta_candidates:
        element = soup.select_one(selector)
        if element:
            content = element.get("content", "")
            price = _parse_brl_price(content)
            if price is not None:
                return price

    text_candidates = [
        "[itemprop='price']",
        "[data-testid='price-part']",
        "[data-andes-money-amount='true']",
        ".andes-money-amount",
        ".ui-search-price__second-line",
        ".poly-price__current",
        ".a-price .a-offscreen",
        ".priceToPay .a-offscreen",
    ]

    for selector in text_candidates:
        for element in soup.select(selector):
            price = _parse_brl_price(element.get_text(" ", strip=True))
            if price is not None:
                return price

    json_ld_blocks = soup.select("script[type='application/ld+json']")
    for block in json_ld_blocks:
        text = block.get_text("", strip=True)
        for pattern in [r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?', r'"lowPrice"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)"?']:
            found = re.search(pattern, text)
            if found:
                try:
                    return float(found.group(1))
                except ValueError:
                    continue

    # Fallback final: tenta capturar valores monetarios diretamente do texto.
    textos = soup.stripped_strings
    for texto in textos:
        if "R$" not in texto and "$" not in texto:
            continue

        price = _parse_brl_price(texto)
        if price is not None and price > 0:
            return price

    return None


def _extract_price_from_html(html, marketplace="generic"):
    soup = BeautifulSoup(html, "html.parser")

    if marketplace == "mercadolivre":
        price = _extract_price_from_soup_mercadolivre(soup)
        if price is not None:
            return price

    return _extract_price_from_soup_generic(soup)


def _extract_price_pair_from_html(html, marketplace="generic"):
    soup = BeautifulSoup(html, "html.parser")

    if marketplace == "mercadolivre":
        price_after, price_before = _extract_price_pair_from_soup_mercadolivre(soup)
        if price_after is not None:
            return price_after, price_before

    price = _extract_price_from_soup_generic(soup)
    return price, None


def _is_ml_challenge_html(html):
    if not html:
        return False

    lowered = html.lower()
    markers = [
        "_bmstate",
        "verifychallenge",
        "continue-button",
        "_bm_skipml",
    ]
    return any(marker in lowered for marker in markers)


def _prepare_ml_challenge_cookies(session):
    bmstate_raw = session.cookies.get("_bmstate")
    if not bmstate_raw:
        return False

    try:
        parts = unquote(bmstate_raw).split(";")
        seed = parts[0].strip()
        difficulty = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    except Exception:
        return False

    if not seed or difficulty < 0 or difficulty > 6:
        return False

    prefix = "0" * difficulty
    nonce = 0
    limit = 2_000_000
    while nonce < limit:
        digest = hashlib.sha256(f"{seed}{nonce}".encode("utf-8")).hexdigest()
        if digest.startswith(prefix):
            break
        nonce += 1

    if nonce >= limit:
        return False

    cookie_value = quote(f"{seed};{nonce}")
    for domain in ["mercadolivre.com.br", ".mercadolivre.com.br"]:
        session.cookies.set("_bmc", cookie_value, domain=domain, path="/")
        session.cookies.set("_bm_skipml", "true", domain=domain, path="/")

    return True


def _fetch_with_marketplace_handling(url):
    session = requests.Session()
    response = session.get(url, headers=HTTP_HEADERS, timeout=25)
    response.raise_for_status()

    marketplace = _detect_marketplace_from_url(response.url or url)
    if marketplace != "mercadolivre":
        return response, marketplace

    if _is_ml_challenge_html(response.text) and _prepare_ml_challenge_cookies(session):
        retry = session.get(response.url or url, headers=HTTP_HEADERS, timeout=25)
        retry.raise_for_status()
        return retry, marketplace

    return response, marketplace


def _is_ml_verification_response(response_url, html_text, title_text=""):
    url_text = (response_url or "").lower()
    title_norm = _normalize_text_for_match(title_text)

    if "account-verification" in url_text or "/gz/account-verification" in url_text:
        return True

    if title_norm in {"mercado libre", "mercado livre"}:
        return True

    return _is_ml_challenge_html(html_text)


def _fetch_price_and_title_from_url_via_browser(url):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None, url, "", None, None

    perfis = []
    candidatos = [
        BASE_DIR / "perfil_ml",
        BASE_DIR / "dist-interface" / "perfil_ml",
        Path.cwd() / "perfil_ml",
        Path.cwd() / "dist-interface" / "perfil_ml",
    ]

    for candidato in candidatos:
        caminho = str(candidato)
        if caminho not in perfis and candidato.exists():
            perfis.append(caminho)

    if not perfis:
        perfis.append(str(BASE_DIR / "perfil_ml"))

    for perfil_dir in perfis:
        for modo_headless in (True, False):
            launch_kwargs = dict(
                user_data_dir=perfil_dir,
                headless=modo_headless,
                slow_mo=0,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1366, "height": 768},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )

            if getattr(sys, "frozen", False):
                launch_kwargs["channel"] = "chrome"

            try:
                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(**launch_kwargs)
                    page = context.new_page()

                    page.goto(url, timeout=90000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1400)

                    html = page.content()
                    resolved_url = page.url or url
                    marketplace = _detect_marketplace_from_url(resolved_url)
                    title = _extract_title_from_html(html)
                    price, price_before = _extract_price_pair_from_html(html, marketplace=marketplace)

                    context.close()

                    if price is not None:
                        return price, resolved_url, title, price_before, price

                    if title:
                        return None, resolved_url, title, None, None
            except Exception:
                continue

    return None, url, "", None, None


def _extract_ml_item_id_from_url(url):
    texto = (url or "").upper()
    if not texto:
        return ""

    # Links de anúncio geralmente trazem MLB1234567890 no path ou query (wid/item_id).
    encontrado = re.search(r"\b(MLB\d{6,})\b", texto)
    if encontrado:
        return encontrado.group(1)

    return ""


def _fetch_price_and_title_from_ml_public_api(url):
    item_id = _extract_ml_item_id_from_url(url)
    if not item_id:
        return None, url, "", None, None

    endpoint = f"https://api.mercadolibre.com/items/{item_id}"

    try:
        response = requests.get(endpoint, headers=HTTP_HEADERS, timeout=25)
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception:
        return None, url, "", None, None

    preco = payload.get("price")
    titulo = (payload.get("title") or "").strip()
    permalink = (payload.get("permalink") or "").strip() or url

    try:
        preco_float = float(preco) if preco is not None else None
    except (TypeError, ValueError):
        preco_float = None

    price_before = None
    original_price = payload.get("original_price")
    try:
        if original_price is not None:
            price_before = float(original_price)
    except (TypeError, ValueError):
        price_before = None

    return preco_float, permalink, titulo, price_before, preco_float


def _extract_title_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

    for selector in ["h1.ui-pdp-title", ".ui-pdp-title", "meta[property='og:title']", "title"]:
        node = soup.select_one(selector)
        if not node:
            continue

        if node.name == "meta":
            title = (node.get("content") or "").strip()
        else:
            title = node.get_text(" ", strip=True)

        if title:
            return title

    return ""


def _fetch_price_from_url(url):
    response, marketplace = _fetch_with_marketplace_handling(url)
    price = _extract_price_from_html(response.text, marketplace=marketplace)
    return price, url


def _fetch_price_and_title_from_url(url):
    response, marketplace = _fetch_with_marketplace_handling(url)
    price, price_before = _extract_price_pair_from_html(response.text, marketplace=marketplace)
    title = _extract_title_from_html(response.text)

    if marketplace == "mercadolivre" and _is_ml_verification_response(response.url, response.text, title):
        browser_price, browser_url, browser_title, browser_before, browser_after = _fetch_price_and_title_from_url_via_browser(url)

        if browser_price is not None:
            return browser_price, browser_url, browser_title or title, browser_before, (browser_after or browser_price)

        api_price, api_url, api_title, api_before, api_after = _fetch_price_and_title_from_ml_public_api(url)
        if api_price is not None:
            return api_price, api_url, api_title or browser_title or title, api_before, (api_after or api_price)

        if browser_title or api_title:
            return price, (browser_url or api_url or response.url), (browser_title or api_title), price_before, price

    return price, response.url, title, price_before, price


def _fetch_price_from_description(description):
    terms = " ".join(part for part in [description] if part).strip()
    if not terms:
        return None, ""

    search_url = f"https://lista.mercadolivre.com.br/{quote_plus(terms)}"
    response = requests.get(search_url, headers=HTTP_HEADERS, timeout=25)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    best_price = None
    best_link = ""

    cards = soup.select("li.ui-search-layout__item, li.poly-card")
    for card in cards:
        price = _extract_price_from_card(card)
        if price is None:
            continue

        href_node = card.select_one("a.poly-component__title[href], a.ui-search-link[href], a[href]")
        href = href_node.get("href", "").strip() if href_node is not None else ""
        resolved_link = urljoin(response.url, href) if href else ""

        if best_price is None or price < best_price:
            best_price = price
            best_link = resolved_link

    if best_price is None:
        fallback_price = _extract_price_from_html(response.text)
        return fallback_price, (best_link or search_url)

    return best_price, (best_link or search_url)


def _build_affiliate_link(url_original):
    if not url_original:
        return ""

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return ""

    launch_kwargs = dict(
        user_data_dir=str(BASE_DIR / "perfil_ml"),
        headless=False,
        slow_mo=600,
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

    if getattr(sys, "frozen", False):
        launch_kwargs["channel"] = "chrome"

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(**launch_kwargs)
            page = context.new_page()
            page.goto(url_original, timeout=90000, wait_until="domcontentloaded")

            faixa_afiliados = page.locator("nav[aria-label='Afiliados'].stripe").first
            faixa_afiliados.wait_for(state="visible", timeout=12000)

            botao_compartilhar = faixa_afiliados.locator(
                "button[data-testid='generate_link_button']:has(span.andes-button__text:has-text('Compartilhar'))"
            ).first
            botao_compartilhar.wait_for(state="visible", timeout=12000)
            botao_compartilhar.click()

            popover = page.locator("div[data-testid='popper'].link-generator").first
            popover.wait_for(state="visible", timeout=12000)

            campo_link = popover.locator("textarea[data-testid='text-field__label_link']").first
            campo_link.wait_for(state="visible", timeout=12000)

            affiliate_link = ""
            for _ in range(6):
                affiliate_link = campo_link.input_value().strip()
                if affiliate_link and "meli.la" in affiliate_link:
                    break
                affiliate_link = ""
                page.wait_for_timeout(600)

            if not affiliate_link:
                botao_copiar = popover.locator("button[data-testid='copy-button__label_link']").first
                botao_copiar.wait_for(state="visible", timeout=8000)
                botao_copiar.click()
                page.wait_for_timeout(800)
                affiliate_link = campo_link.input_value().strip()

            if (not affiliate_link or "meli.la" not in affiliate_link):
                try:
                    clip = page.evaluate("navigator.clipboard.readText()")
                    if isinstance(clip, str) and "meli.la" in clip:
                        affiliate_link = clip.strip()
                except Exception:
                    pass

            page.keyboard.press("Escape")
            context.close()

        if affiliate_link and "meli.la" in affiliate_link:
            return affiliate_link
    except Exception:
        return ""

    return ""


def _normalize_text(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _normalize_text_for_match(value):
    texto = unicodedata.normalize("NFKD", str(value or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^a-zA-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip().casefold()


def _split_match_tokens(value):
    texto = _normalize_text_for_match(value)
    if not texto:
        return []

    tokens = []
    for token in texto.split(" "):
        if not token:
            continue

        # Mantem tokens numericos curtos (ex.: 64, 128) e palavras com 3+ chars.
        if token.isdigit() or len(token) >= 3:
            tokens.append(token)

    return tokens


def _description_matches_title(description, title):
    descricao_norm = _normalize_text_for_match(description)
    titulo_norm = _normalize_text_for_match(title)

    if not descricao_norm:
        return True

    if not titulo_norm:
        return False

    if descricao_norm in titulo_norm:
        return True

    tokens_desc = _split_match_tokens(descricao_norm)
    if not tokens_desc:
        return True

    acertos = 0
    for token in tokens_desc:
        if token in titulo_norm:
            acertos += 1

    proporcao_tokens = acertos / len(tokens_desc)

    if len(tokens_desc) <= 2 and acertos >= 1:
        return True

    if proporcao_tokens >= 0.55:
        return True

    similaridade = SequenceMatcher(None, descricao_norm, titulo_norm).ratio()
    return similaridade >= 0.72


def _extract_price_from_card(card):
    frac = card.select_one("[data-andes-money-amount-fraction='true']")
    cents = card.select_one("[data-andes-money-amount-cents='true']")
    if frac is not None:
        text_price = frac.get_text(" ", strip=True)
        if cents is not None:
            text_price = f"{text_price},{cents.get_text(' ', strip=True)}"
        parsed = _parse_brl_price(text_price)
        if parsed is not None:
            return parsed

    return _extract_price_from_html(str(card))


def _fetch_lowest_price_by_description_in_url(url, description):
    response = requests.get(url, headers=HTTP_HEADERS, timeout=25)
    response.raise_for_status()

    target = _normalize_text(description)
    if not target:
        return None, url

    soup = BeautifulSoup(response.text, "html.parser")
    cards = soup.select("li.ui-search-layout__item, li.poly-card, article")

    best_price = None
    best_link = ""

    for card in cards:
        title_node = card.select_one(
            "a.poly-component__title, h2.ui-search-item__title, .poly-component__title-wrapper, [title]"
        )
        title_text = ""
        if title_node is not None:
            title_text = (title_node.get_text(" ", strip=True) or title_node.get("title") or "").strip()

        if target and not _description_matches_title(target, title_text):
            continue

        price = _extract_price_from_card(card)
        if price is None:
            continue

        href_node = card.select_one("a.poly-component__title[href], a.ui-search-link[href], a[href]")
        href = href_node.get("href", "").strip() if href_node is not None else ""
        resolved_link = urljoin(response.url, href) if href else response.url

        if best_price is None or price < best_price:
            best_price = price
            best_link = resolved_link

    return best_price, (best_link or response.url)


def load_alerts_config(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        return []


def save_alerts_config(config_path, alerts):
    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(alerts, file, indent=2, ensure_ascii=False)


def load_hub_schedules_config(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception:
        return []


def save_hub_schedules_config(config_path, schedules):
    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(schedules, file, indent=2, ensure_ascii=False)


def _parse_iso_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def run_main_mode(forward_args):
    original_argv = list(sys.argv)
    previous_gui_mode = os.environ.get("PROMOS_GUI_MODE")
    try:
        os.environ["PROMOS_GUI_MODE"] = "1"
        sys.argv = ["main.py", *forward_args]
        if "main" in sys.modules:
            importlib.reload(sys.modules["main"])
        else:
            importlib.import_module("main")
    finally:
        sys.argv = original_argv
        if previous_gui_mode is None:
            os.environ.pop("PROMOS_GUI_MODE", None)
        else:
            os.environ["PROMOS_GUI_MODE"] = previous_gui_mode


def build_worker_command(args):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-main", *args]

    return [sys.executable, str(BASE_DIR / "gui_promos.py"), "--run-main", *args]


def build_worker_env():
    env = os.environ.copy()

    # Prevent onefile parent/child temp-dir conflicts when spawning the same exe.
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        env.pop("_MEIPASS2", None)

    return env


def build_styles(root):
    style = ttk.Style(root)
    # Use a consistent theme so custom colors remain readable across systems.
    style.theme_use("clam")

    bg = "#e8edf0"
    panel = "#ffffff"
    accent = "#2fa6bf"
    accent_active = "#1d8ea6"
    input_bg = "#f8fbfd"
    text_dark = "#3d4a53"
    text_muted = "#6b7782"
    border_soft = "#d5e0e7"

    root.configure(bg=bg)

    style.configure("Main.TFrame", background=bg)
    style.configure("Hero.TFrame", background=accent)
    style.configure("Card.TLabelframe", background=panel, bordercolor=border_soft, borderwidth=1, relief="flat")
    style.configure("Card.TLabelframe.Label", background=panel, foreground=accent, font=("Segoe UI Semibold", 11))
    style.configure("Header.TLabel", background=bg, foreground=accent, font=("Segoe UI", 22, "bold"))
    style.configure("Hint.TLabel", background=bg, foreground=text_muted, font=("Segoe UI", 10))
    style.configure("Field.TLabel", background=panel, foreground=text_dark, font=("Segoe UI", 10, "bold"))
    style.configure("HeroTitle.TLabel", background=accent, foreground="#ffffff", font=("Segoe UI", 18, "bold"))
    style.configure("HeroText.TLabel", background=accent, foreground="#eaf6fa", font=("Segoe UI", 10))
    style.configure("Info.TLabel", background=panel, foreground=accent, font=("Segoe UI", 10, "bold"))
    style.configure(
        "Action.TButton",
        background=accent,
        foreground="#ffffff",
        font=("Segoe UI", 10, "bold"),
        borderwidth=0,
        relief="flat",
        padding=(14, 8),
        focusthickness=0,
    )
    style.map(
        "Action.TButton",
        background=[("active", accent_active), ("pressed", accent_active), ("disabled", "#b8d9e1")],
        foreground=[("disabled", "#f2f6f8"), ("!disabled", "#ffffff")],
    )
    style.configure(
        "TEntry",
        fieldbackground=input_bg,
        background=input_bg,
        bordercolor=border_soft,
        lightcolor=border_soft,
        darkcolor=border_soft,
        borderwidth=1,
        relief="flat",
        padding=7,
    )
    style.configure(
        "TCombobox",
        fieldbackground=input_bg,
        background=input_bg,
        bordercolor=border_soft,
        lightcolor=border_soft,
        darkcolor=border_soft,
        relief="flat",
        padding=6,
    )
    style.configure("TCheckbutton", background=panel, foreground=text_dark, font=("Segoe UI", 10))
    style.configure(
        "Treeview",
        background="#ffffff",
        foreground="#26323a",
        fieldbackground="#ffffff",
        rowheight=24,
        bordercolor=border_soft,
        borderwidth=1,
    )
    style.map("Treeview", background=[("selected", "#d8eff5")], foreground=[("selected", "#1f2b33")])
    style.configure("Treeview.Heading", background="#eef4f7", foreground="#2f3c45", relief="flat")


def create_gui(categorias):
    root = tk.Tk()
    root.title("Promos - Interface")
    root.geometry("1160x760")
    root.minsize(1024, 700)

    build_styles(root)

    main_frame = ttk.Frame(root, style="Main.TFrame", padding=20)
    main_frame.pack(fill="both", expand=True)

    hero = ttk.Frame(main_frame, style="Hero.TFrame", padding=(14, 10))
    hero.pack(fill="x", pady=(0, 8))

    hero_left = ttk.Frame(hero, style="Hero.TFrame")
    hero_left.pack(side="left", fill="both", expand=True)

    ttk.Label(hero_left, text="PROMOS", style="HeroTitle.TLabel").pack(anchor="w")
    ttk.Label(
        hero_left,
        text="Automatize buscas no hub, relampago e programacoes com uma interface unica.",
        style="HeroText.TLabel",
    ).pack(anchor="w", pady=(4, 0))

    hero_right = ttk.Frame(hero, style="Hero.TFrame")
    hero_right.pack(side="right", padx=(20, 0))
    ttk.Label(hero_right, text="Painel de Operacao", style="HeroText.TLabel").pack(anchor="e")
    ttk.Label(hero_right, text="Mercado Livre", style="HeroTitle.TLabel").pack(anchor="e")

    ttk.Label(main_frame, text="Entre com os dados do processo no formulario.", style="Hint.TLabel").pack(anchor="w", pady=(0, 6))

    top = ttk.Frame(main_frame, style="Main.TFrame")
    top.pack(fill="x", expand=False, pady=(0, 4))

    product_frame = ttk.LabelFrame(top, text="PROCURAR PRODUTO", style="Card.TLabelframe", padding=8)
    product_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

    relampago_frame = ttk.LabelFrame(top, text="PROCURAR OFERTAS RELAMPAGO", style="Card.TLabelframe", padding=8)
    relampago_frame.pack(side="right", fill="both", expand=True, padx=(8, 0))

    descricao_var = tk.StringVar()
    preco_min_var = tk.StringVar()
    preco_max_var = tk.StringVar()
    desconto_var = tk.StringVar()
    limite_candidatos_prod_var = tk.StringVar()
    categoria_var = tk.StringVar(value="")
    subcategoria_var = tk.StringVar(value="")
    categoria_id_var = tk.StringVar(value="")
    subcategoria_id_var = tk.StringVar(value="")

    fontes_vars = {
        "Mercado Livre": tk.BooleanVar(value=True),
        "Amazon": tk.BooleanVar(value=False),
        "Shoppee": tk.BooleanVar(value=False),
        "Tiktok shop": tk.BooleanVar(value=False),
        "Todas": tk.BooleanVar(value=False),
    }

    rel_preco_min_var = tk.StringVar()
    rel_preco_max_var = tk.StringVar()
    rel_desconto_var = tk.StringVar()
    rel_limite_var = tk.StringVar()
    rel_descricao_var = tk.StringVar()
    rel_padrao_var = tk.BooleanVar(value=False)

    categories_catalog = _load_ml_categories_catalog(categorias)
    categorias_raiz = categories_catalog.get("roots") if isinstance(categories_catalog.get("roots"), list) else []
    categorias_raiz = _normalizar_raizes_categoria(categorias_raiz, categorias)

    map_categoria_nome_para_id = {
        _chave_nome_categoria(c.get("name") or ""): str(c.get("id") or "").strip().upper()
        for c in categorias_raiz
        if str(c.get("name") or "").strip()
    }
    categorias_prod_values = ["", *[str(c.get("name") or "") for c in categorias_raiz]]
    map_subcategoria_prod_nome_para_id = {}

    def _decimal_input_valido(texto):
        texto = (texto or "").strip()
        if not texto:
            return True
        return bool(re.fullmatch(r"\d+(?:[\.,]\d{0,2})?", texto))

    def _inteiro_input_valido(texto):
        texto = (texto or "").strip()
        return not texto or texto.isdigit()

    def _normalizar_varchar(var, limite=255):
        texto = (var.get() or "")
        texto_limpo = "".join(ch for ch in texto if ch >= " " or ch == "\t")
        if len(texto_limpo) > limite:
            texto_limpo = texto_limpo[:limite]
        if texto_limpo != texto:
            var.set(texto_limpo)

    def _formatar_decimal_em_var(var):
        texto = (var.get() or "").strip()
        if not texto:
            return

        try:
            valor = float(texto.replace(",", "."))
        except ValueError:
            return

        var.set(f"{valor:.2f}".replace(".", ","))

    vcmd_decimal = (root.register(_decimal_input_valido), "%P")
    vcmd_inteiro = (root.register(_inteiro_input_valido), "%P")

    descricao_var.trace_add("write", lambda *_: _normalizar_varchar(descricao_var))

    row = 0
    ttk.Label(product_frame, text="Descricao:", style="Field.TLabel").grid(row=row, column=0, sticky="w")
    desc_entry = ttk.Entry(product_frame, textvariable=descricao_var)
    desc_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6))
    info_icon = ttk.Label(product_frame, text="(i)", style="Info.TLabel", cursor="hand2")
    info_icon.grid(row=row, column=2, sticky="w")
    Tooltip(info_icon, "Descreva com o máximo de detalhes possíveis as caracterísiticas do produto desejado")

    row += 1
    ttk.Label(product_frame, text="MarketPlace:", style="Field.TLabel").grid(row=row, column=0, sticky="nw", pady=(6, 0))
    source_frame = ttk.Frame(product_frame, style="Card.TLabelframe")
    source_frame.grid(row=row, column=1, columnspan=2, sticky="w", pady=(6, 0))
    marketplace_info = ttk.Label(source_frame, text="(i)", style="Info.TLabel", cursor="hand2")
    marketplace_info.grid(row=0, column=0, padx=(0, 8), sticky="w")
    Tooltip(marketplace_info, "Marcar todas ou diversas caixas pode afetar o tempo de processamento")

    def on_toggle_all():
        if fontes_vars["Todas"].get():
            for nome, var in fontes_vars.items():
                if nome != "Todas":
                    var.set(True)

    def on_toggle_source():
        names = ["Mercado Livre", "Amazon", "Shoppee", "Tiktok shop"]
        if all(fontes_vars[name].get() for name in names):
            fontes_vars["Todas"].set(True)
        else:
            fontes_vars["Todas"].set(False)

    for idx, nome in enumerate(["Mercado Livre", "Amazon", "Shoppee", "Tiktok shop", "Todas"]):
        cmd = on_toggle_all if nome == "Todas" else on_toggle_source
        ttk.Checkbutton(source_frame, text=nome, variable=fontes_vars[nome], command=cmd).grid(row=0, column=idx + 1, padx=(0, 10), sticky="w")

    row += 1
    ttk.Label(product_frame, text="Categoria principal:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 0))
    categorias_combo = ttk.Combobox(product_frame, textvariable=categoria_var, values=categorias_prod_values, state="readonly")
    categorias_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(6, 0))

    row += 1
    ttk.Label(product_frame, text="Subcategoria:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 0))
    subcategorias_combo = ttk.Combobox(product_frame, textvariable=subcategoria_var, values=[""], state="disabled")
    subcategorias_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(6, 0))

    row += 1
    ttk.Label(product_frame, text="Preco minimo:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 0))
    preco_min_entry = ttk.Entry(
        product_frame,
        textvariable=preco_min_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    preco_min_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))

    row += 1
    ttk.Label(product_frame, text="Preco maximo:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 0))
    preco_max_entry = ttk.Entry(
        product_frame,
        textvariable=preco_max_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    preco_max_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))

    row += 1
    ttk.Label(product_frame, text="Desconto minimo (%):", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 0))
    desconto_entry = ttk.Entry(
        product_frame,
        textvariable=desconto_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    desconto_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))

    row += 1
    ttk.Label(product_frame, text="Limite de candidatos:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(6, 0))
    limite_candidatos_prod_entry = ttk.Entry(
        product_frame,
        textvariable=limite_candidatos_prod_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    limite_candidatos_prod_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(6, 0))

    row += 1
    buscar_produto_btn = ttk.Button(product_frame, text="BUSCAR PRODUTO", style="Action.TButton")
    buscar_produto_btn.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))

    row += 1
    ttk.Separator(product_frame, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 4))

    row += 1
    alerta_preco_btn = ttk.Button(product_frame, text="CONFIGURAR ALERTA DE PRECO", style="Action.TButton")
    alerta_preco_btn.grid(row=row, column=0, sticky="w", pady=(6, 0))

    campanha_produto_btn = ttk.Button(product_frame, text="CONFIGURAR CAMPANHA", style="Action.TButton")
    campanha_produto_btn.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

    for col in (1,):
        product_frame.columnconfigure(col, weight=1)

    rel_row = 0
    ttk.Label(relampago_frame, text="Descricao (opcional):", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(6, 0))
    rel_descricao_entry = ttk.Entry(relampago_frame, textvariable=rel_descricao_var)
    rel_descricao_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Preco minimo:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(6, 0))
    rel_preco_min_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_preco_min_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    rel_preco_min_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Preco maximo:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(6, 0))
    rel_preco_max_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_preco_max_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    rel_preco_max_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Desconto minimo (%):", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(6, 0))
    rel_desconto_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_desconto_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    rel_desconto_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Limite de candidatos:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(6, 0))
    rel_limite_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_limite_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    rel_limite_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

    for decimal_var, decimal_entry in [
        (preco_min_var, preco_min_entry),
        (preco_max_var, preco_max_entry),
        (rel_preco_min_var, rel_preco_min_entry),
        (rel_preco_max_var, rel_preco_max_entry),
    ]:
        decimal_entry.bind("<FocusOut>", lambda _e, var=decimal_var: _formatar_decimal_em_var(var))

    rel_row += 1
    rel_padrao_check = ttk.Checkbutton(relampago_frame, text="Usar modo relampago padrao", variable=rel_padrao_var)
    rel_padrao_check.grid(row=rel_row, column=0, sticky="w", pady=(6, 0))
    rel_padrao_info = ttk.Label(relampago_frame, text="(i)", style="Info.TLabel", cursor="hand2")
    rel_padrao_info.grid(row=rel_row, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
    Tooltip(rel_padrao_info, "O modo padrão busca 10 ofertas relâmpago sem especificar categoria, desconto, descrição ou faixa de preço")

    relampago_inputs = [
        rel_descricao_entry,
        rel_preco_min_entry,
        rel_preco_max_entry,
        rel_desconto_entry,
        rel_limite_entry,
    ]

    def _atualizar_subcategorias_produto(parent_id):
        subcategoria_var.set("")
        subcategoria_id_var.set("")
        map_subcategoria_prod_nome_para_id.clear()

        pid = str(parent_id or "").strip().upper()
        if not pid:
            subcategorias_combo.configure(values=[""], state="disabled")
            return

        children = _ensure_ml_subcategories(categories_catalog, pid)
        nomes = [str(item.get("name") or "").strip() for item in children if str(item.get("name") or "").strip()]
        map_subcategoria_prod_nome_para_id.update(
            {
                str(item.get("name") or "").strip(): str(item.get("id") or "").strip().upper()
                for item in children
                if str(item.get("name") or "").strip()
            }
        )

        if not nomes:
            subcategorias_combo.configure(values=[""], state="disabled")
            return

        subcategorias_combo.configure(values=["", *nomes], state="readonly")

    def _on_categoria_produto_change(_event=None):
        nome = (categoria_var.get() or "").strip()
        chave = _chave_nome_categoria(nome)
        cid = str(map_categoria_nome_para_id.get(chave) or "").strip().upper()

        categoria_id_var.set(cid)
        _atualizar_subcategorias_produto(cid)

    def _on_subcategoria_produto_change(_event=None):
        nome = (subcategoria_var.get() or "").strip()
        sid = str(map_subcategoria_prod_nome_para_id.get(nome) or "").strip().upper()
        subcategoria_id_var.set(sid)

    categorias_combo.bind("<<ComboboxSelected>>", _on_categoria_produto_change)
    subcategorias_combo.bind("<<ComboboxSelected>>", _on_subcategoria_produto_change)
    categoria_var.trace_add("write", lambda *_: _on_categoria_produto_change())
    subcategoria_var.trace_add("write", lambda *_: _on_subcategoria_produto_change())

    _on_categoria_produto_change()

    def atualizar_estado_campos_relampago():
        rel_padrao = bool(rel_padrao_var.get())
        estado_entrada = "disabled" if rel_padrao else "normal"

        for widget in [rel_descricao_entry, rel_preco_min_entry, rel_preco_max_entry, rel_desconto_entry, rel_limite_entry]:
            widget.configure(state=estado_entrada)

    rel_padrao_check.configure(command=atualizar_estado_campos_relampago)
    atualizar_estado_campos_relampago()

    rel_row += 1
    buscar_relampago_btn = ttk.Button(relampago_frame, text="BUSCAR OFERTAS RELAMPAGO", style="Action.TButton")
    buscar_relampago_btn.grid(row=rel_row, column=0, columnspan=2, sticky="w", pady=(10, 0))

    relampago_frame.columnconfigure(1, weight=1)

    output_frame = ttk.LabelFrame(main_frame, text="PAINEL DE EXECUCAO", style="Card.TLabelframe", padding=10)
    output_frame.pack(fill="both", expand=True, pady=(12, 0))
    status_var = tk.StringVar(value="Pronto para executar.")
    status_label = ttk.Label(output_frame, textvariable=status_var, style="Hint.TLabel", justify="left")
    status_label.pack(anchor="w", fill="x")

    log_path_var = tk.StringVar(value="Log salvo em: -")
    log_path_label = ttk.Label(output_frame, textvariable=log_path_var, style="Hint.TLabel", justify="left")
    log_path_label.pack(anchor="w", fill="x", pady=(6, 0))

    oauth_url_var = tk.StringVar(value="")
    oauth_status_var = tk.StringVar(value="OAuth URL: nao gerada")
    oauth_url_wrap = ttk.Frame(output_frame, style="Main.TFrame")
    oauth_url_wrap.pack(fill="x", expand=False, pady=(4, 0))
    ttk.Label(oauth_url_wrap, text="URL OAuth:", style="Hint.TLabel").pack(side="left")
    oauth_url_entry = ttk.Entry(oauth_url_wrap, textvariable=oauth_url_var, state="readonly")
    oauth_url_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
    open_oauth_url_btn = ttk.Button(oauth_url_wrap, text="Abrir URL")
    open_oauth_url_btn.pack(side="right", padx=(0, 6))
    copy_oauth_url_btn = ttk.Button(oauth_url_wrap, text="Copiar URL")
    copy_oauth_url_btn.pack(side="right")
    ttk.Label(output_frame, textvariable=oauth_status_var, style="Hint.TLabel", justify="left").pack(anchor="w", fill="x", pady=(2, 0))

    resumo_wrap = ttk.Frame(output_frame, style="Main.TFrame")
    resumo_wrap.pack(fill="both", expand=True, pady=(8, 0))

    resumo_text = tk.Text(
        resumo_wrap,
        height=10,
        wrap="word",
        background="#f6f6f6",
        foreground="#303030",
        borderwidth=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#d5e0e7",
        highlightcolor="#2fa6bf",
        insertwidth=0,
    )
    resumo_scroll = ttk.Scrollbar(resumo_wrap, orient="vertical", command=resumo_text.yview)
    resumo_text.configure(yscrollcommand=resumo_scroll.set)

    resumo_text.pack(side="left", fill="both", expand=True)
    resumo_scroll.pack(side="right", fill="y")
    resumo_text.configure(state="normal")

    def _ajustar_wrap_painel(_event=None):
        largura = max(220, output_frame.winfo_width() - 28)
        status_label.configure(wraplength=largura)
        log_path_label.configure(wraplength=largura)

    output_frame.bind("<Configure>", _ajustar_wrap_painel)
    _ajustar_wrap_painel()

    schedules_frame = ttk.LabelFrame(main_frame, text="PROGRAMACOES", style="Card.TLabelframe", padding=8)
    schedules_frame.pack(fill="both", expand=True, pady=(8, 0))
    output_frame.pack_forget()
    output_frame.pack(fill="both", expand=True, pady=(12, 0))

    schedules_actions = ttk.Frame(schedules_frame, style="Main.TFrame")
    schedules_actions.pack(fill="x", pady=(0, 6))

    alerta_config_btn = ttk.Button(schedules_actions, text="CONFIGURAR ALERTA DE PRECO", style="Action.TButton")
    alerta_config_btn.pack(side="left")

    campanha_config_btn = ttk.Button(schedules_actions, text="CONFIGURAR CAMPANHA", style="Action.TButton")
    campanha_config_btn.pack(side="left", padx=(8, 0))

    sync_sheet_now_btn = ttk.Button(schedules_actions, text="SINCRONIZAR PLANILHA AGORA", style="Action.TButton")
    sync_sheet_now_btn.pack(side="left", padx=(8, 0))

    selecionar_todas_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(schedules_actions, text="Selecionar todas", variable=selecionar_todas_var).pack(side="left", padx=(12, 0))
    delete_selected_btn = ttk.Button(schedules_actions, text="Excluir")
    delete_selected_btn.pack(side="left", padx=(8, 0))

    filtro_programacoes_var = tk.StringVar(value="")
    ttk.Label(schedules_actions, text="Buscar (ID/Nome):", style="Hint.TLabel").pack(side="left", padx=(18, 6))
    ttk.Entry(schedules_actions, textvariable=filtro_programacoes_var, width=28).pack(side="left")
    diagnostico_info_icon = ttk.Label(schedules_actions, text="(i)", style="Info.TLabel", cursor="hand2")
    diagnostico_info_icon.pack(side="left", padx=(8, 0))
    Tooltip(diagnostico_info_icon, lambda: _resumo_hover_diagnostico_execucao())

    grid_wrap = ttk.Frame(schedules_frame, style="Main.TFrame")
    grid_wrap.pack(fill="both", expand=True)

    hub_schedule_tree = ttk.Treeview(
        grid_wrap,
        columns=("sel", "ativo", "id", "nome", "tipo", "inicio", "fim", "ultima", "proxima", "ciclo", "execucao", "acoes"),
        show="headings",
        height=9,
    )

    hub_schedule_tree.heading("sel", text="Sel")
    hub_schedule_tree.heading("ativo", text="Ativo (toggle)")
    hub_schedule_tree.heading("id", text="ID")
    hub_schedule_tree.heading("nome", text="Nome")
    hub_schedule_tree.heading("tipo", text="Tipo")
    hub_schedule_tree.heading("inicio", text="Inicio")
    hub_schedule_tree.heading("fim", text="Fim")
    hub_schedule_tree.heading("ultima", text="Ultima")
    hub_schedule_tree.heading("proxima", text="Proxima")
    hub_schedule_tree.heading("ciclo", text="Ciclo")
    hub_schedule_tree.heading("execucao", text="Execucao")
    hub_schedule_tree.heading("acoes", text="Acoes")

    hub_schedule_tree.column("sel", width=44, anchor="center")
    hub_schedule_tree.column("ativo", width=88, anchor="center")
    hub_schedule_tree.column("id", width=80, anchor="center")
    hub_schedule_tree.column("nome", width=150, anchor="w")
    hub_schedule_tree.column("tipo", width=120, anchor="w")
    hub_schedule_tree.column("inicio", width=110, anchor="center")
    hub_schedule_tree.column("fim", width=110, anchor="center")
    hub_schedule_tree.column("ultima", width=120, anchor="w")
    hub_schedule_tree.column("proxima", width=120, anchor="w")
    hub_schedule_tree.column("ciclo", width=80, anchor="center")
    hub_schedule_tree.column("execucao", width=170, anchor="w")
    hub_schedule_tree.column("acoes", width=200, anchor="center")
    hub_schedule_tree.tag_configure("cfg_ativa", background="#33cc3d")
    hub_schedule_tree.tag_configure("cfg_inativa", background="#e3ee4f")
    hub_schedule_tree.tag_configure("cfg_falha", background="#ffd7d7", foreground="#7a1010")

    schedules_scroll = ttk.Scrollbar(grid_wrap, orient="vertical", command=hub_schedule_tree.yview)
    hub_schedule_tree.configure(yscrollcommand=schedules_scroll.set)
    hub_schedule_tree.pack(side="left", fill="both", expand=True)
    schedules_scroll.pack(side="right", fill="y")

    alerts = load_alerts_config(ALERTS_CONFIG_FILE)
    hub_schedules = load_hub_schedules_config(HUB_SCHEDULES_CONFIG_FILE)
    sheets_alerts_config = _load_sheets_alerts_config(SHEETS_ALERTS_CONFIG_FILE)
    scheduler_state = {"running": False, "running_id": None, "pending_ids": set()}
    alert_execution_queue = queue.Queue()
    sheets_sync_state = {"running": False, "next_run_at": datetime.now()}
    worker_running = {"value": False}
    worker_log = {"path": None}
    alert_log = {"path": None}
    sheet_sync_log = {"path": None}
    worker_messages = queue.Queue()
    alerts_lock = threading.Lock()

    def persist_hub_schedules():
        save_hub_schedules_config(HUB_SCHEDULES_CONFIG_FILE, hub_schedules)

    def persist_alerts():
        save_alerts_config(ALERTS_CONFIG_FILE, alerts)

    def _iniciar_log_alertas():
        ALERT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        data_ref = datetime.now().strftime("%Y%m%d")
        caminho = ALERT_LOGS_DIR / f"alertas_{data_ref}.log"

        if not caminho.exists():
            with open(caminho, "w", encoding="utf-8") as log_file:
                log_file.write(f"=== Inicio do log de alertas: {datetime.now().isoformat(timespec='seconds')} ===\n")

        alert_log["path"] = caminho
        return caminho

    def _iniciar_log_sincronizacao_planilha():
        SHEETS_SYNC_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        data_ref = datetime.now().strftime("%Y%m%d")
        caminho = SHEETS_SYNC_LOGS_DIR / f"sincronizacao_planilha_{data_ref}.log"

        if not caminho.exists():
            with open(caminho, "w", encoding="utf-8") as log_file:
                log_file.write(
                    f"=== Inicio do log de sincronizacao de planilha: {datetime.now().isoformat(timespec='seconds')} ===\n"
                )

        sheet_sync_log["path"] = caminho
        return caminho

    def _escrever_log_alerta(mensagem):
        try:
            caminho = alert_log.get("path") or _iniciar_log_alertas()
            with open(caminho, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mensagem}\n")
            log_path_var.set(f"Log salvo em: {caminho}")
        except Exception:
            pass

    def _escrever_log_sincronizacao_planilha(mensagem):
        try:
            caminho = sheet_sync_log.get("path") or _iniciar_log_sincronizacao_planilha()
            with open(caminho, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mensagem}\n")
            log_path_var.set(f"Log salvo em: {caminho}")
        except Exception:
            pass

    def _numero_destino_trial():
        return (_ler_variavel_ambiente("TWILIO_TRIAL_DESTINO") or TWILIO_TRIAL_DESTINO_PADRAO).strip()

    def _aplicar_destino_whatsapp_trial_em_cfg(cfg):
        numero_forcado = _numero_destino_trial()
        if not numero_forcado:
            return False

        phones_atual = [str(p).strip() for p in (cfg.get("phones") or []) if str(p).strip()]
        tel_atual = str(cfg.get("telefone") or "").strip()

        if phones_atual == [numero_forcado] and tel_atual == numero_forcado:
            return False

        cfg["phones"] = [numero_forcado]
        cfg["telefone"] = numero_forcado
        return True

    def _forcar_whatsapp_trial_nas_configs_ativas():
        if not TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS:
            return

        alterou_alertas = False
        alterou_campanhas = False

        for alert in alerts:
            if bool(alert.get("active", True)) and _aplicar_destino_whatsapp_trial_em_cfg(alert):
                alterou_alertas = True

        for schedule in hub_schedules:
            if bool(schedule.get("active", True)) and _aplicar_destino_whatsapp_trial_em_cfg(schedule):
                alterou_campanhas = True

        if alterou_alertas:
            persist_alerts()
        if alterou_campanhas:
            persist_hub_schedules()

        if alterou_alertas or alterou_campanhas:
            _escrever_log_alerta(
                f"Override trial aplicado para configs ativas. Destino WhatsApp forçado: {_numero_destino_trial()}."
            )

    def _ler_ultimas_linhas(caminho, max_linhas=120):
        try:
            if not caminho or not Path(caminho).exists():
                return []
            with open(caminho, "r", encoding="utf-8") as file:
                linhas = file.readlines()
            return [l.strip() for l in linhas[-max_linhas:] if l.strip()]
        except Exception:
            return []

    def _detectar_ultimo_log_execucao():
        try:
            candidatos = sorted(LOGS_DIR.glob("execucao_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidatos:
                return candidatos[0]
        except Exception:
            return None
        return None

    def _resumo_hover_diagnostico_execucao():
        caminho_alerta = alert_log.get("path") or _iniciar_log_alertas()
        caminho_execucao = worker_log.get("path") or _detectar_ultimo_log_execucao()

        linhas_alerta = _ler_ultimas_linhas(caminho_alerta, max_linhas=160)
        linhas_exec = _ler_ultimas_linhas(caminho_execucao, max_linhas=120)

        sem_disparo = sum(1 for l in linhas_alerta if "sem disparo nesta execucao" in l.casefold())
        sem_execucao = sum(
            1
            for l in linhas_alerta
            if (
                "nao executada" in l.casefold()
                or "campanha invalida" in l.casefold()
                or "desativado" in l.casefold()
                or "encerrado automaticamente" in l.casefold()
            )
        )
        falhas = sum(
            1
            for l in linhas_alerta
            if (
                "erro na checagem" in l.casefold()
                or "falhou" in l.casefold()
                or "falha ao extrair preco" in l.casefold()
            )
        )

        ultima_relevante = "-"
        for linha in reversed(linhas_alerta + linhas_exec):
            lcase = linha.casefold()
            if any(chave in lcase for chave in ["falha", "erro", "sem disparo", "nao executada", "invalida", "encerrado"]):
                ultima_relevante = linha
                break

        falhas_linha = []
        sem_disparo_linha = 0
        for item in _coletar_programacoes():
            cfg = item.get("cfg") or {}
            status_exec = str(cfg.get("last_execution_status") or "").strip().lower()
            mensagem_exec = str(cfg.get("last_execution_message") or "").strip()

            if status_exec == "falha":
                falhas_linha.append(
                    f"- {item.get('tipo')} {item.get('id')}: {item.get('nome')} -> {mensagem_exec or 'Falha na execucao.'}"
                )
            elif status_exec == "sem_disparo":
                sem_disparo_linha += 1

        falhas_linha_texto = "\n".join(falhas_linha) if falhas_linha else "- Nenhuma falha registrada por linha no GRID."

        return (
            "Diagnostico de execucao (logs):\n"
            f"- Sem disparo: {sem_disparo}\n"
            f"- Nao executou: {sem_execucao}\n"
            f"- Falhou: {falhas}\n"
            f"- Sem disparo por criterio (GRID): {sem_disparo_linha}\n"
            "\nFalhas por linha do GRID:\n"
            f"{falhas_linha_texto}\n"
            "\n"
            f"- Ultimo motivo: {ultima_relevante}\n"
            f"- Log alerta: {caminho_alerta}\n"
            f"- Log execucao: {caminho_execucao or '-'}"
        )

    def _registrar_resultado_execucao(cfg, status, mensagem=""):
        if not isinstance(cfg, dict):
            return

        cfg["last_execution_status"] = (status or "").strip().lower() or "desconhecido"
        cfg["last_execution_message"] = (mensagem or "").strip()
        cfg["last_execution_at"] = datetime.now().isoformat(timespec="seconds")

    def _enqueue_alert_execution(alert, source="scheduler"):
        if alert is None:
            return False

        if not bool(alert.get("active", True)):
            return False

        alert_id = str(alert.get("id", "")).strip()
        if not alert_id:
            return False

        if alert_id in scheduler_state["pending_ids"] or scheduler_state.get("running_id") == alert_id:
            _escrever_log_alerta(
                f"Alerta {alert_id} ignorado no enfileiramento ({source}): ja em execucao/fila."
            )
            return False

        scheduler_state["pending_ids"].add(alert_id)
        alert_execution_queue.put(alert_id)

        if source == "manual":
            status_var.set(f"Alerta enfileirado para execucao: {alert.get('name', 'Sem nome')}")

        _escrever_log_alerta(
            f"Alerta {alert_id} enfileirado ({source}) - nome: {alert.get('name', 'Sem nome')}."
        )

        return True

    def _run_next_alert_from_queue():
        if scheduler_state["running"]:
            return

        next_alert_id = None
        while not alert_execution_queue.empty():
            candidato_id = alert_execution_queue.get_nowait()
            _, alert_obj = _obter_programacao_por_key(_programacao_key("alerta", candidato_id))
            if alert_obj is not None and bool(alert_obj.get("active", True)):
                next_alert_id = candidato_id
                break

            scheduler_state["pending_ids"].discard(candidato_id)

        if not next_alert_id:
            return

        scheduler_state["running"] = True
        scheduler_state["running_id"] = next_alert_id
        _escrever_log_alerta(f"Iniciando execucao do alerta {next_alert_id}.")

        def worker(alert_ref):
            result = _check_alert_once(alert_ref)
            root.after(0, lambda: _finalize_alert_queue_execution(next_alert_id, [result]))

        _, alert_item = _obter_programacao_por_key(_programacao_key("alerta", next_alert_id))
        if alert_item is None:
            _escrever_log_alerta(
                f"Alerta {next_alert_id} removido/inativo antes da execucao."
            )
            _finalize_alert_queue_execution(next_alert_id, [])
            return

        threading.Thread(target=worker, args=(alert_item,), daemon=True).start()

    def _finalize_alert_queue_execution(alert_id, results):
        if results:
            _apply_alert_results(results, queue_finalize=False)

        _escrever_log_alerta(f"Finalizada execucao do alerta {alert_id}.")

        scheduler_state["pending_ids"].discard(str(alert_id))
        scheduler_state["running"] = False
        scheduler_state["running_id"] = None

        root.after(50, _run_next_alert_from_queue)

    def _proximo_id_configuracao():
        max_id = 0
        for cfg in [*alerts, *hub_schedules]:
            raw_id = str(cfg.get("id", "")).strip()
            if raw_id.isdigit():
                max_id = max(max_id, int(raw_id))
        return f"{max_id + 1:06d}"

    def _padronizar_formato_ids_configuracoes():
        alterou = False

        for cfg in [*alerts, *hub_schedules]:
            atual = str(cfg.get("id", "")).strip()
            if atual.isdigit() and len(atual) < 6:
                cfg["id"] = atual.zfill(6)
                alterou = True

        if alterou:
            save_alerts_config(ALERTS_CONFIG_FILE, alerts)
            save_hub_schedules_config(HUB_SCHEDULES_CONFIG_FILE, hub_schedules)

    def _target_price_from_alert(alert):
        if alert.get("precoDesejado") is not None:
            return float(alert.get("precoDesejado"))
        return float(alert.get("target_price", 0) or 0)

    def _urls_from_config(config):
        urls = [str(url).strip() for url in (config.get("urls") or []) if str(url).strip()]
        if urls:
            return urls[:5]

        links = []
        for idx in range(1, 6):
            link = str(config.get(f"link{idx}", "")).strip()
            if link:
                links.append(link)
        return links

    def _urls_from_alert(alert):
        return _urls_from_config(alert)

    def _normalizar_alertas_schema():
        alterou = False

        for alert in alerts:
            descricao = (alert.get("descricao") or alert.get("description") or "").strip()
            nome_atual = (alert.get("name") or "").strip()
            nome = nome_atual or descricao or "Alerta sem nome"

            urls = _urls_from_alert(alert)
            emails = alert.get("emails")
            if not isinstance(emails, list):
                emails = _split_destinos(alert.get("email", ""))
            emails = [str(e).strip() for e in emails if str(e).strip()][:1]

            phones = alert.get("phones")
            if not isinstance(phones, list):
                phones = _split_destinos(alert.get("telefone", ""))
            phones = [str(p).strip() for p in phones if str(p).strip()][:1]

            target_price = _target_price_from_alert(alert)
            configured_at = alert.get("configured_at") or alert.get("dt_criacao") or datetime.now().isoformat(timespec="seconds")
            end_at = alert.get("end_at")
            if not end_at:
                configured_dt = _parse_iso_datetime(configured_at) or datetime.now()
                end_at = (configured_dt + timedelta(days=ALERT_ACTIVE_DAYS_DEFAULT)).isoformat(timespec="seconds")

            novo_alerta = {
                **alert,
                "name": nome,
                "mode": "url",
                "description": descricao,
                "descricao": descricao,
                "target_price": target_price,
                "precoDesejado": target_price,
                "emails": emails,
                "email": (emails[0] if emails else ""),
                "phones": phones,
                "telefone": (phones[0] if phones else ""),
                "urls": urls,
                "interval_hours": ALERT_INTERVAL_HOURS_FIXED,
                "active": bool(alert.get("active", True)),
                "configured_at": configured_at,
                "end_at": end_at,
                "agendado": bool(alert.get("agendado", True)),
                "dt_criacao": alert.get("dt_criacao") or configured_at,
                "last_notified_at": alert.get("last_notified_at"),
                "first_triggered_at": alert.get("first_triggered_at"),
            }

            for idx in range(1, 6):
                novo_alerta[f"link{idx}"] = urls[idx - 1] if idx - 1 < len(urls) else ""

            if novo_alerta != alert:
                alert.clear()
                alert.update(novo_alerta)
                alterou = True

        if alterou:
            persist_alerts()

    def _normalizar_hub_schedules_schema():
        alterou = False

        for schedule in hub_schedules:
            urls = _urls_from_config(schedule)
            emails = schedule.get("emails")
            if not isinstance(emails, list):
                emails = _split_destinos(schedule.get("email", ""))
            emails = [str(e).strip() for e in emails if str(e).strip()][:1]

            phones = schedule.get("phones")
            if not isinstance(phones, list):
                phones = _split_destinos(schedule.get("telefone", ""))
            phones = [str(p).strip() for p in phones if str(p).strip()][:1]

            novo_schedule = {
                **schedule,
                "emails": emails,
                "email": (emails[0] if emails else ""),
                "phones": phones,
                "telefone": (phones[0] if phones else ""),
                "urls": urls,
                "active": bool(schedule.get("active", True)),
            }

            for idx in range(1, 6):
                novo_schedule[f"link{idx}"] = urls[idx - 1] if idx - 1 < len(urls) else ""

            if novo_schedule != schedule:
                schedule.clear()
                schedule.update(novo_schedule)
                alterou = True

        if alterou:
            persist_hub_schedules()

    def _parse_schedule_datetime_input(value, field_name, required=False, end_of_day=False):
        texto = (value or "").strip()
        if not texto:
            if required:
                raise ValueError(f"Campo '{field_name}' e obrigatorio.")
            return None

        try:
            data = datetime.strptime(texto, "%d/%m/%Y")
            if end_of_day:
                return data.replace(hour=23, minute=59, second=59)
            return data
        except ValueError:
            # Backward compatibility with previously saved/input formats.
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    data = datetime.strptime(texto, fmt)
                    if end_of_day:
                        return data.replace(hour=23, minute=59, second=59)
                    return data
                except ValueError:
                    continue
            raise ValueError(f"Campo '{field_name}' deve estar em DD/MM/AAAA.")

    def _abrir_seletor_data(parent, data_var, titulo="Selecionar data"):
        atual = _parse_schedule_datetime_input(data_var.get(), "Data", required=False)
        base = atual or datetime.now()

        popup = tk.Toplevel(parent)
        popup.title(titulo)
        popup.configure(bg="#ececec")
        popup.transient(parent)
        popup.grab_set()
        popup.resizable(False, False)

        frame = ttk.Frame(popup, style="Main.TFrame", padding=10)
        frame.pack(fill="both", expand=True)

        mes_ano_var = tk.StringVar()
        dias_frame = ttk.Frame(frame, style="Main.TFrame")
        dias_frame.pack(fill="both", expand=True, pady=(8, 0))

        state = {"year": base.year, "month": base.month}

        def _mes_anterior():
            if state["month"] == 1:
                state["month"] = 12
                state["year"] -= 1
            else:
                state["month"] -= 1
            _renderizar_calendario()

        def _mes_proximo():
            if state["month"] == 12:
                state["month"] = 1
                state["year"] += 1
            else:
                state["month"] += 1
            _renderizar_calendario()

        def _selecionar_dia(dia):
            escolhido = datetime(state["year"], state["month"], dia)
            data_var.set(escolhido.strftime("%d/%m/%Y"))
            popup.destroy()

        top = ttk.Frame(frame, style="Main.TFrame")
        top.pack(fill="x")
        ttk.Button(top, text="<", width=3, command=_mes_anterior).pack(side="left")
        ttk.Label(top, textvariable=mes_ano_var, style="Field.TLabel").pack(side="left", padx=8)
        ttk.Button(top, text=">", width=3, command=_mes_proximo).pack(side="left")

        def _renderizar_calendario():
            for child in dias_frame.winfo_children():
                child.destroy()

            nomes_dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
            for idx, nome in enumerate(nomes_dias):
                ttk.Label(dias_frame, text=nome, style="Hint.TLabel").grid(row=0, column=idx, padx=2, pady=(0, 4))

            mes_ano_var.set(f"{calendar.month_name[state['month']]} {state['year']}")
            first_weekday, qtd_dias = calendar.monthrange(state["year"], state["month"])

            linha = 1
            coluna = first_weekday
            for dia in range(1, qtd_dias + 1):
                ttk.Button(
                    dias_frame,
                    text=str(dia),
                    width=4,
                    command=lambda d=dia: _selecionar_dia(d),
                ).grid(row=linha, column=coluna, padx=2, pady=2)
                coluna += 1
                if coluna > 6:
                    coluna = 0
                    linha += 1

        _renderizar_calendario()
        popup.wait_visibility()
        popup.focus_force()

    def _formatar_data(valor_iso):
        dt = _parse_iso_datetime(valor_iso)
        if not dt:
            return "-"
        return dt.strftime("%d/%m/%Y")

    def _formatar_data_hora(valor_iso):
        dt = _parse_iso_datetime(valor_iso)
        if not dt:
            return "-"
        return dt.strftime("%d/%m/%Y %H:%M")

    programacoes_selecionadas = set()

    def _programacao_key(tipo, item_id):
        return f"{tipo}:{item_id}"

    def _pill_ativo(is_active):
        return "[ ON ]" if is_active else "[ OFF ]"

    def _formatar_data_hora_curta(value_dt):
        if not value_dt:
            return "-"
        return value_dt.strftime("%d/%m %H:%M")

    def _proxima_execucao_alerta(alert, now=None):
        now = now or datetime.now()
        if not alert.get("active", True):
            return "-"

        fim = _parse_iso_datetime(alert.get("end_at"))
        if fim and now > fim:
            return "-"

        next_check = _parse_iso_datetime(alert.get("next_check_at"))
        if next_check is not None:
            if now >= next_check:
                return "Agora"
            return _formatar_data_hora_curta(next_check)

        last_check = _parse_iso_datetime(alert.get("last_check_at"))
        intervalo_horas = max(1, int(alert.get("interval_hours", 1)))
        if last_check is None:
            return "Agora"

        return _formatar_data_hora_curta(last_check + timedelta(hours=intervalo_horas))

    def _proxima_execucao_campanha(schedule, now=None):
        now = now or datetime.now()
        if not schedule.get("active", True):
            return "-"

        next_run = _parse_iso_datetime(schedule.get("next_run_at"))
        if next_run is not None:
            if now >= next_run:
                return "Agora"
            return _formatar_data_hora_curta(next_run)

        inicio = _parse_iso_datetime(schedule.get("start_at"))
        fim = _parse_iso_datetime(schedule.get("end_at"))
        ultimo = _parse_iso_datetime(schedule.get("last_run_at"))
        intervalo_horas = max(1, int(schedule.get("interval_hours", 1)))

        if inicio and now < inicio:
            return _formatar_data_hora_curta(inicio)

        if ultimo is None:
            return "Agora"

        proxima = ultimo + timedelta(hours=intervalo_horas)
        if fim and proxima > fim:
            return "-"

        return _formatar_data_hora_curta(proxima)

    def _formatar_status_agendamento(schedule, now=None):
        now = now or datetime.now()

        status_exec = str(schedule.get("last_execution_status") or "").strip().lower()
        msg_exec = str(schedule.get("last_execution_message") or "").strip()
        if status_exec == "falha":
            return f"Falha: {msg_exec or 'erro de execucao'}"
        if status_exec == "sucesso":
            return f"Ultima execucao: {(_parse_iso_datetime(schedule.get('last_execution_at')) or now).strftime('%d/%m %H:%M')}"

        if not schedule.get("active", True):
            return "Inativo"

        inicio = _parse_iso_datetime(schedule.get("start_at"))
        fim = _parse_iso_datetime(schedule.get("end_at"))
        ultimo = _parse_iso_datetime(schedule.get("last_run_at"))

        if inicio and now < inicio:
            return "Aguardando inicio"
        if fim and now > fim:
            return "Encerrado"
        if ultimo:
            return f"Ultima execucao: {ultimo.strftime('%d/%m %H:%M')}"

        return "Pronto para executar"

    def _formatar_status_alerta(alert, now=None):
        now = now or datetime.now()

        status_exec = str(alert.get("last_execution_status") or "").strip().lower()
        msg_exec = str(alert.get("last_execution_message") or "").strip()
        if status_exec == "falha":
            return f"Falha: {msg_exec or 'erro de execucao'}"
        if status_exec == "sem_disparo":
            return "Sem disparo (criterios)"
        if status_exec == "sucesso":
            return "Disparo realizado"

        if not alert.get("active", True):
            return "Inativo"

        fim = _parse_iso_datetime(alert.get("end_at"))
        if fim and now > fim:
            return "Encerrado"

        last_check = _parse_iso_datetime(alert.get("last_check_at"))
        interval_hours = max(1, int(alert.get("interval_hours", 3)))

        if last_check is None:
            return "Pronto para executar"

        proxima = last_check + timedelta(hours=interval_hours)
        if now >= proxima:
            return "Aguardando ciclo"

        return f"Proxima: {proxima.strftime('%d/%m %H:%M')}"

    def _coletar_programacoes():
        itens = []

        for alert in alerts:
            aid = alert.get("id")
            itens.append(
                {
                    "key": _programacao_key("alerta", aid),
                    "id": str(aid),
                    "nome": alert.get("name", "Alerta sem nome"),
                    "tipo": "Alerta de preco",
                    "ativo": _pill_ativo(bool(alert.get("active", True))),
                    "inicio": _formatar_data(alert.get("configured_at")),
                    "fim": _formatar_data(alert.get("end_at")),
                    "ultima": _formatar_data_hora(alert.get("last_check_at")),
                    "proxima": _proxima_execucao_alerta(alert),
                    "ciclo": f"{int(alert.get('interval_hours', 1))}h",
                    "execucao": _formatar_status_alerta(alert),
                    "cfg": alert,
                }
            )

        for schedule in hub_schedules:
            sid = schedule.get("id")
            itens.append(
                {
                    "key": _programacao_key("campanha", sid),
                    "id": str(sid),
                    "nome": schedule.get("name", "Rotina sem nome"),
                    "tipo": "Campanha",
                    "ativo": _pill_ativo(bool(schedule.get("active", True))),
                    "inicio": _formatar_data(schedule.get("start_at")),
                    "fim": _formatar_data(schedule.get("end_at")),
                    "ultima": _formatar_data_hora(schedule.get("last_run_at")),
                    "proxima": _proxima_execucao_campanha(schedule),
                    "ciclo": f"{int(schedule.get('interval_hours', 1))}h",
                    "execucao": _formatar_status_agendamento(schedule),
                    "cfg": schedule,
                }
            )

        return itens

    def _filtrar_programacoes(itens):
        termo = (filtro_programacoes_var.get() or "").strip().casefold()
        if not termo:
            return itens

        filtrados = []
        for item in itens:
            alvo = f"{item.get('id', '')} {item.get('nome', '')}".casefold()
            if termo in alvo:
                filtrados.append(item)
        return filtrados

    def _refresh_hub_schedules_grid():
        for item_id in hub_schedule_tree.get_children():
            hub_schedule_tree.delete(item_id)

        itens = _filtrar_programacoes(_coletar_programacoes())
        if not itens:
            hub_schedule_tree.insert(
                "",
                "end",
                iid="empty-state",
                values=("", "", "", "Nenhuma configuracao cadastrada", "", "", "", "", "", "", "", ""),
            )
            return

        for item in itens:
            marcado = "☑" if item["key"] in programacoes_selecionadas else "☐"
            _, cfg = _obter_programacao_por_key(item["key"])
            ativo_cfg = bool((cfg or {}).get("active", True))
            status_exec = str((cfg or {}).get("last_execution_status") or "").strip().lower()
            if status_exec == "falha":
                tag_linha = "cfg_falha"
            else:
                tag_linha = "cfg_ativa" if ativo_cfg else "cfg_inativa"

            hub_schedule_tree.insert(
                "",
                "end",
                iid=item["key"],
                tags=(tag_linha,),
                values=(
                    marcado,
                    item["ativo"],
                    item["id"],
                    item["nome"],
                    item["tipo"],
                    item["inicio"],
                    item["fim"],
                    item["ultima"],
                    item["proxima"],
                    item["ciclo"],
                    item["execucao"],
                    "(i) | Editar | Excluir | Executar",
                ),
            )

    def _normalizar_proximas_execucoes():
        alterou_alertas = False
        alterou_rotinas = False
        agora = datetime.now()

        for alert in alerts:
            intervalo_horas = ALERT_INTERVAL_HOURS_FIXED
            if int(alert.get("interval_hours", ALERT_INTERVAL_HOURS_FIXED)) != ALERT_INTERVAL_HOURS_FIXED:
                alert["interval_hours"] = ALERT_INTERVAL_HOURS_FIXED
                alterou_alertas = True

            next_check = _parse_iso_datetime(alert.get("next_check_at"))
            if next_check is not None:
                continue

            last_check = _parse_iso_datetime(alert.get("last_check_at"))
            if last_check is not None:
                base = last_check
            else:
                base = _parse_iso_datetime(alert.get("configured_at")) or agora

            alert["next_check_at"] = (base + timedelta(hours=intervalo_horas)).isoformat(timespec="seconds")
            alterou_alertas = True

        for schedule in hub_schedules:
            intervalo_horas = max(1, int(schedule.get("interval_hours", 1)))
            next_run = _parse_iso_datetime(schedule.get("next_run_at"))
            if next_run is not None:
                continue

            ultimo = _parse_iso_datetime(schedule.get("last_run_at"))
            if ultimo is not None:
                base = ultimo
            else:
                base = _parse_iso_datetime(schedule.get("configured_at")) or agora

            schedule["next_run_at"] = (base + timedelta(hours=intervalo_horas)).isoformat(timespec="seconds")
            alterou_rotinas = True

        if alterou_alertas:
            persist_alerts()
        if alterou_rotinas:
            save_hub_schedules_config(HUB_SCHEDULES_CONFIG_FILE, hub_schedules)

    def _sheet_get_cell(row_values, index):
        if index < len(row_values):
            return str(row_values[index]).strip()
        return ""

    def _sheet_row_to_alert(row_values, row_number):
        carimbo = _sheet_get_cell(row_values, 0)
        email = _sheet_get_cell(row_values, 1)
        descricao = _sheet_get_cell(row_values, 3)
        preco_desejado_raw = _sheet_get_cell(row_values, 4)
        link1 = _sheet_get_cell(row_values, 5)
        telefone = _sheet_get_cell(row_values, 6)
        link2 = _sheet_get_cell(row_values, 8)
        link3 = _sheet_get_cell(row_values, 10)
        link4 = _sheet_get_cell(row_values, 12)
        link5 = _sheet_get_cell(row_values, 14)

        if not descricao:
            raise ValueError("Descricao do produto nao informada (coluna D).")

        preco_desejado = parse_float(preco_desejado_raw, "Preco desejado")
        if preco_desejado is None or preco_desejado <= 0:
            raise ValueError("Preco desejado invalido (coluna E).")

        links = [l for l in [link1, link2, link3, link4, link5] if l]
        if not links:
            raise ValueError("Informe ao menos um link entre as colunas F/I/K/M/O.")

        if not email and not telefone:
            raise ValueError("Informe email (coluna B) e/ou telefone (coluna G).")

        email_unico, emails = _single_destino(email)
        telefone_unico, phones = _single_destino(telefone)

        if email and len(_split_destinos(email)) > 1:
            raise ValueError("A coluna B deve conter apenas 1 e-mail.")

        if telefone and len(_split_destinos(telefone)) > 1:
            raise ValueError("A coluna G deve conter apenas 1 telefone.")

        agora = datetime.now().isoformat(timespec="seconds")
        alert_id = _proximo_id_configuracao()
        alert = {
            "id": alert_id,
            "source": "planilha",
            "sheet_row_number": row_number,
            "name": descricao,
            "description": descricao,
            "descricao": descricao,
            "mode": "url",
            "target_price": float(preco_desejado),
            "precoDesejado": float(preco_desejado),
            "email": email_unico,
            "emails": emails,
            "telefone": telefone_unico,
            "phones": phones,
            "link1": link1,
            "link2": link2,
            "link3": link3,
            "link4": link4,
            "link5": link5,
            "urls": links,
            "agendado": True,
            "dt_criacao": agora,
            "carimbo_data_hora": carimbo,
            "active": True,
            "interval_hours": ALERT_INTERVAL_HOURS_FIXED,
            "last_check_at": None,
            "next_check_at": (datetime.now() + timedelta(hours=ALERT_INTERVAL_HOURS_FIXED)).isoformat(timespec="seconds"),
            "configured_at": agora,
            "end_at": (datetime.now() + timedelta(days=ALERT_ACTIVE_DAYS_DEFAULT)).isoformat(timespec="seconds"),
            "last_notified_price": None,
            "last_notified_at": None,
            "first_triggered_at": None,
        }
        return alert

    def _sheet_mark_row_imported(client, spreadsheet_id, worksheet_name, row_number, dt_criacao):
        range_write = _sheet_a1_range(worksheet_name, f"Q{row_number}:R{row_number}")
        values = [["true", dt_criacao]]
        (
            client.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_write,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            )
            .execute()
        )

    def _import_alerts_from_sheet_once():
        _maybe_breakpoint("_import_alerts_from_sheet_once.entry")
        _escrever_log_sincronizacao_planilha("Inicio da rotina de sincronizacao da planilha.")

        if sheets_sync_state["running"]:
            _escrever_log_sincronizacao_planilha("Sincronizacao ignorada: ja existe execucao em andamento.")
            _append_resumo(
                f"[{datetime.now().strftime('%H:%M:%S')}] Sincronizacao da planilha ja esta em andamento.\n"
            )
            return

        if not sheets_alerts_config.get("enabled", False):
            _escrever_log_sincronizacao_planilha("Sincronizacao ignorada: integracao desativada.")
            return

        spreadsheet_id = (sheets_alerts_config.get("spreadsheet_id") or "").strip()
        if not spreadsheet_id:
            spreadsheet_id = _spreadsheet_id_from_url(sheets_alerts_config.get("spreadsheet_url"))
        worksheet_name = (sheets_alerts_config.get("worksheet_name") or "RespostasForm").strip()
        auth_mode = (sheets_alerts_config.get("auth_mode") or "oauth_user").strip().lower()

        if not spreadsheet_id:
            _escrever_log_sincronizacao_planilha("Sincronizacao ignorada: spreadsheet_id ausente.")
            return

        if auth_mode == "service_account":
            service_account_path = _resolve_config_file_path(sheets_alerts_config.get("service_account_file"))
            if service_account_path is None or not service_account_path.exists():
                _escrever_log_sincronizacao_planilha(
                    f"Sincronizacao ignorada: service account ausente ({service_account_path or '[vazio]'})."
                )
                _append_resumo(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Integracao da planilha ignorada: arquivo de service account nao encontrado ({service_account_path or '[vazio]'}).\n"
                )
                return
        else:
            oauth_client_path = _resolve_config_file_path(sheets_alerts_config.get("oauth_client_file"))
            if oauth_client_path is None or not oauth_client_path.exists():
                _escrever_log_sincronizacao_planilha(
                    f"Sincronizacao ignorada: oauth client ausente ({oauth_client_path or '[vazio]'})."
                )
                _append_resumo(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Integracao da planilha ignorada: arquivo OAuth client secret nao encontrado ({oauth_client_path or '[vazio]'}).\n"
                )
                return

        sheets_sync_state["running"] = True

        def worker():
            mensagens = []
            importados = 0
            falhou = False
            worksheet_name_resolvido = worksheet_name

            def _registrar_progresso_sync(mensagem):
                _escrever_log_sincronizacao_planilha(mensagem)
                root.after(0, lambda: status_var.set(mensagem))
                root.after(0, lambda: _append_resumo(f"[{datetime.now().strftime('%H:%M:%S')}] {mensagem}\n"))

            try:
                _escrever_log_sincronizacao_planilha(
                    f"Worker iniciado. worksheet='{worksheet_name}' auth_mode='{auth_mode}' spreadsheet_id='{spreadsheet_id}'."
                )
                client = _load_google_sheets_client(sheets_alerts_config, progress_callback=_registrar_progresso_sync)
                worksheet_name_resolvido = _sheet_resolver_nome_aba(client, spreadsheet_id, worksheet_name)
                if worksheet_name_resolvido != worksheet_name:
                    _escrever_log_sincronizacao_planilha(
                        f"Aba resolvida automaticamente: configurada='{worksheet_name}' usada='{worksheet_name_resolvido}'."
                    )

                range_read = _sheet_a1_range(worksheet_name_resolvido, "A2:R")
                response = (
                    client.spreadsheets()
                    .values()
                    .get(spreadsheetId=spreadsheet_id, range=range_read)
                    .execute()
                )
                values = response.get("values", [])
                _escrever_log_sincronizacao_planilha(f"Leitura da planilha concluida. Linhas recebidas: {len(values)}.")

                for idx, row_values in enumerate(values, start=2):
                    agendado_valor = _sheet_get_cell(row_values, 16)
                    if _str_to_bool(agendado_valor):
                        continue

                    with alerts_lock:
                        ja_importado = any(
                            str(a.get("source", "")).strip().lower() == "planilha"
                            and str(a.get("sheet_row_number", "")).strip().isdigit()
                            and int(str(a.get("sheet_row_number", "")).strip()) == idx
                            for a in alerts
                        )

                    if ja_importado:
                        continue

                    try:
                        alert = _sheet_row_to_alert(row_values, idx)
                    except Exception as exc:
                        _escrever_log_sincronizacao_planilha(f"Linha {idx} invalida: {exc}.")
                        mensagens.append(f"Linha {idx}: erro de validacao ({exc}).")
                        continue

                    if TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS and bool(alert.get("active", True)):
                        _aplicar_destino_whatsapp_trial_em_cfg(alert)

                    with alerts_lock:
                        alerts.append(alert)
                        persist_alerts()
                        # Executa a configuração recém-importada
                        key = f"alerta:{alert.get('id')}"
                        try:
                            _executar_programacao_agora(key)
                        except Exception as e:
                            _escrever_log_sincronizacao_planilha(f"Falha ao executar alerta importado (ID {alert.get('id', '-')}) automaticamente: {e}")

                    _sheet_mark_row_imported(
                        client,
                        spreadsheet_id,
                        worksheet_name_resolvido,
                        idx,
                        alert["dt_criacao"],
                    )
                    importados += 1
                    _escrever_log_sincronizacao_planilha(
                        f"Linha {idx} importada com sucesso. Alerta ID {alert.get('id', '-')}"
                    )

                if importados:
                    _escrever_log_sincronizacao_planilha(f"Importacao concluida com {importados} alerta(s).")
                    mensagens.append(f"{importados} alerta(s) importado(s) da planilha.")
            except ImportError:
                falhou = True
                _escrever_log_sincronizacao_planilha("Falha por dependencias ausentes do Google.")
                mensagens.append(
                    "Dependencias Google nao instaladas para integrar planilha. Instale: google-api-python-client google-auth google-auth-oauthlib"
                )
            except Exception as exc:
                falhou = True
                _escrever_log_sincronizacao_planilha(f"Falha na importacao da planilha: {exc}")
                mensagens.append(f"Falha na importacao da planilha: {exc}")
            finally:
                def finalize():
                    sheets_sync_state["running"] = False
                    sheets_sync_state["next_run_at"] = datetime.now() + timedelta(minutes=ALERTS_IMPORT_INTERVAL_MINUTES)

                    if falhou:
                        status_var.set("Falha na sincronizacao manual da planilha.")
                    elif importados:
                        status_var.set(f"Sincronizacao concluida: {importados} alerta(s) importado(s).")
                    else:
                        status_var.set("Sincronizacao concluida: nenhuma nova linha para importar.")

                    if not mensagens and importados == 0:
                        mensagens.append("Nenhuma nova linha elegivel para importar da planilha.")
                        _escrever_log_sincronizacao_planilha("Nenhuma nova linha elegivel para importacao.")

                    if mensagens:
                        for mensagem in mensagens:
                            _escrever_log_sincronizacao_planilha(mensagem)
                            _append_resumo(f"[{datetime.now().strftime('%H:%M:%S')}] {mensagem}\n")
                    if importados:
                        _refresh_hub_schedules_grid()

                    _escrever_log_sincronizacao_planilha(
                        f"Finalizacao da sincronizacao. falhou={falhou} importados={importados}."
                    )

                root.after(0, finalize)

        threading.Thread(target=worker, daemon=True).start()

    def _obter_programacao_por_key(key):
        if not key or ":" not in key:
            return None, None

        tipo, raw_id = key.split(":", 1)
        if tipo == "alerta":
            for alert in alerts:
                if str(alert.get("id")) == raw_id:
                    return "alerta", alert
        elif tipo == "campanha":
            for schedule in hub_schedules:
                if str(schedule.get("id")) == raw_id:
                    return "campanha", schedule

        return None, None

    def _toggle_select_all_programacoes():
        marcar_todas = bool(selecionar_todas_var.get())
        programacoes_selecionadas.clear()
        if marcar_todas:
            for item in _coletar_programacoes():
                programacoes_selecionadas.add(item["key"])
        _refresh_hub_schedules_grid()

    selecionar_todas_var.trace_add("write", lambda *_: _toggle_select_all_programacoes())
    filtro_programacoes_var.trace_add("write", lambda *_: _refresh_hub_schedules_grid())

    def _build_hub_args_from_values(categoria, descricao, preco_min, preco_max, desconto_min, limite_candidatos=None, urls=None):
        args = ["--produto-por-html"]

        for url in [str(item).strip() for item in (urls or []) if str(item).strip()][:5]:
            args.extend(["--url-produto", url])

        if categoria and categoria != "Todas categorias":
            args.extend(["--categoria", categoria])

        if descricao:
            args.extend(["--descricao-produto", descricao])

        if preco_min is not None:
            args.extend(["--preco-minimo", str(preco_min)])

        if preco_max is not None:
            args.extend(["--preco-maximo", str(preco_max)])

        if desconto_min is not None:
            args.extend(["--desconto-minimo", str(desconto_min)])

        if limite_candidatos is not None:
            args.extend(["--limite-candidatos", str(limite_candidatos)])

        return args

    def _build_hub_args_from_schedule(schedule):
        return _build_hub_args_from_values(
            (schedule.get("categoria") or "").strip(),
            (schedule.get("descricao") or "").strip(),
            schedule.get("preco_minimo"),
            schedule.get("preco_maximo"),
            schedule.get("desconto_minimo"),
            schedule.get("limite_candidatos"),
            _urls_from_config(schedule),
        )

    def open_hub_schedule_modal(schedule=None):
        modal = tk.Toplevel(root)
        modal.title("Configurar rotina programada do hub")
        modal.geometry("760x900")
        modal.minsize(700, 820)
        modal.configure(bg="#ececec")
        modal.transient(root)
        modal.grab_set()

        frame = ttk.Frame(modal, style="Main.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Rotina Programada - Busca no Hub", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        def _aplicar_mascara_data(var, lock):
            if lock["value"]:
                return

            lock["value"] = True
            try:
                digitos = re.sub(r"\D", "", var.get() or "")[:8]
                blocos = [
                    digitos[0:2],
                    digitos[2:4],
                    digitos[4:8],
                ]

                texto = ""
                if blocos[0]:
                    texto += blocos[0]
                if blocos[1]:
                    texto += f"/{blocos[1]}"
                if blocos[2]:
                    texto += f"/{blocos[2]}"

                if texto != var.get():
                    var.set(texto)
            finally:
                lock["value"] = False

        nome_var = tk.StringVar(value=(schedule.get("name", "") if schedule else ""))
        inicio_var = tk.StringVar(value=(
            _parse_iso_datetime(schedule.get("start_at")).strftime("%d/%m/%Y")
            if schedule and _parse_iso_datetime(schedule.get("start_at"))
            else ""
        ))
        fim_var = tk.StringVar(value=(
            _parse_iso_datetime(schedule.get("end_at")).strftime("%d/%m/%Y")
            if schedule and _parse_iso_datetime(schedule.get("end_at"))
            else ""
        ))
        ciclo_var = tk.StringVar(value=str(int(schedule.get("interval_hours", 1))) if schedule else "1")
        categoria_ag_var = tk.StringVar(value=(schedule.get("categoria") if schedule else "Todas categorias"))
        descricao_ag_var = tk.StringVar(value=(schedule.get("descricao", "") if schedule else ""))
        preco_min_ag_var = tk.StringVar(value=("" if not schedule or schedule.get("preco_minimo") is None else str(schedule.get("preco_minimo"))))
        preco_max_ag_var = tk.StringVar(value=("" if not schedule or schedule.get("preco_maximo") is None else str(schedule.get("preco_maximo"))))
        desconto_ag_var = tk.StringVar(value=("" if not schedule or schedule.get("desconto_minimo") is None else str(schedule.get("desconto_minimo"))))
        limite_candidatos_ag_var = tk.StringVar(value=(
            str(schedule.get("limite_candidatos") if schedule and schedule.get("limite_candidatos") is not None else 10)
        ))
        ativo_var = tk.BooleanVar(value=(bool(schedule.get("active", True)) if schedule else True))
        executar_ao_salvar_var = tk.BooleanVar(value=False)
        email_ag_var = tk.StringVar(
            value=(
                (schedule.get("email") or "; ".join(schedule.get("emails", [])))
                if schedule
                else ""
            )
        )
        telefone_ag_var = tk.StringVar(
            value=(
                (schedule.get("telefone") or "; ".join(schedule.get("phones", [])))
                if schedule
                else ""
            )
        )
        urls_campanha = _urls_from_config(schedule or {})
        while len(urls_campanha) < 5:
            urls_campanha.append("")
        link_vars = [tk.StringVar(value=urls_campanha[idx]) for idx in range(5)]

        inicio_lock = {"value": False}
        fim_lock = {"value": False}
        inicio_var.trace_add("write", lambda *_: _aplicar_mascara_data(inicio_var, inicio_lock))
        fim_var.trace_add("write", lambda *_: _aplicar_mascara_data(fim_var, fim_lock))

        ttk.Label(frame, text="Nome:", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=(14, 0))
        ttk.Entry(frame, textvariable=nome_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(14, 0))

        ttk.Label(frame, text="Inicio:", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        inicio_row = ttk.Frame(frame, style="Main.TFrame")
        inicio_row.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        ttk.Entry(inicio_row, textvariable=inicio_var).pack(side="left", fill="x", expand=True)
        ttk.Button(
            inicio_row,
            text="Calendario",
            command=lambda: _abrir_seletor_data(modal, inicio_var, "Selecionar inicio"),
        ).pack(side="left", padx=(8, 0))

        ttk.Label(frame, text="Fim:", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        fim_row = ttk.Frame(frame, style="Main.TFrame")
        fim_row.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        ttk.Entry(fim_row, textvariable=fim_var).pack(side="left", fill="x", expand=True)
        ttk.Button(
            fim_row,
            text="Calendario",
            command=lambda: _abrir_seletor_data(modal, fim_var, "Selecionar fim"),
        ).pack(side="left", padx=(8, 0))

        ttk.Label(frame, text="Executar a cada (horas):", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=ciclo_var, validate="key", validatecommand=vcmd_inteiro).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Categoria:", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Combobox(frame, textvariable=categoria_ag_var, values=["Todas categorias", *categorias], state="readonly").grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Descricao (opcional):", style="Field.TLabel").grid(row=6, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=descricao_ag_var).grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        for idx, link_var in enumerate(link_vars, start=1):
            ttk.Label(frame, text=f"Link {idx} (opcional):", style="Field.TLabel").grid(row=6 + idx, column=0, sticky="w", pady=(12, 0))
            ttk.Entry(frame, textvariable=link_var).grid(row=6 + idx, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Preco minimo (opcional):", style="Field.TLabel").grid(row=12, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=preco_min_ag_var).grid(row=12, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Preco maximo (opcional):", style="Field.TLabel").grid(row=13, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=preco_max_ag_var).grid(row=13, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Desconto minimo (%) opcional:", style="Field.TLabel").grid(row=14, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=desconto_ag_var).grid(row=14, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Qtd. candidatos validos:", style="Field.TLabel").grid(row=15, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=limite_candidatos_ag_var, validate="key", validatecommand=vcmd_inteiro).grid(row=15, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Se informado, o link tem prioridade de busca.", style="Hint.TLabel").grid(
            row=16,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(12, 0),
        )

        ttk.Checkbutton(frame, text="Rotina ativa", variable=ativo_var).grid(row=17, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Checkbutton(frame, text="Executar a primeira vez assim que salvar", variable=executar_ao_salvar_var).grid(row=18, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(frame, text="E-mail:", style="Field.TLabel").grid(row=19, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=email_ag_var).grid(row=19, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Telefone:", style="Field.TLabel").grid(row=20, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=telefone_ag_var).grid(row=20, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        botoes = ttk.Frame(frame, style="Main.TFrame")
        botoes.grid(row=21, column=0, columnspan=2, sticky="w", pady=(18, 0))

        def salvar_rotina():
            nome = (nome_var.get() or "").strip()

            try:
                if not nome:
                    raise ValueError("Campo 'Nome' e obrigatorio.")

                inicio_dt = _parse_schedule_datetime_input(inicio_var.get(), "Inicio", required=True)
                fim_dt = _parse_schedule_datetime_input(fim_var.get(), "Fim", required=True, end_of_day=True)
                ciclo_horas = parse_int(ciclo_var.get(), "Executar a cada (horas)")
                if ciclo_horas is None or ciclo_horas < 1:
                    raise ValueError("A rotina deve rodar no minimo a cada 1 hora.")

                preco_min = parse_float(preco_min_ag_var.get(), "Preco minimo")
                preco_max = parse_float(preco_max_ag_var.get(), "Preco maximo")
                desconto_min = parse_int(desconto_ag_var.get(), "Desconto minimo")
                limite_candidatos = parse_int(limite_candidatos_ag_var.get(), "Qtd. candidatos validos")
            except ValueError as exc:
                messagebox.showerror("Validacao", str(exc), parent=modal)
                return

            if limite_candidatos is None:
                limite_candidatos = 10
            if limite_candidatos < 1:
                messagebox.showerror("Validacao", "Qtd. candidatos validos deve ser no minimo 1.", parent=modal)
                return

            if fim_dt and fim_dt.date() < inicio_dt.date():
                messagebox.showerror("Validacao", "A data de fim nao pode ser menor que a data de inicio.", parent=modal)
                return

            categoria_valor = (categoria_ag_var.get() or "Todas categorias").strip() or "Todas categorias"
            descricao_valor = (descricao_ag_var.get() or "").strip()
            urls = [str(var.get()).strip() for var in link_vars if str(var.get()).strip()]
            invalidas = [url for url in urls if not url.startswith("http://") and not url.startswith("https://")]
            if invalidas:
                messagebox.showerror("Validacao", "Todos os links devem comecar com http:// ou https://.", parent=modal)
                return

            email_unico, emails = _single_destino(email_ag_var.get())
            telefone_unico, telefones = _single_destino(telefone_ag_var.get())
            agora = datetime.now()
            executar_agora = bool(executar_ao_salvar_var.get())
            link_map = {f"link{idx}": (urls[idx - 1] if idx - 1 < len(urls) else "") for idx in range(1, 6)}

            if len(_split_destinos(email_ag_var.get())) > 1:
                messagebox.showerror("Validacao", "Informe apenas 1 e-mail na rotina.", parent=modal)
                return

            if len(_split_destinos(telefone_ag_var.get())) > 1:
                messagebox.showerror("Validacao", "Informe apenas 1 telefone na rotina.", parent=modal)
                return

            if bool(ativo_var.get()) and TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS:
                numero_forcado = _numero_destino_trial()
                telefone_unico = numero_forcado
                telefones = [numero_forcado]

            if schedule is None:
                novo = {
                    "id": _proximo_id_configuracao(),
                    "name": nome,
                    "active": bool(ativo_var.get()),
                    "start_at": inicio_dt.isoformat(timespec="minutes"),
                    "end_at": fim_dt.isoformat(timespec="minutes") if fim_dt else None,
                    "interval_hours": int(ciclo_horas),
                    "categoria": categoria_valor,
                    "descricao": descricao_valor,
                    "urls": urls,
                    **link_map,
                    "email": email_unico,
                    "emails": emails,
                    "telefone": telefone_unico,
                    "phones": telefones,
                    "preco_minimo": preco_min,
                    "preco_maximo": preco_max,
                    "desconto_minimo": desconto_min,
                    "limite_candidatos": int(limite_candidatos),
                    "last_run_at": None,
                    "configured_at": agora.isoformat(timespec="seconds"),
                    "next_run_at": (agora + timedelta(hours=int(ciclo_horas))).isoformat(timespec="seconds"),
                }
                hub_schedules.append(novo)
                status_var.set(f"Rotina '{nome}' criada.")
                schedule_ref = novo
            else:
                schedule["name"] = nome
                schedule["active"] = bool(ativo_var.get())
                schedule["start_at"] = inicio_dt.isoformat(timespec="minutes")
                schedule["end_at"] = fim_dt.isoformat(timespec="minutes") if fim_dt else None
                schedule["interval_hours"] = int(ciclo_horas)
                schedule["categoria"] = categoria_valor
                schedule["descricao"] = descricao_valor
                schedule["urls"] = urls
                schedule.update(link_map)
                schedule["email"] = email_unico
                schedule["emails"] = emails
                schedule["telefone"] = telefone_unico
                schedule["phones"] = telefones
                schedule["preco_minimo"] = preco_min
                schedule["preco_maximo"] = preco_max
                schedule["desconto_minimo"] = desconto_min
                schedule["limite_candidatos"] = int(limite_candidatos)
                schedule["configured_at"] = agora.isoformat(timespec="seconds")
                schedule["last_run_at"] = None
                schedule["next_run_at"] = (agora + timedelta(hours=int(ciclo_horas))).isoformat(timespec="seconds")
                status_var.set(f"Rotina '{nome}' atualizada.")
                schedule_ref = schedule

            persist_hub_schedules()
            _refresh_hub_schedules_grid()
            modal.destroy()

            if executar_agora and schedule_ref.get("active", True):
                _executar_programacao_agora(_programacao_key("campanha", schedule_ref.get("id")))

        ttk.Button(botoes, text="Salvar", style="Action.TButton", command=salvar_rotina).pack(side="left")
        ttk.Button(botoes, text="Cancelar", command=modal.destroy).pack(side="left", padx=(8, 0))

        frame.columnconfigure(1, weight=1)

    def open_alerta_preco_form(alert=None):
        modal = tk.Toplevel(root)
        modal.title("Configurar alerta de preco")
        modal.geometry("760x640")
        modal.minsize(700, 560)
        modal.configure(bg="#ececec")
        modal.transient(root)
        modal.grab_set()

        frame = ttk.Frame(modal, style="Main.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Configurar Alerta de Preco", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        descricao_padrao = ""
        if alert:
            descricao_padrao = (alert.get("description") or alert.get("descricao") or "").strip()

        nome_var = tk.StringVar(value=((alert.get("name", "") if alert else "") or descricao_padrao))
        descricao_alerta_var = tk.StringVar(value=descricao_padrao)
        preco_alvo_var = tk.StringVar(value=("" if not alert else str(_target_price_from_alert(alert))))
        email_var = tk.StringVar(value=("" if not alert else str(alert.get("email") or "; ".join(alert.get("emails", [])))))
        telefone_var = tk.StringVar(value=("" if not alert else str(alert.get("telefone") or "; ".join(alert.get("phones", [])))))

        urls_alerta = _urls_from_alert(alert or {})
        while len(urls_alerta) < 5:
            urls_alerta.append("")

        link_vars = [tk.StringVar(value=urls_alerta[idx]) for idx in range(5)]

        ttk.Label(frame, text="Descricao do produto:", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=(14, 0))
        ttk.Entry(frame, textvariable=descricao_alerta_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(14, 0))

        ttk.Label(frame, text="Nome (opcional):", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=nome_var).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Preco desejado (R$):", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(
            frame,
            textvariable=preco_alvo_var,
            validate="key",
            validatecommand=vcmd_decimal,
        ).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="E-mail(s):", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=email_var).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Telefone(s):", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=telefone_var).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        for idx, link_var in enumerate(link_vars, start=1):
            ttk.Label(frame, text=f"Link {idx}:", style="Field.TLabel").grid(row=5 + idx, column=0, sticky="w", pady=(12, 0))
            ttk.Entry(frame, textvariable=link_var).grid(row=5 + idx, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Observacao: ciclo fixo de 1 hora e verificacao sempre por URL.", style="Hint.TLabel").grid(
            row=11,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(12, 0),
        )

        botoes = ttk.Frame(frame, style="Main.TFrame")
        botoes.grid(row=12, column=0, columnspan=2, sticky="w", pady=(16, 0))

        def salvar_alerta_form():
            descricao = (descricao_alerta_var.get() or "").strip()
            nome = (nome_var.get() or "").strip() or descricao or "Alerta sem nome"

            try:
                preco_alvo = parse_float(preco_alvo_var.get(), "Preco alvo")
                if preco_alvo is None or preco_alvo <= 0:
                    raise ValueError("Campo 'Preco alvo' deve ser maior que zero.")

            except ValueError as exc:
                messagebox.showerror("Validacao", str(exc), parent=modal)
                return

            urls = [str(var.get()).strip() for var in link_vars if str(var.get()).strip()]
            invalidas = [url for url in urls if not url.startswith("http://") and not url.startswith("https://")]
            if invalidas:
                messagebox.showerror("Validacao", "Todas as URLs devem comecar com http:// ou https://.", parent=modal)
                return

            if not urls:
                messagebox.showerror("Validacao", "Informe ao menos uma URL.", parent=modal)
                return

            if not descricao:
                messagebox.showerror("Validacao", "A descricao do produto e obrigatoria para validacao do link.", parent=modal)
                return

            email_unico, emails = _single_destino(email_var.get())
            telefone_unico, telefones = _single_destino(telefone_var.get())

            if len(_split_destinos(email_var.get())) > 1:
                messagebox.showerror("Validacao", "Informe apenas 1 e-mail por alerta.", parent=modal)
                return

            if len(_split_destinos(telefone_var.get())) > 1:
                messagebox.showerror("Validacao", "Informe apenas 1 telefone por alerta.", parent=modal)
                return

            if not emails and not telefones:
                messagebox.showerror("Validacao", "Informe ao menos um destino: e-mail e/ou telefone.", parent=modal)
                return

            agora = datetime.now()
            link_map = {f"link{idx}": (urls[idx - 1] if idx - 1 < len(urls) else "") for idx in range(1, 6)}
            ativo_alerta = bool(alert.get("active", True)) if alert else True

            if ativo_alerta and TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS:
                numero_forcado = _numero_destino_trial()
                telefone_unico = numero_forcado
                telefones = [numero_forcado]

            if alert is None:
                novo_alerta = {
                    "id": _proximo_id_configuracao(),
                    "name": nome,
                    "mode": "url",
                    "target_price": preco_alvo,
                    "precoDesejado": preco_alvo,
                    "interval_hours": ALERT_INTERVAL_HOURS_FIXED,
                    "urls": urls,
                    **link_map,
                    "email": email_unico,
                    "emails": emails,
                    "telefone": telefone_unico,
                    "phones": telefones,
                    "description": descricao,
                    "descricao": descricao,
                    "active": True,
                    "agendado": True,
                    "last_check_at": None,
                    "next_check_at": (agora + timedelta(hours=ALERT_INTERVAL_HOURS_FIXED)).isoformat(timespec="seconds"),
                    "configured_at": agora.isoformat(timespec="seconds"),
                    "end_at": (agora + timedelta(days=ALERT_ACTIVE_DAYS_DEFAULT)).isoformat(timespec="seconds"),
                    "dt_criacao": agora.isoformat(timespec="seconds"),
                    "last_notified_price": None,
                    "last_notified_at": None,
                    "first_triggered_at": None,
                }
                alerts.append(novo_alerta)
                status_var.set(f"Alerta '{nome}' criado.")
                alert_ref = novo_alerta
            else:
                alert["name"] = nome
                alert["mode"] = "url"
                alert["target_price"] = preco_alvo
                alert["precoDesejado"] = preco_alvo
                alert["interval_hours"] = ALERT_INTERVAL_HOURS_FIXED
                alert["urls"] = urls
                alert.update(link_map)
                alert["email"] = email_unico
                alert["emails"] = emails
                alert["telefone"] = telefone_unico
                alert["phones"] = telefones
                alert["description"] = descricao
                alert["descricao"] = descricao
                alert["configured_at"] = agora.isoformat(timespec="seconds")
                alert["end_at"] = (agora + timedelta(days=ALERT_ACTIVE_DAYS_DEFAULT)).isoformat(timespec="seconds")
                alert["last_check_at"] = None
                alert["next_check_at"] = (agora + timedelta(hours=ALERT_INTERVAL_HOURS_FIXED)).isoformat(timespec="seconds")
                alert["first_triggered_at"] = None
                alert["last_notified_at"] = None
                alert["last_notified_price"] = None
                status_var.set(f"Alerta '{nome}' atualizado.")
                alert_ref = alert

            persist_alerts()
            _refresh_hub_schedules_grid()
            modal.destroy()

            if alert is None and alert_ref.get("active", True):
                _executar_programacao_agora(_programacao_key("alerta", alert_ref.get("id")))

        ttk.Button(botoes, text="Salvar", style="Action.TButton", command=salvar_alerta_form).pack(side="left")
        ttk.Button(botoes, text="Cancelar", command=modal.destroy).pack(side="left", padx=(8, 0))

        frame.columnconfigure(1, weight=1)

    def _excluir_programacao_por_key(key):
        tipo, item = _obter_programacao_por_key(key)
        if tipo == "alerta" and item is not None:
            alerts[:] = [a for a in alerts if str(a.get("id")) != str(item.get("id"))]
            persist_alerts()
            return True
        if tipo == "campanha" and item is not None:
            hub_schedules[:] = [s for s in hub_schedules if str(s.get("id")) != str(item.get("id"))]
            persist_hub_schedules()
            return True
        return False

    def on_excluir_programacoes_selecionadas():
        if not programacoes_selecionadas:
            messagebox.showwarning("Atencao", "Selecione ao menos uma configuracao para excluir.")
            return

        confirmar = messagebox.askyesno("Excluir configuracoes", "Deseja excluir as configuracoes selecionadas?")
        if not confirmar:
            return

        for key in list(programacoes_selecionadas):
            _excluir_programacao_por_key(key)

        programacoes_selecionadas.clear()
        selecionar_todas_var.set(False)
        _refresh_hub_schedules_grid()
        status_var.set("Configuracoes selecionadas excluidas.")

    def _executar_programacao_agora(key):
        tipo, item = _obter_programacao_por_key(key)
        if item is None:
            return

        if tipo == "campanha":
            agora = datetime.now()
            intervalo_horas = max(1, int(item.get("interval_hours", 1)))
            item["last_run_at"] = agora.isoformat(timespec="seconds")
            item["next_run_at"] = (agora + timedelta(hours=intervalo_horas)).isoformat(timespec="seconds")
            persist_hub_schedules()
            _refresh_hub_schedules_grid()
            args = _build_hub_args_from_schedule(item)
            args.extend(["--modalidade-execucao", "campanha"])
            launch_process(args, f"Rotina executada manualmente: {item.get('name', 'Sem nome')}", execution_key=key)
            return

        if tipo == "alerta":
            if _enqueue_alert_execution(item, source="manual"):
                _run_next_alert_from_queue()
            else:
                status_var.set(f"Alerta ja esta em execucao/fila: {item.get('name', 'Sem nome')}")

    def _resumo_execucao_por_linha(key):
        tipo, item = _obter_programacao_por_key(key)
        if item is None:
            return "Linha nao encontrada."

        status_exec = str(item.get("last_execution_status") or "").strip().lower() or "sem_execucao"
        msg_exec = str(item.get("last_execution_message") or "").strip() or "-"
        when_exec = _formatar_data_hora(item.get("last_execution_at"))

        if status_exec == "falha":
            status_humano = "Falha"
        elif status_exec == "sem_disparo":
            status_humano = "Sem disparo por criterio"
        elif status_exec == "sucesso":
            status_humano = "Sucesso"
        else:
            status_humano = "Sem execucao registrada"

        if tipo == "alerta":
            return (
                "Resumo de execucao da linha\n\n"
                f"ID: {item.get('id', '-')}\n"
                f"Tipo: Alerta de preco\n"
                f"Nome: {item.get('name', 'Alerta sem nome')}\n"
                f"Status: {status_humano}\n"
                f"Mensagem: {msg_exec}\n"
                f"Ultima execucao registrada: {when_exec}\n"
                f"Ultima checagem: {_formatar_data_hora(item.get('last_check_at'))}\n"
                f"Proxima checagem: {_proxima_execucao_alerta(item)}"
            )

        return (
            "Resumo de execucao da linha\n\n"
            f"ID: {item.get('id', '-')}\n"
            f"Tipo: Campanha\n"
            f"Nome: {item.get('name', 'Rotina sem nome')}\n"
            f"Status: {status_humano}\n"
            f"Mensagem: {msg_exec}\n"
            f"Ultima execucao registrada: {when_exec}\n"
            f"Ultima rodada da rotina: {_formatar_data_hora(item.get('last_run_at'))}\n"
            f"Proxima execucao: {_proxima_execucao_campanha(item)}"
        )

    def _on_programacoes_tree_click(event):
        row_id = hub_schedule_tree.identify_row(event.y)
        col_id = hub_schedule_tree.identify_column(event.x)
        if not row_id:
            return
        if row_id == "empty-state":
            return

        if col_id == "#1":
            if row_id in programacoes_selecionadas:
                programacoes_selecionadas.remove(row_id)
            else:
                programacoes_selecionadas.add(row_id)
            _refresh_hub_schedules_grid()
            return

        if col_id == "#2":
            tipo, item = _obter_programacao_por_key(row_id)
            if item is None:
                return
            item["active"] = not bool(item.get("active", True))
            if tipo == "alerta":
                item["first_triggered_at"] = None
                item["last_notified_at"] = None
                item["last_notified_price"] = None
                if bool(item.get("active", True)) and TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS:
                    _aplicar_destino_whatsapp_trial_em_cfg(item)
                persist_alerts()
            elif tipo == "campanha":
                if bool(item.get("active", True)) and TWILIO_TRIAL_FORCE_ACTIVE_CONFIGS:
                    _aplicar_destino_whatsapp_trial_em_cfg(item)
                persist_hub_schedules()
            _refresh_hub_schedules_grid()
            return

        if col_id == "#12":
            bbox = hub_schedule_tree.bbox(row_id, col_id)
            if not bbox:
                return

            col_x, _col_y, col_w, _col_h = bbox
            clique_relativo = max(0, min(col_w - 1, event.x - col_x))
            fatia = col_w / 4

            if clique_relativo < fatia:
                resumo = _resumo_execucao_por_linha(row_id)
                messagebox.showinfo("Resumo da linha", resumo)
                return

            if clique_relativo < (2 * fatia):
                if len(programacoes_selecionadas) > 1:
                    messagebox.showwarning("Edicao bloqueada", "Nao e possivel editar com mais de uma configuracao selecionada.")
                    return

                tipo, item = _obter_programacao_por_key(row_id)
                if tipo == "alerta":
                    open_alerta_preco_form(item)
                elif tipo == "campanha":
                    open_hub_schedule_modal(item)
                return

            if clique_relativo < (3 * fatia):
                tipo, item = _obter_programacao_por_key(row_id)
                if item is None:
                    return
                nome = item.get("name", "Sem nome")
                if not messagebox.askyesno("Excluir configuracao", f"Deseja excluir '{nome}'?"):
                    return
                _excluir_programacao_por_key(row_id)
                programacoes_selecionadas.discard(row_id)
                _refresh_hub_schedules_grid()
                return

            _executar_programacao_agora(row_id)
            return

    hub_schedule_tree.bind("<Button-1>", _on_programacoes_tree_click)

    def _hub_schedule_due(schedule, now):
        if not schedule.get("active", True):
            return False

        inicio = _parse_iso_datetime(schedule.get("start_at"))
        fim = _parse_iso_datetime(schedule.get("end_at"))
        if inicio and now < inicio:
            return False
        if fim and now > fim:
            return False

        next_run = _parse_iso_datetime(schedule.get("next_run_at"))
        if next_run is not None:
            return now >= next_run

        intervalo_horas = max(1, int(schedule.get("interval_hours", 1)))
        ultimo = _parse_iso_datetime(schedule.get("last_run_at"))
        if ultimo is None:
            return True

        return (now - ultimo) >= timedelta(hours=intervalo_horas)

    def run_hub_scheduler_tick():
        if worker_running["value"]:
            return

        agora = datetime.now()
        due_schedule = next((s for s in hub_schedules if _hub_schedule_due(s, agora)), None)
        if due_schedule is None:
            return

        due_schedule["last_run_at"] = agora.isoformat(timespec="seconds")
        due_schedule["next_run_at"] = (agora + timedelta(hours=max(1, int(due_schedule.get("interval_hours", 1))))).isoformat(timespec="seconds")

        persist_hub_schedules()
        _refresh_hub_schedules_grid()

        args = _build_hub_args_from_schedule(due_schedule)
        args.extend(["--modalidade-execucao", "campanha"])
        launch_process(
            args,
            f"Rotina programada em execucao: {due_schedule.get('name', 'Sem nome')}",
            execution_key=_programacao_key("campanha", due_schedule.get("id")),
        )

    _save_sheets_alerts_config(SHEETS_ALERTS_CONFIG_FILE, sheets_alerts_config)
    _padronizar_formato_ids_configuracoes()
    _normalizar_alertas_schema()
    _normalizar_hub_schedules_schema()
    _forcar_whatsapp_trial_nas_configs_ativas()
    _normalizar_proximas_execucoes()
    _refresh_hub_schedules_grid()
    _iniciar_log_alertas()

    def _mostrar_modal_continuar_login_ml():
        confirmado = {"value": False}

        modal = tk.Toplevel(root)
        modal.title("Autenticacao necessaria")
        modal.configure(bg="#ececec")
        modal.transient(root)
        modal.grab_set()
        modal.resizable(False, False)

        frame = ttk.Frame(modal, style="Main.TFrame", padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Mercado Livre não autenticado, realize o login e clique em 'Continuar'",
            style="Hint.TLabel",
            wraplength=420,
            justify="left",
        ).pack(anchor="w")

        def _confirmar():
            confirmado["value"] = True
            modal.destroy()

        ttk.Button(frame, text="Continuar", style="Action.TButton", command=_confirmar).pack(anchor="e", pady=(14, 0))

        modal.protocol("WM_DELETE_WINDOW", _confirmar)
        modal.wait_visibility()
        modal.focus_force()
        modal.wait_window()

        return confirmado["value"]

    def _sinalizar_confirmacao_login_ml():
        try:
            LOGIN_OK_SIGNAL_FILE.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
            status_var.set("Confirmacao enviada. Validando login do Mercado Livre...")
        except Exception as exc:
            messagebox.showerror("Falha", f"Nao foi possivel enviar confirmacao de login.\n\n{exc}")

    def _tratar_marcadores_autenticacao(texto):
        if AUTH_MARKER_REQUIRED_ML not in texto and AUTH_MARKER_STILL_PENDING_ML not in texto:
            return

        if AUTH_MARKER_STILL_PENDING_ML in texto:
            status_var.set("Login ainda nao confirmado. Finalize o login e clique em 'Continuar' novamente.")
        else:
            status_var.set("Aguardando login no Mercado Livre...")

        if _mostrar_modal_continuar_login_ml():
            _sinalizar_confirmacao_login_ml()

    def _append_resumo(texto):
        if not texto:
            return

        resumo_text.insert("end", texto)
        resumo_text.see("end")
        _tratar_marcadores_autenticacao(texto)

        match_url = re.search(r"https?://\S+", texto)
        if match_url:
            url_extraida = match_url.group(0).rstrip(".)],")
            if "accounts.google.com" in url_extraida or "oauth2" in url_extraida:
                oauth_url_var.set(url_extraida)
                _refresh_oauth_url_ui()

    def _limpar_resumo():
        resumo_text.delete("1.0", "end")

    def _refresh_oauth_url_ui():
        has_url = bool((oauth_url_var.get() or "").strip())
        oauth_status_var.set("OAuth URL: gerada" if has_url else "OAuth URL: nao gerada")
        open_oauth_url_btn.configure(state=("normal" if has_url else "disabled"))
        copy_oauth_url_btn.configure(state=("normal" if has_url else "disabled"))

    def _abrir_oauth_url():
        url = (oauth_url_var.get() or "").strip()
        if not url:
            status_var.set("Nenhuma URL OAuth disponivel no momento.")
            return

        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            url = f"https://{url}"

        try:
            abriu = webbrowser.open_new_tab(url)
            if not abriu:
                raise RuntimeError("Nao foi possivel abrir o navegador padrao.")
            status_var.set("URL OAuth aberta no navegador.")
        except Exception as exc:
            status_var.set("Falha ao abrir URL OAuth automaticamente.")
            messagebox.showwarning("OAuth", f"Nao foi possivel abrir a URL automaticamente.\n\n{exc}")

    def _copiar_oauth_url():
        url = (oauth_url_var.get() or "").strip()
        if not url:
            messagebox.showinfo("OAuth", "Nenhuma URL OAuth disponivel para copiar.")
            return
        root.clipboard_clear()
        root.clipboard_append(url)
        status_var.set("URL OAuth copiada para a area de transferencia.")

    open_oauth_url_btn.configure(command=_abrir_oauth_url)
    copy_oauth_url_btn.configure(command=_copiar_oauth_url)
    _refresh_oauth_url_ui()

    def _drain_worker_messages():
        try:
            while True:
                _append_resumo(worker_messages.get_nowait())
        except queue.Empty:
            pass

        root.after(200, _drain_worker_messages)

    class _TeeWriter:
        def __init__(self, output_queue, file_handle=None, mirror=None):
            self._queue = output_queue
            self._file_handle = file_handle
            self._mirror = mirror

        def write(self, texto):
            if not texto:
                return 0

            self._queue.put(texto)

            if self._file_handle:
                self._file_handle.write(texto)

            if self._mirror:
                self._mirror.write(texto)

            return len(texto)

        def flush(self):
            if self._file_handle:
                self._file_handle.flush()
            if self._mirror:
                self._mirror.flush()

    def _iniciar_log_execucao(forward_args):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho = LOGS_DIR / f"execucao_{timestamp}.log"

        with open(caminho, "w", encoding="utf-8") as log_file:
            log_file.write(f"=== Inicio da execucao: {datetime.now().isoformat(timespec='seconds')} ===\n")
            log_file.write(f"Args: {' '.join(forward_args)}\n\n")

        return caminho

    root.after(200, _drain_worker_messages)

    def _alert_due(alert, now):
        if not alert.get("active", True):
            return False

        first_triggered_at = _parse_iso_datetime(alert.get("first_triggered_at"))
        if first_triggered_at is not None:
            prazo_execucao = first_triggered_at + timedelta(days=ALERT_EXECUTION_DAYS_AFTER_FIRST_TRIGGER)
            if now > prazo_execucao:
                alert["active"] = False
                _escrever_log_alerta(
                    f"Alerta {alert.get('id', '-')} desativado: janela de execucao de {ALERT_EXECUTION_DAYS_AFTER_FIRST_TRIGGER} dias apos primeiro disparo foi encerrada."
                )
                persist_alerts()
                return False

        fim = _parse_iso_datetime(alert.get("end_at"))
        if fim and now > fim:
            alert["active"] = False
            _escrever_log_alerta(
                f"Alerta {alert.get('id', '-')} encerrado automaticamente apos {ALERT_ACTIVE_DAYS_DEFAULT} dias."
            )
            persist_alerts()
            return False

        next_check = _parse_iso_datetime(alert.get("next_check_at"))
        if next_check is not None:
            return now >= next_check

        interval_hours = max(1, int(alert.get("interval_hours", 1)))
        last_check = _parse_iso_datetime(alert.get("last_check_at"))

        if last_check is None:
            return True

        return now - last_check >= timedelta(hours=interval_hours)

    def _check_alert_once(alert):
        description = (alert.get("description") or alert.get("descricao") or "").strip()
        urls = _urls_from_alert(alert)
        target_price = _target_price_from_alert(alert)
        alert_id = str(alert.get("id", "-")).strip() or "-"
        lowest_price = None
        lowest_price_before = None
        lowest_price_after = None
        source = ""
        title_found = ""
        error_message = None
        descricao_invalida = 0
        links_invalidos = 0
        falhas_extracao = 0
        urls_processadas = 0
        target_normalized = _normalize_text_for_match(description)

        try:
            for url in urls:
                url_limpa = (url or "").strip()
                if not (url_limpa.startswith("http://") or url_limpa.startswith("https://")):
                    links_invalidos += 1
                    continue

                urls_processadas += 1

                try:
                    price, src, title, price_before, price_after = _fetch_price_and_title_from_url(url_limpa)
                except Exception:
                    falhas_extracao += 1
                    continue

                # Sem preço válido, não há base para validar aderência por descrição.
                if price is None:
                    falhas_extracao += 1
                    continue

                if target_normalized:
                    if not _description_matches_title(target_normalized, title):
                        descricao_invalida += 1
                        continue

                if lowest_price is None or price < lowest_price:
                    lowest_price = price
                    source = src
                    title_found = title
                    lowest_price_before = price_before
                    lowest_price_after = price_after or price

            if lowest_price is None and description:
                try:
                    preco_por_descricao, origem_por_descricao = _fetch_price_from_description(description)
                    if preco_por_descricao is not None:
                        lowest_price = preco_por_descricao
                        source = origem_por_descricao or source
                        title_found = description
                        _escrever_log_alerta(
                            f"Alerta {alert_id}: preco obtido via fallback por descricao."
                        )
                except Exception:
                    pass

            if lowest_price is None:
                if urls and links_invalidos == len(urls):
                    error_message = "Link invalido."
                elif urls_processadas > 0 and descricao_invalida >= urls_processadas:
                    error_message = "Descricao nao bateu com o titulo."
                elif falhas_extracao > 0 or urls_processadas > 0:
                    error_message = "Falha ao extrair preco."
                elif urls:
                    error_message = "Falha ao extrair preco."

            if lowest_price is not None:
                affiliate_source = _build_affiliate_link(source)
                if not affiliate_source:
                    error_message = "Nao foi possivel gerar link de afiliado para o anuncio encontrado."
                else:
                    source = affiliate_source
        except Exception as exc:
            error_message = str(exc)

        agora = datetime.now()
        interval_hours = ALERT_INTERVAL_HOURS_FIXED
        alert["interval_hours"] = ALERT_INTERVAL_HOURS_FIXED
        alert["last_check_at"] = agora.isoformat(timespec="seconds")
        alert["next_check_at"] = (agora + timedelta(hours=interval_hours)).isoformat(timespec="seconds")

        if error_message:
            _escrever_log_alerta(f"Alerta {alert_id} erro na checagem: {error_message}")
            return {
                "alert": alert,
                "triggered": False,
                "price": None,
                "price_before": None,
                "price_after": None,
                "source": source,
                "title": title_found,
                "error": error_message,
                "diagnostics": {
                    "links_invalidos": links_invalidos,
                    "descricao_invalida": descricao_invalida,
                    "falhas_extracao": falhas_extracao,
                    "urls_processadas": urls_processadas,
                },
            }

        triggered = lowest_price is not None and lowest_price <= target_price
        _escrever_log_alerta(
            f"Alerta {alert_id} checado: triggered={triggered} preco={lowest_price} alvo={target_price}"
        )
        return {
            "alert": alert,
            "triggered": triggered,
            "price": lowest_price,
            "price_before": lowest_price_before,
            "price_after": lowest_price_after,
            "source": source,
            "title": title_found,
            "error": None,
            "diagnostics": {
                "links_invalidos": links_invalidos,
                "descricao_invalida": descricao_invalida,
                "falhas_extracao": falhas_extracao,
                "urls_processadas": urls_processadas,
            },
        }

    def _enviar_alerta_email(destinos, assunto, corpo):
        if not destinos:
            return False, "sem destinos"

        smtp_host = _ler_variavel_ambiente("SMTP_HOST")
        smtp_port = int(_ler_variavel_ambiente("SMTP_PORT") or "587")
        smtp_user = _ler_variavel_ambiente("SMTP_USER")
        smtp_pass = _ler_variavel_ambiente("SMTP_PASS")
        smtp_from = _ler_variavel_ambiente("SMTP_FROM") or smtp_user
        smtp_use_tls = _ler_variavel_ambiente("SMTP_USE_TLS") not in {"0", "false", "False"}

        if not smtp_host or not smtp_from:
            return False, "SMTP nao configurado"

        msg = MIMEText(corpo, "plain", "utf-8")
        msg["Subject"] = assunto
        msg["From"] = smtp_from
        msg["To"] = ", ".join(destinos)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, destinos, msg.as_string())

        return True, "ok"

    def _enviar_alerta_whatsapp(destinos, mensagem):
        if not destinos:
            return False, "sem destinos"

        if TwilioClient is None:
            return False, "twilio nao instalado"

        account_sid = _ler_variavel_ambiente("TWILIO_ACCOUNT_SID")
        auth_token = _ler_variavel_ambiente("TWILIO_AUTH_TOKEN")
        whatsapp_from = _ler_variavel_ambiente("TWILIO_WHATSAPP_FROM")
        if not account_sid or not auth_token or not whatsapp_from:
            return False, "Twilio nao configurado"

        client = TwilioClient(account_sid, auth_token)
        enviados = 0
        destinos_utilizados = []
        sids_enviados = []
        erros_envio = []

        for numero in destinos:
            to = _normalizar_telefone_whatsapp(numero)
            if not to:
                continue

            destinos_utilizados.append(_mascarar_destino_whatsapp(to))

            try:
                resposta = client.messages.create(from_=whatsapp_from, to=to, body=mensagem)
                enviados += 1
                sid = str(getattr(resposta, "sid", "")).strip()
                if sid:
                    sids_enviados.append(sid)
            except TwilioRestException as exc:
                codigo = getattr(exc, "code", "-")
                status = getattr(exc, "status", "-")
                detalhe = str(getattr(exc, "msg", exc) or exc).strip()
                erros_envio.append(f"{_mascarar_destino_whatsapp(to)}(code={codigo},status={status},msg={detalhe[:80]})")
                continue

        if not destinos_utilizados:
            return False, "nenhum numero valido"

        resumo_destinos = ",".join(destinos_utilizados)
        if enviados:
            resumo_sids = ",".join(sids_enviados[:3]) if sids_enviados else "sem-sid"
            if erros_envio:
                return True, f"{enviados} envio(s) destinos={resumo_destinos} sid={resumo_sids} erros_parciais={'; '.join(erros_envio)}"
            return True, f"{enviados} envio(s) destinos={resumo_destinos} sid={resumo_sids}"

        if erros_envio:
            return False, f"nenhum envio destinos={resumo_destinos} erros={'; '.join(erros_envio)}"
        return False, f"nenhum envio destinos={resumo_destinos}"

    def _apply_alert_results(results, queue_finalize=True):
        triggered_count = 0
        ofertas_alerta_saida = []
        resumo_motivos = {
            "link_invalido": 0,
            "descricao_divergente": 0,
            "falha_extracao_preco": 0,
        }

        for result in results:
            alert = result["alert"]
            if result["error"]:
                _registrar_resultado_execucao(alert, "falha", result["error"])
                status_var.set(f"Falha ao verificar alerta '{alert.get('name', 'Sem nome')}'.")
                _append_resumo(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Alerta '{alert.get('name', 'Sem nome')}' sem preco valido: {result['error']}\n"
                )
                _escrever_log_alerta(
                    f"Alerta {alert.get('id', '-')} falhou: {result['error']}"
                )

                erro = (result.get("error") or "").casefold()
                if "link invalido" in erro:
                    resumo_motivos["link_invalido"] += 1
                elif "descricao nao bateu com o titulo" in erro:
                    resumo_motivos["descricao_divergente"] += 1
                elif "falha ao extrair preco" in erro:
                    resumo_motivos["falha_extracao_preco"] += 1
                continue

            if not result["triggered"]:
                _registrar_resultado_execucao(alert, "sem_disparo", "Nao se encaixou nos criterios de disparo.")
                _escrever_log_alerta(
                    f"Alerta {alert.get('id', '-')} sem disparo nesta execucao."
                )
                continue

            price = result["price"]
            last_notified_at = _parse_iso_datetime(alert.get("last_notified_at"))
            last_notified_price = None
            try:
                if alert.get("last_notified_price") is not None:
                    last_notified_price = float(alert.get("last_notified_price"))
            except Exception:
                last_notified_price = None

            if last_notified_at is not None and last_notified_at.date() == datetime.now().date():
                # Reenvia no mesmo dia somente se o preco caiu ainda mais.
                if last_notified_price is None or price >= last_notified_price:
                    _escrever_log_alerta(
                        f"Alerta {alert.get('id', '-')} sem novo envio (mesmo dia e sem queda adicional de preco)."
                    )
                    continue
                _escrever_log_alerta(
                    f"Alerta {alert.get('id', '-')} com reenvio no mesmo dia por nova queda de preco ({last_notified_price:.2f} -> {price:.2f})."
                )

            if not alert.get("first_triggered_at"):
                alert["first_triggered_at"] = datetime.now().isoformat(timespec="seconds")
                _escrever_log_alerta(
                    f"Alerta {alert.get('id', '-')} marcou primeiro disparo em {alert['first_triggered_at']}."
                )

            alert["last_notified_price"] = price
            alert["last_notified_at"] = datetime.now().isoformat(timespec="seconds")
            _registrar_resultado_execucao(alert, "sucesso", "Disparo enviado.")
            triggered_count += 1

            destinos = []
            emails_cfg = [e for e in alert.get("emails", []) if str(e).strip()]
            phones_cfg = [p for p in alert.get("phones", []) if str(p).strip()]
            if emails_cfg:
                destinos.append(f"e-mails: {', '.join(emails_cfg)}")
            if phones_cfg:
                destinos.append(f"telefones: {', '.join(phones_cfg)}")

            _append_resumo(
                f"[{datetime.now().strftime('%H:%M:%S')}] Alerta '{alert.get('name', 'Alerta')}' disparou. "
                f"Preco: R$ {price:.2f}. Destinos: {('; '.join(destinos) if destinos else 'nao configurados')}.\n"
            )

            # "Antes" e "Depois" devem vir do HTML do anúncio (quando disponíveis).
            price_maior = result.get("price_before")
            price_menor = result.get("price_after")

            if price_menor is None:
                price_menor = float(price)

            if price_maior is None:
                price_maior = float(price_menor)

            if float(price_maior) < float(price_menor):
                price_maior, price_menor = price_menor, price_maior
            
            oferta_alerta = {
                "categoria": "Alerta > Preco",
                "descricao": alert.get("name", "Alerta"),
                "antes": f"R$ {price_maior:.2f}",
                "desconto": "-",
                "depois": f"R$ {price_menor:.2f}",
                "link": result.get("source") or "-",
            }
            ofertas_alerta_saida.append(oferta_alerta)

            assunto = f"Alerta de preço: {alert.get('name', 'Alerta')}"
            corpo = (
                f"{alert.get('name', 'Alerta')} disparou!\n\n"
                f"Descricao validada: {alert.get('description') or alert.get('descricao') or '-'}\n"
                f"Preco encontrado: {_formatar_preco_brl(price)}\n"
                f"Antes: ~{_formatar_preco_brl(price_maior)}~\n"
                f"Depois: *{_formatar_preco_brl(price_menor)}*\n"
                f"Preco desejado: {_formatar_preco_brl(_target_price_from_alert(alert))}\n"
                f"Origem: {result.get('source') or '-'}"
            )
            mensagem_whatsapp = (
                "ALERTA DE OFERTA\n\n"
                f"O produto {alert.get('description') or alert.get('descricao') or '-'} "
                f"foi anunciado com valor abaixo de {_formatar_preco_brl(_target_price_from_alert(alert))}\n\n"
                f"Antes: ~{_formatar_preco_brl(price_maior)}~\n"
                f"Depois: *{_formatar_preco_brl(price_menor)}*\n\n"
                f"Acesse o link para visualizar: {result.get('source') or '-'}"
            )

            email_ok, email_msg = _enviar_alerta_email(emails_cfg, assunto, corpo)
            whatsapp_ok, whatsapp_msg = _enviar_alerta_whatsapp(phones_cfg, mensagem_whatsapp)

            _append_resumo(
                f"[{datetime.now().strftime('%H:%M:%S')}] Notificacao alerta {alert.get('id', '-')}: "
                f"email={email_msg}; whatsapp={whatsapp_msg}.\n"
            )
            _escrever_log_alerta(
                f"Notificacao alerta {alert.get('id', '-')}: email={email_msg}; whatsapp={whatsapp_msg}."
            )

            # Pop-up customizado que fecha sozinho após 10s ou ao clicar em OK
            popup = tk.Toplevel(root)
            popup.title("Alerta de preço")
            popup.configure(bg="#ececec")
            popup.transient(root)
            popup.resizable(False, False)
            popup.geometry("400x220")
            frame = ttk.Frame(popup, style="Main.TFrame", padding=18)
            frame.pack(fill="both", expand=True)
            msg = (
                f"{alert.get('name', 'Alerta')} disparou!\n\n"
                f"Preço encontrado: R$ {price:.2f}\n"
                f"Antes: ~{_formatar_preco_brl(price_maior)}~\n"
                f"Depois: *{_formatar_preco_brl(price_menor)}*\n"
                f"Preço alvo: R$ {_target_price_from_alert(alert):.2f}\n"
                f"Origem: {result.get('source') or '-'}\n"
                f"Email: {'OK' if email_ok else 'pendente/falhou'} | WhatsApp: {'OK' if whatsapp_ok else 'pendente/falhou'}"
            )
            label = ttk.Label(frame, text=msg, style="Field.TLabel", justify="left", wraplength=360)
            label.pack(anchor="w", pady=(0, 18))
            btn = ttk.Button(frame, text="OK", command=popup.destroy)
            btn.pack(anchor="e")
            popup.after(10000, popup.destroy)
            popup.wait_visibility()
            popup.focus_force()

        if triggered_count:
            status_var.set(f"{triggered_count} alerta(s) disparado(s).")
            _escrever_log_alerta(f"Execucao finalizada com {triggered_count} alerta(s) disparado(s).")
        else:
            _escrever_log_alerta("Execucao finalizada sem disparos.")

        total_motivos = sum(resumo_motivos.values())
        if total_motivos:
            mensagem_motivos = (
                "Resumo de falhas: "
                f"links invalidos={resumo_motivos['link_invalido']}; "
                f"descricao divergente={resumo_motivos['descricao_divergente']}; "
                f"falha extracao preco={resumo_motivos['falha_extracao_preco']}."
            )
            _append_resumo(f"[{datetime.now().strftime('%H:%M:%S')}] {mensagem_motivos}\n")
            _escrever_log_alerta(mensagem_motivos)

        if ofertas_alerta_saida:
            salvar_saida_execucao_modalidade(ofertas_alerta_saida, "alerta")

        persist_alerts()
        if queue_finalize:
            scheduler_state["running"] = False

    def run_scheduler_tick():
        now = datetime.now()
        with alerts_lock:
            due_alerts = [alert for alert in alerts if _alert_due(alert, now)]
        if not due_alerts:
            return

        enfileirados = 0
        for alert in due_alerts:
            if _enqueue_alert_execution(alert, source="scheduler"):
                enfileirados += 1

        if enfileirados:
            _run_next_alert_from_queue()

    def scheduler_loop():
        if datetime.now() >= sheets_sync_state["next_run_at"]:
            _import_alerts_from_sheet_once()
        run_scheduler_tick()
        run_hub_scheduler_tick()
        _refresh_hub_schedules_grid()
        root.after(SCHEDULER_TICK_MS, scheduler_loop)

    root.after(SCHEDULER_TICK_MS, scheduler_loop)

    def on_sync_sheet_now():
        _maybe_breakpoint("on_sync_sheet_now.entry")

        if not sheets_alerts_config.get("enabled", False):
            _escrever_log_sincronizacao_planilha("Sincronizacao manual bloqueada: integracao desativada.")
            messagebox.showwarning(
                "Integracao desativada",
                "Ative a integracao da planilha no arquivo integracao_planilha_alertas.json para sincronizar.",
            )
            return

        caminho_log_planilha = _iniciar_log_sincronizacao_planilha()
        log_path_var.set(f"Log salvo em: {caminho_log_planilha}")
        status_var.set("Sincronizacao manual da planilha iniciada...")
        _append_resumo(f"[{datetime.now().strftime('%H:%M:%S')}] Sincronizacao manual solicitada.\n")
        _escrever_log_sincronizacao_planilha("Sincronizacao manual solicitada pelo usuario.")
        _import_alerts_from_sheet_once()

    def launch_process(forward_args, status_text, execution_key=None):
        if worker_running["value"]:
            messagebox.showwarning("Em execucao", "Ja existe uma busca em andamento.")
            return

        if LOGIN_OK_SIGNAL_FILE.exists():
            try:
                LOGIN_OK_SIGNAL_FILE.unlink()
            except Exception:
                pass

        worker_running["value"] = True
        status_var.set(status_text)
        _limpar_resumo()

        try:
            caminho_log = _iniciar_log_execucao(forward_args)
        except Exception as exc:
            worker_running["value"] = False
            messagebox.showerror("Falha", f"Nao foi possivel criar o log de execucao.\n\n{exc}")
            return

        worker_log["path"] = caminho_log
        log_path_var.set(f"Log salvo em: {caminho_log}")
        _append_resumo(f"[{datetime.now().strftime('%H:%M:%S')}] {status_text}\n")
        _append_resumo(f"[{datetime.now().strftime('%H:%M:%S')}] Log: {caminho_log}\n\n")

        def _finish_worker(message=None):
            worker_running["value"] = False
            if message:
                status_var.set(message)
            _refresh_hub_schedules_grid()

        def _worker():
            erro = None
            mensagem_final = "Processo finalizado."

            try:
                with open(caminho_log, "a", encoding="utf-8") as log_file:
                    tee = _TeeWriter(worker_messages, file_handle=log_file, mirror=sys.__stdout__)
                    with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
                        try:
                            run_main_mode(forward_args)
                        except SystemExit as exc:
                            codigo = exc.code
                            if codigo not in (None, 0):
                                raise RuntimeError(f"Processo finalizado com codigo {codigo}.") from exc
                        finally:
                            print(f"\n=== Fim da execucao: {datetime.now().isoformat(timespec='seconds')} ===")
            except Exception as exc:
                erro = exc
                mensagem_final = "Falha na execucao."

            if erro is None:
                if execution_key:
                    tipo_exec, cfg_exec = _obter_programacao_por_key(execution_key)
                    if cfg_exec is not None:
                        _registrar_resultado_execucao(cfg_exec, "sucesso", "Execucao concluida sem falhas.")
                        if tipo_exec == "campanha":
                            persist_hub_schedules()
                        elif tipo_exec == "alerta":
                            persist_alerts()
                root.after(0, lambda: _finish_worker(mensagem_final))
                return

            if execution_key:
                tipo_exec, cfg_exec = _obter_programacao_por_key(execution_key)
                if cfg_exec is not None:
                    _registrar_resultado_execucao(cfg_exec, "falha", str(erro))
                    if tipo_exec == "campanha":
                        persist_hub_schedules()
                    elif tipo_exec == "alerta":
                        persist_alerts()

            root.after(
                0,
                lambda: (
                    messagebox.showerror("Falha", f"Erro durante a execucao:\n\n{erro}"),
                    _finish_worker(mensagem_final),
                ),
            )

        threading.Thread(target=_worker, daemon=True).start()

    def on_buscar_produto():
        selected = [name for name, var in fontes_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning("Atencao", "Selecione ao menos uma fonte.")
            return

        if not (fontes_vars["Mercado Livre"].get() or fontes_vars["Todas"].get()):
            messagebox.showwarning("Fonte nao suportada", "No momento o backend implementa apenas Mercado Livre.")
            return

        unsupported = [name for name in ["Amazon", "Shoppee", "Tiktok shop"] if fontes_vars[name].get()]
        if unsupported:
            messagebox.showinfo("Aviso", "Amazon/Shoppee/Tiktok Shop ainda nao estao implementados no backend. A busca rodara no Mercado Livre.")

        try:
            preco_min = parse_float(preco_min_var.get(), "Preco minimo")
            preco_max = parse_float(preco_max_var.get(), "Preco maximo")
            desconto = parse_int(desconto_var.get(), "Desconto minimo")
            limite_candidatos = parse_int(limite_candidatos_prod_var.get(), "Limite de candidatos")
        except ValueError as exc:
            messagebox.showerror("Validacao", str(exc))
            return

        if limite_candidatos is not None and limite_candidatos < 1:
            messagebox.showerror("Validacao", "Limite de candidatos deve ser no minimo 1.")
            return

        descricao = descricao_var.get().strip()
        categoria_principal = (categoria_var.get() or "").strip()
        subcategoria = (subcategoria_var.get() or "").strip()
        categoria = subcategoria or categoria_principal
        categoria_id = (subcategoria_id_var.get() or categoria_id_var.get() or "").strip().upper()
        subcategoria_id = (subcategoria_id_var.get() or "").strip().upper()

        possui_categoria = bool(categoria_id or (categoria and categoria != "Todas categorias"))
        if not descricao and not possui_categoria:
            messagebox.showwarning(
                "Atencao",
                "Informe ao menos Categoria e/ou Descricao para buscar o produto.",
            )
            return

        pasta_saida = filedialog.askdirectory(
            title="Escolha onde salvar lista_anuncios.txt",
            mustexist=True,
        )
        if not pasta_saida:
            return

        args = _build_hub_args_from_values(categoria, descricao, preco_min, preco_max, desconto, limite_candidatos)
        if categoria_id:
            args.extend(["--categoria-id", categoria_id])
        if subcategoria_id:
            args.extend(["--subcategoria-id", subcategoria_id])
        args.extend(["--pasta-saida", pasta_saida, "--modalidade-execucao", "ondemand"])

        launch_process(args, "Busca de produto on demand iniciada em nova janela.")

    def on_buscar_relampago():
        if rel_padrao_var.get():
            pasta_saida = filedialog.askdirectory(
                title="Escolha onde salvar lista_anuncios.txt",
                mustexist=True,
            )
            if not pasta_saida:
                return

            launch_process(
                ["--relampago-padrao", "--pasta-saida", pasta_saida, "--modalidade-execucao", "ondemand"],
                "Processo de ofertas relampago padrao iniciado em nova janela.",
            )
            return

        try:
            preco_min = parse_float(rel_preco_min_var.get(), "Preco minimo")
            preco_max = parse_float(rel_preco_max_var.get(), "Preco maximo")
            desconto = parse_int(rel_desconto_var.get(), "Desconto minimo")
            limite = parse_int(rel_limite_var.get(), "Limite de candidatos")
        except ValueError as exc:
            messagebox.showerror("Validacao", str(exc))
            return

        descricao = (rel_descricao_var.get() or "").strip()

        possui_parametro = any(
            [
                bool(descricao),
                preco_min is not None,
                preco_max is not None,
                desconto is not None,
                limite is not None,
            ]
        )

        if not possui_parametro:
            messagebox.showwarning(
                "Atencao",
                "Com o modo relampago padrao desmarcado, preencha ao menos um parametro para executar.",
            )
            return

        pasta_saida = filedialog.askdirectory(
            title="Escolha onde salvar lista_anuncios.txt",
            mustexist=True,
        )
        if not pasta_saida:
            return

        args = []

        args.append("--somente-relampago")
        if descricao:
            args.extend(["--descricao-produto", descricao])
        if preco_min is not None:
            args.extend(["--preco-minimo", str(preco_min)])
        if preco_max is not None:
            args.extend(["--preco-maximo", str(preco_max)])
        if desconto is not None:
            args.extend(["--desconto-minimo", str(desconto)])
        if limite is not None:
            args.extend(["--limite-candidatos", str(limite)])

        args.extend(["--pasta-saida", pasta_saida, "--modalidade-execucao", "ondemand"])
        launch_process(args, "Processo de ofertas relampago iniciado em nova janela.")

    buscar_produto_btn.configure(command=on_buscar_produto)
    buscar_relampago_btn.configure(command=on_buscar_relampago)
    alerta_preco_btn.configure(command=lambda: open_alerta_preco_form(None))
    campanha_produto_btn.configure(command=lambda: open_hub_schedule_modal(None))
    alerta_config_btn.configure(command=lambda: open_alerta_preco_form(None))
    campanha_config_btn.configure(command=lambda: open_hub_schedule_modal(None))
    sync_sheet_now_btn.configure(command=on_sync_sheet_now)
    delete_selected_btn.configure(command=on_excluir_programacoes_selecionadas)

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-main", action="store_true")
    parsed, forward = parser.parse_known_args()

    if parsed.run_main:
        run_main_mode(forward)
        return

    categorias = load_categories(BASE_DIR / "categorias_exec.txt")
    create_gui(categorias)


if __name__ == "__main__":
    main()
