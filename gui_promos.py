import argparse
import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus
import tkinter as tk
from tkinter import messagebox, ttk

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
ALERTS_CONFIG_FILE = BASE_DIR / "alertas_preco.json"
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


def _parse_iso_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def run_main_mode(forward_args):
    sys.argv = ["main.py", *forward_args]
    import main  # noqa: F401


def build_worker_command(args):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-main", *args]

    return [sys.executable, str(BASE_DIR / "gui_promos.py"), "--run-main", *args]


def build_styles(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    bg = "#ececec"
    panel = "#dedede"
    accent = "#47c4c8"
    input_bg = "#f6f6f6"

    root.configure(bg=bg)

    style.configure("Main.TFrame", background=bg)
    style.configure("Card.TLabelframe", background=panel, bordercolor=accent, borderwidth=2, relief="solid")
    style.configure("Card.TLabelframe.Label", background=panel, foreground=accent, font=("Segoe UI Semibold", 11))
    style.configure("Header.TLabel", background=bg, foreground=accent, font=("Segoe UI", 22, "bold"))
    style.configure("Hint.TLabel", background=bg, foreground="#5b5b5b", font=("Segoe UI", 10))
    style.configure("Field.TLabel", background=panel, foreground="#474747", font=("Segoe UI", 10, "bold"))
    style.configure("Info.TLabel", background=panel, foreground=accent, font=("Segoe UI", 10, "bold"))
    style.configure("Action.TButton", background=accent, foreground="#ffffff", font=("Segoe UI", 10, "bold"), borderwidth=0, padding=(12, 8))
    style.map("Action.TButton", background=[("active", "#35aeb2")])
    style.configure("TEntry", fieldbackground=input_bg, background=input_bg, bordercolor=accent, lightcolor=accent, darkcolor=accent, borderwidth=1)
    style.configure("TCombobox", fieldbackground=input_bg, background=input_bg, bordercolor=accent, lightcolor=accent, darkcolor=accent)
    style.configure("TCheckbutton", background=panel, foreground="#3f3f3f", font=("Segoe UI", 10))


def create_gui(categorias):
    root = tk.Tk()
    root.title("Promos - Interface")
    root.geometry("1160x760")
    root.minsize(1024, 700)

    build_styles(root)

    main_frame = ttk.Frame(root, style="Main.TFrame", padding=18)
    main_frame.pack(fill="both", expand=True)

    ttk.Label(main_frame, text="BEM VINDO!", style="Header.TLabel").pack(anchor="w")
    ttk.Label(main_frame, text="Entre com os dados do processo no formulario.", style="Hint.TLabel").pack(anchor="w", pady=(0, 10))

    top = ttk.Frame(main_frame, style="Main.TFrame")
    top.pack(fill="both", expand=True)

    product_frame = ttk.LabelFrame(top, text="PROCURAR PRODUTO", style="Card.TLabelframe", padding=14)
    product_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

    relampago_frame = ttk.LabelFrame(top, text="PROCURAR OFERTAS RELAMPAGO", style="Card.TLabelframe", padding=14)
    relampago_frame.pack(side="right", fill="both", expand=True, padx=(8, 0))

    descricao_var = tk.StringVar()
    preco_min_var = tk.StringVar()
    preco_max_var = tk.StringVar()
    desconto_var = tk.StringVar(value="30")
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
    rel_preco_max_var = tk.StringVar(value="400")
    rel_desconto_var = tk.StringVar(value="30")
    rel_limite_var = tk.StringVar(value="10")
    rel_categoria_var = tk.StringVar(value="Todas categorias")
    rel_padrao_var = tk.BooleanVar(value=True)

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
    ttk.Label(product_frame, text="Categoria:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(12, 0))
    categorias_combo = ttk.Combobox(product_frame, textvariable=categoria_var, values=["", *categorias], state="readonly")
    categorias_combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(12, 0))

    row += 1
    ttk.Label(product_frame, text="Preco minimo:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(12, 0))
    ttk.Entry(product_frame, textvariable=preco_min_var).grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(12, 0))

    row += 1
    ttk.Label(product_frame, text="Preco maximo:", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(12, 0))
    ttk.Entry(product_frame, textvariable=preco_max_var).grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(12, 0))

    row += 1
    ttk.Label(product_frame, text="Desconto minimo (%):", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(12, 0))
    ttk.Entry(product_frame, textvariable=desconto_var).grid(row=row, column=1, sticky="ew", padx=(6, 6), pady=(12, 0))

    row += 1
    ttk.Checkbutton(product_frame, text="Priorizar menor preco", variable=menor_preco_var).grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 0))

    row += 1
    buscar_produto_btn = ttk.Button(product_frame, text="BUSCAR PRODUTO", style="Action.TButton")
    buscar_produto_btn.grid(row=row, column=0, columnspan=3, sticky="w", pady=(16, 0))

    row += 1
    alerta_preco_btn = ttk.Button(product_frame, text="ALERTA DE PRECO", style="Action.TButton")
    alerta_preco_btn.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))

    for col in (1,):
        product_frame.columnconfigure(col, weight=1)

    rel_row = 0
    ttk.Label(relampago_frame, text="Categoria:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w")
    rel_categorias = ["Todas categorias", *categorias]
    rel_categoria_combo = ttk.Combobox(relampago_frame, textvariable=rel_categoria_var, values=rel_categorias, state="readonly")
    rel_categoria_combo.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Preco minimo:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(12, 0))
    rel_preco_min_entry = ttk.Entry(relampago_frame, textvariable=rel_preco_min_var)
    rel_preco_min_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Preco maximo:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(12, 0))
    rel_preco_max_entry = ttk.Entry(relampago_frame, textvariable=rel_preco_max_var)
    rel_preco_max_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Desconto minimo (%):", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(12, 0))
    rel_desconto_entry = ttk.Entry(relampago_frame, textvariable=rel_desconto_var)
    rel_desconto_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

    rel_row += 1
    ttk.Label(relampago_frame, text="Limite de candidatos:", style="Field.TLabel").grid(row=rel_row, column=0, sticky="w", pady=(12, 0))
    rel_limite_entry = ttk.Entry(relampago_frame, textvariable=rel_limite_var)
    rel_limite_entry.grid(row=rel_row, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

    rel_row += 1
    rel_padrao_check = ttk.Checkbutton(relampago_frame, text="Usar modo relampago padrao", variable=rel_padrao_var)
    rel_padrao_check.grid(row=rel_row, column=0, sticky="w", pady=(12, 0))
    rel_padrao_info = ttk.Label(relampago_frame, text="(i)", style="Info.TLabel", cursor="hand2")
    rel_padrao_info.grid(row=rel_row, column=1, sticky="w", padx=(8, 0), pady=(12, 0))
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

    alerts = load_alerts_config(ALERTS_CONFIG_FILE)
    scheduler_state = {"running": False}

    def persist_alerts():
        save_alerts_config(ALERTS_CONFIG_FILE, alerts)

    def open_alerta_preco_modal():
        modal = tk.Toplevel(root)
        modal.title("Configurar alerta de preco")
        modal.geometry("980x760")
        modal.minsize(900, 700)
        modal.configure(bg="#ececec")
        modal.transient(root)
        modal.grab_set()

        frame = ttk.Frame(modal, style="Main.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Configurar Alerta de Preco", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")

        modo_var = tk.StringVar(value="url")
        nome_var = tk.StringVar()
        preco_alvo_var = tk.StringVar()
        intervalo_horas_var = tk.StringVar(value="1")
        descricao_alerta_var = tk.StringVar()
        ativo_var = tk.BooleanVar(value=True)
        editing_alert_id = {"value": None}
        selection_vars = {}
        alert_rows = []
        select_all_var = tk.BooleanVar(value=False)

        save_button_text = tk.StringVar(value="Salvar alerta")
        form_status_var = tk.StringVar(value="")

        ttk.Label(frame, text="Nome do alerta:", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=nome_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="Modo:", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))

        modo_frame = ttk.Frame(frame, style="Main.TFrame")
        modo_frame.grid(row=2, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=(12, 0))

        rb_url = ttk.Radiobutton(modo_frame, text="Por URL (Recomendável)", value="url", variable=modo_var)
        rb_desc = ttk.Radiobutton(modo_frame, text="Por descrição do produto", value="descricao", variable=modo_var)
        rb_url.grid(row=0, column=0, sticky="w")
        rb_desc.grid(row=0, column=1, sticky="w", padx=(12, 0))

        obs_url = ttk.Label(frame, text="Observação: Recomendável usar por URL para maior precisão.", style="Hint.TLabel")
        obs_url.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="Preço alvo (R$):", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=preco_alvo_var).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        ttk.Label(frame, text="A cada X horas:", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=intervalo_horas_var).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        ttk.Label(frame, text="(mínimo 1 hora)", style="Hint.TLabel").grid(row=5, column=2, sticky="w", padx=(8, 0), pady=(12, 0))

        urls_wrap = ttk.Frame(frame, style="Main.TFrame")
        urls_wrap.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(14, 0))

        ttk.Label(urls_wrap, text="URLs do produto:", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        add_url_btn = ttk.Button(urls_wrap, text="+", width=3)
        add_url_btn.grid(row=0, column=1, sticky="w", padx=(8, 0))
        Tooltip(add_url_btn, "Clique para adicionar mais URLs")

        urls_frame = ttk.Frame(urls_wrap, style="Main.TFrame")
        urls_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        desc_wrap = ttk.Frame(frame, style="Main.TFrame")
        desc_wrap.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Label(desc_wrap, text="Descrição do produto:", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(desc_wrap, textvariable=descricao_alerta_var).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Checkbutton(frame, text="Ativo", variable=ativo_var).grid(row=8, column=0, sticky="w", pady=(16, 0))

        ttk.Label(frame, textvariable=form_status_var, style="Hint.TLabel").grid(row=8, column=1, columnspan=2, sticky="w", pady=(16, 0), padx=(8, 0))

        botoes_frame = ttk.Frame(frame, style="Main.TFrame")
        botoes_frame.grid(row=9, column=0, columnspan=3, sticky="w", pady=(16, 0))

        config_frame = ttk.LabelFrame(frame, text="CONFIGURACOES CRIADAS", style="Card.TLabelframe", padding=10)
        config_frame.grid(row=10, column=0, columnspan=3, sticky="nsew", pady=(16, 0))

        config_actions = ttk.Frame(config_frame, style="Main.TFrame")
        config_actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Checkbutton(
            config_actions,
            text="Selecionar tudo",
            variable=select_all_var,
            command=lambda: toggle_select_all(),
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Button(config_actions, text="Excluir selecionados", command=lambda: delete_selected_alerts()).grid(row=0, column=1, sticky="w")

        grid_header = ttk.Frame(config_frame, style="Main.TFrame")
        grid_header.grid(row=1, column=0, sticky="ew")

        ttk.Label(grid_header, text="Sel", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(grid_header, text="Nome", style="Field.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(grid_header, text="Modo", style="Field.TLabel").grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(grid_header, text="Preco alvo", style="Field.TLabel").grid(row=0, column=3, sticky="w", padx=(8, 0))
        ttk.Label(grid_header, text="Intervalo", style="Field.TLabel").grid(row=0, column=4, sticky="w", padx=(8, 0))
        ttk.Label(grid_header, text="Origem", style="Field.TLabel").grid(row=0, column=5, sticky="w", padx=(8, 0))
        ttk.Label(grid_header, text="Acoes", style="Field.TLabel").grid(row=0, column=6, sticky="w", padx=(8, 0))

        rows_container = ttk.Frame(config_frame, style="Main.TFrame")
        rows_container.grid(row=2, column=0, sticky="nsew", pady=(6, 0))

        lista_urls_vars = []
        url_rows = []

        def redraw_url_fields():
            for row_widget in url_rows:
                row_widget.destroy()
            url_rows.clear()

            for idx, var in enumerate(lista_urls_vars):
                row_frame = ttk.Frame(urls_frame, style="Main.TFrame")
                row_frame.grid(row=idx, column=0, sticky="ew", pady=(0, 6))
                url_rows.append(row_frame)

                ttk.Entry(row_frame, textvariable=var).grid(row=0, column=0, sticky="ew")
                if len(lista_urls_vars) > 1:
                    btn_remove = ttk.Button(
                        row_frame,
                        text="-",
                        width=3,
                        command=lambda i=idx: remove_url_field(i),
                    )
                    btn_remove.grid(row=0, column=1, padx=(6, 0))

                row_frame.columnconfigure(0, weight=1)

        def add_url_field(initial_value=""):
            var = tk.StringVar(value=initial_value)
            lista_urls_vars.append(var)
            redraw_url_fields()

        def remove_url_field(index):
            if len(lista_urls_vars) <= 1:
                return
            lista_urls_vars.pop(index)
            redraw_url_fields()

        def toggle_mode_fields():
            is_url = modo_var.get() == "url"

            urls_wrap.grid() if is_url else urls_wrap.grid_remove()
            desc_wrap.grid_remove() if is_url else desc_wrap.grid()

        def reset_form():
            editing_alert_id["value"] = None
            save_button_text.set("Salvar alerta")
            form_status_var.set("")

            modo_var.set("url")
            nome_var.set("")
            preco_alvo_var.set("")
            intervalo_horas_var.set("1")
            descricao_alerta_var.set("")
            ativo_var.set(True)

            lista_urls_vars.clear()
            add_url_field("")
            toggle_mode_fields()

        def apply_alert_to_form(alert):
            editing_alert_id["value"] = alert.get("id")
            save_button_text.set("Salvar alteracoes")
            form_status_var.set("Modo edicao ativo")

            modo = (alert.get("mode") or "url").strip().lower()
            modo_var.set("descricao" if modo == "descricao" else "url")
            nome_var.set(alert.get("name", ""))
            preco_alvo_var.set(str(alert.get("target_price", "")))
            intervalo_horas_var.set(str(alert.get("interval_hours", 1)))
            descricao_alerta_var.set(alert.get("description", ""))
            ativo_var.set(bool(alert.get("active", True)))

            lista_urls_vars.clear()
            urls = alert.get("urls", []) or [""]
            for url in urls:
                add_url_field(url)

            toggle_mode_fields()

        def format_origem(alert):
            mode = (alert.get("mode") or "url").strip().lower()
            if mode == "url":
                urls = [u for u in alert.get("urls", []) if u]
                if not urls:
                    return "-"
                if len(urls) == 1:
                    return urls[0][:40] + ("..." if len(urls[0]) > 40 else "")
                return f"{len(urls)} URLs"
            descricao = (alert.get("description") or "").strip()
            if not descricao:
                return "-"
            return descricao[:40] + ("..." if len(descricao) > 40 else "")

        def update_select_all_state():
            if not selection_vars:
                select_all_var.set(False)
                return

            select_all_var.set(all(var.get() for var in selection_vars.values()))

        def toggle_select_all():
            mark_all = bool(select_all_var.get())
            for var in selection_vars.values():
                var.set(mark_all)

        def delete_one(alert_id):
            index = next((i for i, alert in enumerate(alerts) if alert.get("id") == alert_id), None)
            if index is None:
                return

            alerts.pop(index)
            persist_alerts()

            if editing_alert_id["value"] == alert_id:
                reset_form()

            render_alert_rows()

        def delete_selected_alerts():
            selected_ids = [
                alert_id for alert_id, var in selection_vars.items() if var.get()
            ]

            if not selected_ids:
                messagebox.showwarning("Atencao", "Selecione ao menos uma configuracao para excluir.", parent=modal)
                return

            remaining = [alert for alert in alerts if alert.get("id") not in selected_ids]
            alerts.clear()
            alerts.extend(remaining)
            persist_alerts()

            if editing_alert_id["value"] in selected_ids:
                reset_form()

            render_alert_rows()

        def render_alert_rows():
            for row in alert_rows:
                row.destroy()
            alert_rows.clear()
            selection_vars.clear()
            select_all_var.set(False)

            if not alerts:
                empty_label = ttk.Label(rows_container, text="Nenhuma configuracao cadastrada.", style="Hint.TLabel")
                empty_label.grid(row=0, column=0, sticky="w")
                alert_rows.append(empty_label)
                return

            for idx, alert in enumerate(alerts):
                row_frame = ttk.Frame(rows_container, style="Main.TFrame")
                row_frame.grid(row=idx, column=0, sticky="ew", pady=(0, 4))
                alert_rows.append(row_frame)

                alert_id = alert.get("id")
                selected_var = tk.BooleanVar(value=False)
                selection_vars[alert_id] = selected_var

                ttk.Checkbutton(
                    row_frame,
                    variable=selected_var,
                    command=update_select_all_state,
                ).grid(row=0, column=0, sticky="w")
                ttk.Label(row_frame, text=alert.get("name", "-"), style="Hint.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
                ttk.Label(row_frame, text=(alert.get("mode") or "url"), style="Hint.TLabel").grid(row=0, column=2, sticky="w", padx=(8, 0))
                ttk.Label(row_frame, text=f"R$ {float(alert.get('target_price', 0)):.2f}", style="Hint.TLabel").grid(row=0, column=3, sticky="w", padx=(8, 0))
                ttk.Label(row_frame, text=f"{int(alert.get('interval_hours', 1))}h", style="Hint.TLabel").grid(row=0, column=4, sticky="w", padx=(8, 0))
                ttk.Label(row_frame, text=format_origem(alert), style="Hint.TLabel").grid(row=0, column=5, sticky="w", padx=(8, 0))

                edit_btn = ttk.Button(row_frame, text="✎", width=3, command=lambda a=alert: apply_alert_to_form(a))
                edit_btn.grid(row=0, column=6, sticky="w", padx=(8, 0))
                Tooltip(edit_btn, "Editar configuracao")

                delete_btn = ttk.Button(row_frame, text="🗑", width=3, command=lambda aid=alert_id: delete_one(aid))
                delete_btn.grid(row=0, column=7, sticky="w", padx=(6, 0))
                Tooltip(delete_btn, "Excluir configuracao")

                row_frame.columnconfigure(5, weight=1)

        def salvar_alerta():
            nome = nome_var.get().strip() or "Alerta sem nome"

            try:
                preco_alvo = parse_float(preco_alvo_var.get(), "Preço alvo")
                if preco_alvo is None or preco_alvo <= 0:
                    raise ValueError("Campo 'Preço alvo' deve ser maior que zero.")

                intervalo_horas = parse_int(intervalo_horas_var.get(), "A cada X horas")
                if intervalo_horas is None or intervalo_horas < 1:
                    raise ValueError("A rotina deve ser no mínimo a cada 1 hora.")
            except ValueError as exc:
                messagebox.showerror("Validação", str(exc), parent=modal)
                return

            modo = modo_var.get()
            urls = [var.get().strip() for var in lista_urls_vars if var.get().strip()]

            if modo == "url":
                if not urls:
                    messagebox.showerror("Validação", "Informe pelo menos uma URL para o alerta.", parent=modal)
                    return

                invalid_urls = [url for url in urls if not url.startswith("http://") and not url.startswith("https://")]
                if invalid_urls:
                    messagebox.showerror("Validação", "Todas as URLs devem começar com http:// ou https://.", parent=modal)
                    return

            descricao_alerta = descricao_alerta_var.get().strip()
            if modo == "descricao" and not descricao_alerta:
                messagebox.showerror("Validação", "No modo descrição, informe a descrição do produto.", parent=modal)
                return

            existing = next((alert for alert in alerts if alert.get("id") == editing_alert_id["value"]), None)

            if existing is None:
                alert = {
                    "id": int(datetime.now().timestamp() * 1000),
                    "name": nome,
                    "mode": modo,
                    "target_price": preco_alvo,
                    "interval_hours": intervalo_horas,
                    "urls": urls,
                    "description": descricao_alerta,
                    "active": bool(ativo_var.get()),
                    "last_check_at": None,
                    "last_notified_price": None,
                }
                alerts.append(alert)
                status_var.set(f"Alerta '{nome}' salvo com sucesso.")
            else:
                existing["name"] = nome
                existing["mode"] = modo
                existing["target_price"] = preco_alvo
                existing["interval_hours"] = intervalo_horas
                existing["urls"] = urls
                existing["description"] = descricao_alerta
                existing["active"] = bool(ativo_var.get())
                status_var.set(f"Alerta '{nome}' atualizado com sucesso.")

            persist_alerts()
            render_alert_rows()
            reset_form()

        add_url_btn.configure(command=lambda: add_url_field(""))
        add_url_field("")

        modo_var.trace_add("write", lambda *_: toggle_mode_fields())
        toggle_mode_fields()
        render_alert_rows()

        ttk.Button(botoes_frame, textvariable=save_button_text, style="Action.TButton", command=salvar_alerta).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(botoes_frame, text="Limpar", command=reset_form).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(botoes_frame, text="Fechar", command=modal.destroy).grid(row=0, column=2)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(10, weight=1)
        urls_wrap.columnconfigure(2, weight=1)
        urls_frame.columnconfigure(0, weight=1)
        desc_wrap.columnconfigure(1, weight=1)
        config_frame.columnconfigure(0, weight=1)
        config_frame.rowconfigure(2, weight=1)
        rows_container.columnconfigure(0, weight=1)

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
        root.after(SCHEDULER_TICK_MS, scheduler_loop)

    root.after(SCHEDULER_TICK_MS, scheduler_loop)

    def launch_process(forward_args, status_text):
        cmd = build_worker_command(forward_args)
        try:
            subprocess.Popen(cmd, cwd=BASE_DIR)
            status_var.set(status_text)
        except Exception as exc:
            messagebox.showerror("Falha", f"Nao foi possivel iniciar o processo.\n\n{exc}")

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

        args = ["--produto-por-html"]
        if categoria:
            args.extend(["--categoria", categoria])

        if descricao:
            args.extend(["--descricao-produto", descricao])

        if preco_min is not None:
            args.extend(["--preco-minimo", str(preco_min)])

        if preco_max is not None:
            args.extend(["--preco-maximo", str(preco_max)])

        if desconto is not None:
            args.extend(["--desconto-minimo", str(desconto)])

        launch_process(args, "Busca de produto por HTML do hub iniciada em nova janela.")

    def on_buscar_relampago():
        try:
            preco_min = parse_float(rel_preco_min_var.get(), "Preco minimo")
            preco_max = parse_float(rel_preco_max_var.get(), "Preco maximo")
            desconto = parse_int(rel_desconto_var.get(), "Desconto minimo")
            limite = parse_int(rel_limite_var.get(), "Limite de candidatos")
        except ValueError as exc:
            messagebox.showerror("Validacao", str(exc))
            return

        categoria = rel_categoria_var.get().strip()
        args = []

        if rel_padrao_var.get():
            args.append("--relampago-padrao")
        else:
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

        launch_process(args, "Processo de ofertas relampago iniciado em nova janela.")

    buscar_produto_btn.configure(command=on_buscar_produto)
    buscar_relampago_btn.configure(command=on_buscar_relampago)
    alerta_preco_btn.configure(command=open_alerta_preco_modal)

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
