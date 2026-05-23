import argparse
import contextlib
import importlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
ALERTS_CONFIG_FILE = BASE_DIR / "alertas_preco.json"
HUB_SCHEDULES_CONFIG_FILE = BASE_DIR / "agendamentos_hub.json"
LOGS_DIR = BASE_DIR / "logs_execucao"
LOGIN_OK_SIGNAL_FILE = BASE_DIR / ".ml_login_ok.signal"
AUTH_MARKER_REQUIRED_ML = "[AUTH_REQUIRED_ML]"
AUTH_MARKER_STILL_PENDING_ML = "[AUTH_STILL_PENDING_ML]"
SCHEDULER_TICK_MS = 60000
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

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

        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 18
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
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
    text = (value or "").strip().replace(",", ".")
    if not text:
        return None

    try:
        return float(text)
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

    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})|\d+[\.,]\d{2}|\d+)", raw)
    if not match:
        return None

    number = match.group(1)
    if "." in number and "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(",", ".")

    try:
        return float(number)
    except ValueError:
        return None


def _extract_price_from_html(html):
    soup = BeautifulSoup(html, "html.parser")

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
        "[data-andes-money-amount-fraction='true']",
        ".andes-money-amount__fraction",
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

    return None


def _fetch_price_from_url(url):
    response = requests.get(url, headers=HTTP_HEADERS, timeout=25)
    response.raise_for_status()

    price = _extract_price_from_html(response.text)
    return price, url


