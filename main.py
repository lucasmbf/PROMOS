from playwright.sync_api import sync_playwright

from parsers.mercadolivre import mercado_livre

import random
import time


links = [

    "https://meli.la/2Kq5XRb", 
    "https://meli.la/1WhHT8g",
    "https://meli.la/2F2xN6H",
    "https://meli.la/1dy7YiJ",
    "https://meli.la/1kW5HS2"
]


lista_produtos = []


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
        "https://www.mercadolivre.com.br"
    )

    print(
        "\nFaça login manualmente no Mercado Livre."
    )

    print(
        "Depois pressione ENTER."
    )

    input()

    for link in links:

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

        lista_produtos.append(
            produto
        )

        time.sleep(
            random.uniform(5, 10)
        )

    context.close()


with open(

    "produtos.txt",

    "w",

    encoding="utf-8"

) as arquivo:

    for produto in lista_produtos:

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

print(

    "\nArquivo produtos.txt gerado com sucesso!"
)