def _fetch_price_from_description(description):
    terms = " ".join(part for part in [description] if part).strip()
    if not terms:
        return None, ""

    search_url = f"https://lista.mercadolivre.com.br/{quote_plus(terms)}"
    response = requests.get(search_url, headers=HTTP_HEADERS, timeout=25)
    response.raise_for_status()

    price = _extract_price_from_html(response.text)
    return price, search_url


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
        padding=(16, 10),
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

    hero = ttk.Frame(main_frame, style="Hero.TFrame", padding=(18, 14))
    hero.pack(fill="x", pady=(0, 12))

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

    ttk.Label(main_frame, text="Entre com os dados do processo no formulario.", style="Hint.TLabel").pack(anchor="w", pady=(0, 10))

    top = ttk.Frame(main_frame, style="Main.TFrame")
    top.pack(fill="x", expand=False, pady=(0, 6))

    product_frame = ttk.LabelFrame(top, text="PROCURAR PRODUTO", style="Card.TLabelframe", padding=14)
    product_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

    relampago_frame = ttk.LabelFrame(top, text="PROCURAR OFERTAS RELAMPAGO", style="Card.TLabelframe", padding=14)
    relampago_frame.pack(side="right", fill="both", expand=True, padx=(8, 0))

    descricao_var = tk.StringVar()
    preco_min_var = tk.StringVar()
    preco_max_var = tk.StringVar()
    desconto_var = tk.StringVar()
    menor_preco_var = tk.BooleanVar(value=True)
    categoria_var = tk.StringVar(value="")

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
    rel_categoria_var = tk.StringVar(value="Todas categorias")
    rel_padrao_var = tk.BooleanVar(value=False)

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
    ttk.Label(product_frame, text="MarketPlace:", style="Field.TLabel").grid(row=row, column=0, sticky="nw", pady=(10, 0))
    source_frame = ttk.Frame(product_frame, style="Card.TLabelframe")
    source_frame.grid(row=row, column=1, columnspan=2, sticky="w", pady=(10, 0))

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
        ttk.Checkbutton(source_frame, text=nome, variable=fontes_vars[nome], command=cmd).grid(row=0, column=idx, padx=(0, 10), sticky="w")

    row += 1
    ttk.Label(product_frame, text="Categoria:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
    categorias_combo = ttk.Combobox(product_frame, textvariable=categoria_var, values=["", *categorias], state="readonly")
    categorias_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(8, 0))

    row += 1
    ttk.Label(product_frame, text="Preco minimo:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
    preco_min_entry = ttk.Entry(
        product_frame,
        textvariable=preco_min_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    preco_min_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(8, 0))

    row += 1
    ttk.Label(product_frame, text="Preco maximo:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
    preco_max_entry = ttk.Entry(
        product_frame,
        textvariable=preco_max_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    preco_max_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(8, 0))

    row += 1
    ttk.Label(product_frame, text="Desconto minimo (%):", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
    desconto_entry = ttk.Entry(
        product_frame,
        textvariable=desconto_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    desconto_entry.grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(8, 0))

    row += 1
    ttk.Checkbutton(product_frame, text="Priorizar menor preco", variable=menor_preco_var).grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))

    row += 1
    buscar_produto_btn = ttk.Button(product_frame, text="BUSCAR PRODUTO", style="Action.TButton")
    buscar_produto_btn.grid(row=row, column=0, columnspan=3, sticky="w", pady=(16, 0))

    row += 1
    ttk.Separator(product_frame, orient="horizontal").grid(row=row, column=0, columnspan=3, sticky="ew", pady=(14, 6))

    row += 1
    alerta_preco_btn = ttk.Button(product_frame, text="CONFIGURAR ALERTA DE PRECO", style="Action.TButton")
    alerta_preco_btn.grid(row=row, column=0, sticky="w", pady=(8, 0))

    campanha_produto_btn = ttk.Button(product_frame, text="CONFIGURAR CAMPANHA", style="Action.TButton")
    campanha_produto_btn.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

    for col in (1,):
        product_frame.columnconfigure(col, weight=1)

    rel_row = 0
    ttk.Label(relampago_frame, text="Categoria:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w")
    rel_categorias = ["Todas categorias", *categorias]
    rel_categoria_combo = ttk.Combobox(relampago_frame, textvariable=rel_categoria_var, values=rel_categorias, state="readonly")
    rel_categoria_combo.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Preco minimo:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(8, 0))
    rel_preco_min_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_preco_min_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    rel_preco_min_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Preco maximo:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(8, 0))
    rel_preco_max_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_preco_max_var,
        validate="key",
        validatecommand=vcmd_decimal,
    )
    rel_preco_max_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Desconto minimo (%):", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(8, 0))
    rel_desconto_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_desconto_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    rel_desconto_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Limite de candidatos:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(8, 0))
    rel_limite_entry = ttk.Entry(
        relampago_frame,
        textvariable=rel_limite_var,
        validate="key",
        validatecommand=vcmd_inteiro,
    )
    rel_limite_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

    for decimal_var, decimal_entry in [
        (preco_min_var, preco_min_entry),
        (preco_max_var, preco_max_entry),
        (rel_preco_min_var, rel_preco_min_entry),
        (rel_preco_max_var, rel_preco_max_entry),
    ]:
        decimal_entry.bind("<FocusOut>", lambda _e, var=decimal_var: _formatar_decimal_em_var(var))

    rel_row += 1
    rel_padrao_check = ttk.Checkbutton(relampago_frame, text="Usar modo relampago padrao", variable=rel_padrao_var)
    rel_padrao_check.grid(row=rel_row, column=0, sticky="w", pady=(8, 0))
    rel_padrao_info = ttk.Label(relampago_frame, text="(i)", style="Info.TLabel", cursor="hand2")
    rel_padrao_info.grid(row=rel_row, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
    Tooltip(rel_padrao_info, "O modo padrão busca 10 ofertas relâmpago sem especificar categoria, desconto, descrição ou faixa de preço")

    relampago_inputs = [
        rel_categoria_combo,
        rel_preco_min_entry,
        rel_preco_max_entry,
        rel_desconto_entry,
        rel_limite_entry,
    ]

    def atualizar_estado_campos_relampago():
        estado = "disabled" if rel_padrao_var.get() else "normal"

        rel_categoria_combo.configure(state="disabled" if rel_padrao_var.get() else "readonly")

        for widget in relampago_inputs[1:]:
            widget.configure(state=estado)

    rel_padrao_check.configure(command=atualizar_estado_campos_relampago)
    atualizar_estado_campos_relampago()

    rel_row += 1
    buscar_relampago_btn = ttk.Button(relampago_frame, text="BUSCAR OFERTAS RELAMPAGO", style="Action.TButton")
    buscar_relampago_btn.grid(row=rel_row, column=0, columnspan=2, sticky="w", pady=(16, 0))

    relampago_frame.columnconfigure(1, weight=1)

    output_frame = ttk.LabelFrame(main_frame, text="STATUS", style="Card.TLabelframe", padding=10)
    output_frame.pack(fill="x", expand=False, pady=(12, 0))
    status_var = tk.StringVar(value="Pronto para executar.")
    ttk.Label(output_frame, textvariable=status_var, style="Hint.TLabel").pack(anchor="w")

    log_path_var = tk.StringVar(value="Log salvo em: -")
    ttk.Label(output_frame, textvariable=log_path_var, style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    resumo_text = tk.Text(
        output_frame,
        height=8,
        wrap="word",
        background="#f6f6f6",
        foreground="#303030",
        borderwidth=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground="#d5e0e7",
        highlightcolor="#2fa6bf",
    )
    resumo_text.pack(fill="x", expand=False, pady=(8, 0))
    resumo_text.configure(state="disabled")

    schedules_frame = ttk.LabelFrame(main_frame, text="PROGRAMACOES", style="Card.TLabelframe", padding=8)
    schedules_frame.pack(fill="both", expand=True, pady=(10, 0))
    output_frame.pack_forget()
    output_frame.pack(fill="x", expand=False, pady=(12, 0))

    schedules_actions = ttk.Frame(schedules_frame, style="Main.TFrame")
    schedules_actions.pack(fill="x", pady=(0, 8))

    alerta_config_btn = ttk.Button(schedules_actions, text="CONFIGURAR ALERTA DE PRECO", style="Action.TButton")
    alerta_config_btn.pack(side="left")

    campanha_config_btn = ttk.Button(schedules_actions, text="CONFIGURAR CAMPANHA", style="Action.TButton")
    campanha_config_btn.pack(side="left", padx=(8, 0))

    delete_selected_btn = ttk.Button(schedules_actions, text="EXCLUIR SELECIONADAS", style="Action.TButton")
    delete_selected_btn.pack(side="left", padx=(8, 0))

    selecionar_todas_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(schedules_actions, text="Selecionar todas", variable=selecionar_todas_var).pack(side="left", padx=(12, 0))

    filtro_programacoes_var = tk.StringVar(value="")
    ttk.Label(schedules_actions, text="Buscar (ID/Nome):", style="Hint.TLabel").pack(side="left", padx=(18, 6))
    ttk.Entry(schedules_actions, textvariable=filtro_programacoes_var, width=28).pack(side="left")

    grid_wrap = ttk.Frame(schedules_frame, style="Main.TFrame")
    grid_wrap.pack(fill="both", expand=True)

    hub_schedule_tree = ttk.Treeview(
        grid_wrap,
        columns=("sel", "editar", "excluir", "executar", "ativo", "id", "nome", "tipo", "inicio", "fim", "ultima", "proxima", "ciclo", "execucao"),
        show="headings",
        height=9,
    )

    hub_schedule_tree.heading("sel", text="Sel")
    hub_schedule_tree.heading("editar", text="Editar")
    hub_schedule_tree.heading("excluir", text="Excluir")
    hub_schedule_tree.heading("executar", text="Executar")
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

    hub_schedule_tree.column("sel", width=44, anchor="center")
    hub_schedule_tree.column("editar", width=72, anchor="center")
    hub_schedule_tree.column("excluir", width=72, anchor="center")
    hub_schedule_tree.column("executar", width=80, anchor="center")
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

    schedules_scroll = ttk.Scrollbar(grid_wrap, orient="vertical", command=hub_schedule_tree.yview)
    hub_schedule_tree.configure(yscrollcommand=schedules_scroll.set)
    hub_schedule_tree.pack(side="left", fill="both", expand=True)
    schedules_scroll.pack(side="right", fill="y")

    alerts = load_alerts_config(ALERTS_CONFIG_FILE)
    hub_schedules = load_hub_schedules_config(HUB_SCHEDULES_CONFIG_FILE)
    scheduler_state = {"running": False}
    worker_running = {"value": False}
    worker_log = {"path": None}
    worker_messages = queue.Queue()

    def persist_hub_schedules():
        save_hub_schedules_config(HUB_SCHEDULES_CONFIG_FILE, hub_schedules)

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

        last_check = _parse_iso_datetime(alert.get("last_check_at"))
        intervalo_horas = max(1, int(alert.get("interval_hours", 1)))
        if last_check is None:
            return "Agora"

        return _formatar_data_hora_curta(last_check + timedelta(hours=intervalo_horas))

    def _proxima_execucao_campanha(schedule, now=None):
        now = now or datetime.now()
        if not schedule.get("active", True):
            return "-"

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
        if not alert.get("active", True):
            return "Inativo"

        last_check = _parse_iso_datetime(alert.get("last_check_at"))
        interval_hours = max(1, int(alert.get("interval_hours", 1)))

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
                    "inicio": "-",
                    "fim": "-",
                    "ultima": _formatar_data_hora(alert.get("last_check_at")),
                    "proxima": _proxima_execucao_alerta(alert),
                    "ciclo": f"{int(alert.get('interval_hours', 1))}h",
                    "execucao": _formatar_status_alerta(alert),
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
                values=("", "", "", "", "", "", "Nenhuma configuracao cadastrada", "", "", "", "", "", "", ""),
            )
            return

        for item in itens:
            marcado = "☑" if item["key"] in programacoes_selecionadas else "☐"

            hub_schedule_tree.insert(
                "",
                "end",
                iid=item["key"],
                values=(
                    marcado,
                    "Editar",
                    "Excluir",
                    "Agora",
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
                ),
            )

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

    def _build_hub_args_from_values(categoria, descricao, preco_min, preco_max, desconto_min):
        args = ["--produto-por-html"]

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

        return args

    def _build_hub_args_from_schedule(schedule):
        return _build_hub_args_from_values(
            (schedule.get("categoria") or "").strip(),
            (schedule.get("descricao") or "").strip(),
            schedule.get("preco_minimo"),
            schedule.get("preco_maximo"),
            schedule.get("desconto_minimo"),
        )

    def open_hub_schedule_modal(schedule=None):
        modal = tk.Toplevel(root)
        modal.title("Configurar rotina programada do hub")
        modal.geometry("760x560")
        modal.minsize(700, 520)
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
        ativo_var = tk.BooleanVar(value=(bool(schedule.get("active", True)) if schedule else True))

        inicio_lock = {"value": False}
        fim_lock = {"value": False}
        inicio_var.trace_add("write", lambda *_: _aplicar_mascara_data(inicio_var, inicio_lock))
        fim_var.trace_add("write", lambda *_: _aplicar_mascara_data(fim_var, fim_lock))

        ttk.Label(frame, text="Nome:", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=(14, 0))
        ttk.Entry(frame, textvariable=nome_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(14, 0))

        ttk.Label(frame, text="Inicio:", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=inicio_var).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Fim:", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=fim_var).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Executar a cada (horas):", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=ciclo_var, validate="key", validatecommand=vcmd_inteiro).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Categoria:", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Combobox(frame, textvariable=categoria_ag_var, values=["Todas categorias", *categorias], state="readonly").grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Descricao (opcional):", style="Field.TLabel").grid(row=6, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=descricao_ag_var).grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Preco minimo (opcional):", style="Field.TLabel").grid(row=7, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=preco_min_ag_var).grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Preco maximo (opcional):", style="Field.TLabel").grid(row=8, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=preco_max_ag_var).grid(row=8, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Desconto minimo (%) opcional:", style="Field.TLabel").grid(row=9, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=desconto_ag_var).grid(row=9, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Checkbutton(frame, text="Rotina ativa", variable=ativo_var).grid(row=10, column=0, columnspan=2, sticky="w", pady=(12, 0))

        botoes = ttk.Frame(frame, style="Main.TFrame")
        botoes.grid(row=11, column=0, columnspan=2, sticky="w", pady=(18, 0))

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
            except ValueError as exc:
                messagebox.showerror("Validacao", str(exc), parent=modal)
                return

            if fim_dt and fim_dt <= inicio_dt:
                messagebox.showerror("Validacao", "Fim deve ser maior que o inicio.", parent=modal)
                return

            categoria_valor = (categoria_ag_var.get() or "Todas categorias").strip() or "Todas categorias"
            descricao_valor = (descricao_ag_var.get() or "").strip()

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
                    "preco_minimo": preco_min,
                    "preco_maximo": preco_max,
                    "desconto_minimo": desconto_min,
                    "last_run_at": None,
                }
                hub_schedules.append(novo)
                status_var.set(f"Rotina '{nome}' criada.")
            else:
                schedule["name"] = nome
                schedule["active"] = bool(ativo_var.get())
                schedule["start_at"] = inicio_dt.isoformat(timespec="minutes")
                schedule["end_at"] = fim_dt.isoformat(timespec="minutes") if fim_dt else None
                schedule["interval_hours"] = int(ciclo_horas)
                schedule["categoria"] = categoria_valor
                schedule["descricao"] = descricao_valor
                schedule["preco_minimo"] = preco_min
                schedule["preco_maximo"] = preco_max
                schedule["desconto_minimo"] = desconto_min
                status_var.set(f"Rotina '{nome}' atualizada.")

            persist_hub_schedules()
            _refresh_hub_schedules_grid()
            modal.destroy()

        ttk.Button(botoes, text="Salvar", style="Action.TButton", command=salvar_rotina).pack(side="left")
        ttk.Button(botoes, text="Cancelar", command=modal.destroy).pack(side="left", padx=(8, 0))

        frame.columnconfigure(1, weight=1)

    def open_alerta_preco_form(alert=None):
        modal = tk.Toplevel(root)
        modal.title("Configurar alerta de preco")
        modal.geometry("760x560")
        modal.minsize(700, 520)
        modal.configure(bg="#ececec")
        modal.transient(root)
        modal.grab_set()

        frame = ttk.Frame(modal, style="Main.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Configurar Alerta de Preco", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        modo_var = tk.StringVar(value=((alert.get("mode") if alert else "url") or "url"))
        nome_var = tk.StringVar(value=(alert.get("name", "") if alert else ""))
        preco_alvo_var = tk.StringVar(value=("" if not alert else str(alert.get("target_price", ""))))
        intervalo_horas_var = tk.StringVar(value=(str(alert.get("interval_hours", 1)) if alert else "1"))
        descricao_alerta_var = tk.StringVar(value=(alert.get("description", "") if alert else ""))
        urls_iniciais = (alert.get("urls", []) if alert else []) or [""]

        ttk.Label(frame, text="Nome:", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=(14, 0))
        ttk.Entry(frame, textvariable=nome_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(14, 0))

        ttk.Label(frame, text="Modo:", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        modo_frame = ttk.Frame(frame, style="Main.TFrame")
        modo_frame.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(12, 0))
        ttk.Radiobutton(modo_frame, text="URL", value="url", variable=modo_var).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(modo_frame, text="Descricao", value="descricao", variable=modo_var).grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(frame, text="Preco alvo (R$):", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=preco_alvo_var).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Ciclo (horas):", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=intervalo_horas_var).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        urls_wrap = ttk.Frame(frame, style="Main.TFrame")
        urls_wrap.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        urls_frame = ttk.Frame(urls_wrap, style="Main.TFrame")
        urls_frame.grid(row=0, column=0, sticky="ew")

        ttk.Label(frame, text="Descricao do produto:", style="Field.TLabel").grid(row=6, column=0, sticky="w", pady=(12, 0))
        descricao_entry = ttk.Entry(frame, textvariable=descricao_alerta_var)
        descricao_entry.grid(row=6, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        botoes = ttk.Frame(frame, style="Main.TFrame")
        botoes.grid(row=7, column=0, columnspan=2, sticky="w", pady=(16, 0))

        url_vars = []
        url_rows = []

        def _redraw_url_fields():
            for row_widget in url_rows:
                row_widget.destroy()
            url_rows.clear()

            for idx, var in enumerate(url_vars):
                row_frame = ttk.Frame(urls_frame, style="Main.TFrame")
                row_frame.grid(row=idx, column=0, sticky="ew", pady=(0, 6))
                url_rows.append(row_frame)

                if idx == 0:
                    ttk.Label(row_frame, text="URLs:", style="Field.TLabel").grid(row=0, column=0, sticky="w")
                else:
                    ttk.Label(row_frame, text="", style="Field.TLabel").grid(row=0, column=0, sticky="w")

                ttk.Entry(row_frame, textvariable=var).grid(row=0, column=1, sticky="ew", padx=(8, 0))

                if idx == 0:
                    add_url_btn = ttk.Button(row_frame, text="+", width=3, command=lambda: _add_url_field(""))
                    add_url_btn.grid(row=0, column=2, sticky="w", padx=(6, 0))
                    Tooltip(add_url_btn, "Adicionar novo campo de URL")

                if len(url_vars) > 1:
                    btn_remove = ttk.Button(
                        row_frame,
                        text="-",
                        width=3,
                        command=lambda i=idx: _remove_url_field(i),
                    )
                    btn_remove.grid(row=0, column=3, padx=(6, 0))

                row_frame.columnconfigure(1, weight=1)

        def _add_url_field(initial_value=""):
            url_vars.append(tk.StringVar(value=initial_value))
            _redraw_url_fields()

        def _remove_url_field(index):
            if len(url_vars) <= 1:
                return
            url_vars.pop(index)
            _redraw_url_fields()

        def _toggle_mode_fields(*_):
            is_url = modo_var.get() == "url"
            if is_url:
                urls_wrap.grid()
                descricao_entry.configure(state="disabled")
            else:
                urls_wrap.grid_remove()
                descricao_entry.configure(state="normal")

        for url in urls_iniciais:
            _add_url_field(url)

        modo_var.trace_add("write", _toggle_mode_fields)
        _toggle_mode_fields()

        def salvar_alerta_form():
            nome = (nome_var.get() or "").strip() or "Alerta sem nome"
            modo = (modo_var.get() or "url").strip().lower()

            try:
                preco_alvo = parse_float(preco_alvo_var.get(), "Preco alvo")
                if preco_alvo is None or preco_alvo <= 0:
                    raise ValueError("Campo 'Preco alvo' deve ser maior que zero.")

                intervalo_horas = parse_int(intervalo_horas_var.get(), "Ciclo (horas)")
                if intervalo_horas is None or intervalo_horas < 1:
                    raise ValueError("A rotina deve ser no minimo a cada 1 hora.")
            except ValueError as exc:
                messagebox.showerror("Validacao", str(exc), parent=modal)
                return

            urls = [str(var.get()).strip() for var in url_vars if str(var.get()).strip()]
            if modo == "url":
                if not urls:
                    messagebox.showerror("Validacao", "Informe ao menos uma URL.", parent=modal)
                    return
                invalidas = [url for url in urls if not url.startswith("http://") and not url.startswith("https://")]
                if invalidas:
                    messagebox.showerror("Validacao", "Todas as URLs devem comecar com http:// ou https://.", parent=modal)
                    return

            descricao = (descricao_alerta_var.get() or "").strip()
            if modo == "descricao" and not descricao:
                messagebox.showerror("Validacao", "No modo descricao, informe a descricao do produto.", parent=modal)
                return

            if alert is None:
                alerts.append(
                    {
                        "id": _proximo_id_configuracao(),
                        "name": nome,
                        "mode": modo,
                        "target_price": preco_alvo,
                        "interval_hours": int(intervalo_horas),
                        "urls": urls,
                        "description": descricao,
                        "active": True,
                        "last_check_at": None,
                        "last_notified_price": None,
                    }
                )
                status_var.set(f"Alerta '{nome}' criado.")
            else:
                alert["name"] = nome
                alert["mode"] = modo
                alert["target_price"] = preco_alvo
                alert["interval_hours"] = int(intervalo_horas)
                alert["urls"] = urls
                alert["description"] = descricao
                status_var.set(f"Alerta '{nome}' atualizado.")

            persist_alerts()
            _refresh_hub_schedules_grid()
            modal.destroy()

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
            item["last_run_at"] = agora.isoformat(timespec="seconds")
            persist_hub_schedules()
            _refresh_hub_schedules_grid()
            args = _build_hub_args_from_schedule(item)
            launch_process(args, f"Rotina executada manualmente: {item.get('name', 'Sem nome')}")
            return

        if tipo == "alerta":
            if scheduler_state["running"]:
                messagebox.showwarning("Em execucao", "Ja existe verificacao de alertas em andamento.")
                return

            scheduler_state["running"] = True

            def worker():
                result = _check_alert_once(item)
                root.after(0, lambda: _apply_alert_results([result]))

            threading.Thread(target=worker, daemon=True).start()
            status_var.set(f"Alerta executado manualmente: {item.get('name', 'Sem nome')}")

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

        if col_id == "#5":
            tipo, item = _obter_programacao_por_key(row_id)
            if item is None:
                return
            item["active"] = not bool(item.get("active", True))
            if tipo == "alerta":
                persist_alerts()
            elif tipo == "campanha":
                persist_hub_schedules()
            _refresh_hub_schedules_grid()
            return

        if col_id == "#2":
            tipo, item = _obter_programacao_por_key(row_id)
            if tipo == "alerta":
                open_alerta_preco_form(item)
            elif tipo == "campanha":
                open_hub_schedule_modal(item)
            return

        if col_id == "#3":
            tipo, item = _obter_programacao_por_key(row_id)
            if item is None:
                return
            nome = item.get("name", "Sem nome")
            if not messagebox.askyesno("Excluir configuracao", f"Deseja excluir '{nome}'?"):
                return
            _excluir_programacao_por_key(row_id)
            programacoes_selecionadas.discard(row_id)
            _refresh_hub_schedules_grid()

        if col_id == "#4":
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
        persist_hub_schedules()
        _refresh_hub_schedules_grid()

        args = _build_hub_args_from_schedule(due_schedule)
        launch_process(args, f"Rotina programada em execucao: {due_schedule.get('name', 'Sem nome')}")

    _padronizar_formato_ids_configuracoes()
    _refresh_hub_schedules_grid()

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

        resumo_text.configure(state="normal")
        resumo_text.insert("end", texto)
        resumo_text.see("end")
        resumo_text.configure(state="disabled")
        _tratar_marcadores_autenticacao(texto)

    def _limpar_resumo():
        resumo_text.configure(state="normal")
        resumo_text.delete("1.0", "end")
        resumo_text.configure(state="disabled")

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

    def persist_alerts():
        save_alerts_config(ALERTS_CONFIG_FILE, alerts)

    def _alert_due(alert, now):
        if not alert.get("active", True):
            return False

        interval_hours = max(1, int(alert.get("interval_hours", 1)))
        last_check = _parse_iso_datetime(alert.get("last_check_at"))

        if last_check is None:
            return True

        return now - last_check >= timedelta(hours=interval_hours)

    def _check_alert_once(alert):
        mode = (alert.get("mode") or "url").strip().lower()
        target_price = float(alert.get("target_price", 0))
        lowest_price = None
        source = ""
        error_message = None

        try:
            if mode == "url":
                urls = [url for url in alert.get("urls", []) if url]
                for url in urls:
                    price, src = _fetch_price_from_url(url)
                    if price is None:
                        continue
                    if lowest_price is None or price < lowest_price:
                        lowest_price = price
                        source = src
            else:
                price, src = _fetch_price_from_description(
                    alert.get("description", ""),
                )
                lowest_price = price
                source = src
        except Exception as exc:
            error_message = str(exc)

        alert["last_check_at"] = datetime.now().isoformat(timespec="seconds")

        if error_message:
            return {
                "alert": alert,
                "triggered": False,
                "price": None,
                "source": source,
                "error": error_message,
            }

        triggered = lowest_price is not None and lowest_price <= target_price
        return {
            "alert": alert,
            "triggered": triggered,
            "price": lowest_price,
            "source": source,
            "error": None,
        }

    def _apply_alert_results(results):
        triggered_count = 0

        for result in results:
            alert = result["alert"]
            if result["error"]:
                status_var.set(f"Falha ao verificar alerta '{alert.get('name', 'Sem nome')}'.")
                continue

            if not result["triggered"]:
                continue

            price = result["price"]
            last_notified = alert.get("last_notified_price")
            if last_notified is not None and abs(float(last_notified) - float(price)) < 0.001:
                continue

            alert["last_notified_price"] = price
            triggered_count += 1

            messagebox.showinfo(
                "Alerta de preço",
                (
                    f"{alert.get('name', 'Alerta')} disparou!\n\n"
                    f"Preço encontrado: R$ {price:.2f}\n"
                    f"Preço alvo: R$ {float(alert.get('target_price', 0)):.2f}\n"
                    f"Origem: {result.get('source') or '-'}"
                ),
            )

        if triggered_count:
            status_var.set(f"{triggered_count} alerta(s) disparado(s).")

        persist_alerts()
        scheduler_state["running"] = False

    def run_scheduler_tick():
        if scheduler_state["running"]:
            return

        now = datetime.now()
        due_alerts = [alert for alert in alerts if _alert_due(alert, now)]
        if not due_alerts:
            return

        scheduler_state["running"] = True

        def worker():
            results = [_check_alert_once(alert) for alert in due_alerts]
            root.after(0, lambda: _apply_alert_results(results))

        threading.Thread(target=worker, daemon=True).start()

    def scheduler_loop():
        run_scheduler_tick()
        run_hub_scheduler_tick()
        _refresh_hub_schedules_grid()
        root.after(SCHEDULER_TICK_MS, scheduler_loop)

    root.after(SCHEDULER_TICK_MS, scheduler_loop)

    def launch_process(forward_args, status_text):
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
                root.after(0, lambda: _finish_worker(mensagem_final))
                return

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
        except ValueError as exc:
            messagebox.showerror("Validacao", str(exc))
            return

        descricao = descricao_var.get().strip()
        categoria = categoria_var.get().strip()

        args = _build_hub_args_from_values(categoria, descricao, preco_min, preco_max, desconto)

        launch_process(args, "Busca de produto por HTML do hub iniciada em nova janela.")

    def on_buscar_relampago():
        if rel_padrao_var.get():
            pasta_saida = filedialog.askdirectory(
                title="Escolha onde salvar lista_anuncios.txt",
                mustexist=True,
            )
            if not pasta_saida:
                return

            launch_process(["--relampago-padrao", "--pasta-saida", pasta_saida], "Processo de ofertas relampago padrao iniciado em nova janela.")
            return

        try:
            preco_min = parse_float(rel_preco_min_var.get(), "Preco minimo")
            preco_max = parse_float(rel_preco_max_var.get(), "Preco maximo")
            desconto = parse_int(rel_desconto_var.get(), "Desconto minimo")
            limite = parse_int(rel_limite_var.get(), "Limite de candidatos")
        except ValueError as exc:
            messagebox.showerror("Validacao", str(exc))
            return

        categoria = rel_categoria_var.get().strip()

        possui_parametro = any(
            [
                bool(categoria and categoria != "Todas categorias"),
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
        if categoria and categoria != "Todas categorias":
            args.extend(["--categoria", categoria])
        if preco_min is not None:
            args.extend(["--preco-minimo", str(preco_min)])
        if preco_max is not None:
            args.extend(["--preco-maximo", str(preco_max)])
        if desconto is not None:
            args.extend(["--desconto-minimo", str(desconto)])
        if limite is not None:
            args.extend(["--limite-candidatos", str(limite)])

        args.extend(["--pasta-saida", pasta_saida])
        launch_process(args, "Processo de ofertas relampago iniciado em nova janela.")

    buscar_produto_btn.configure(command=on_buscar_produto)
    buscar_relampago_btn.configure(command=on_buscar_relampago)
    alerta_preco_btn.configure(command=lambda: open_alerta_preco_form(None))
    campanha_produto_btn.configure(command=lambda: open_hub_schedule_modal(None))
    alerta_config_btn.configure(command=lambda: open_alerta_preco_form(None))
    campanha_config_btn.configure(command=lambda: open_hub_schedule_modal(None))
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
