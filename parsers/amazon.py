import random
import re
import time
from contextlib import suppress
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


URL_AMAZON_HOME = "https://www.amazon.com.br/ref=nav_logo"
URL_AMAZON_AFILIADOS = "https://www.amazon.com.br/b/node/122326793011"


def _normalizar_texto(valor):
	return " ".join((valor or "").split()).strip()


def _normalizar_chave_historico(valor):
	return _normalizar_texto(valor).lower()


def _parse_preco_float(texto):
	texto_limpo = _normalizar_texto(texto)
	if not texto_limpo:
		return None

	encontrado = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)", texto_limpo)
	if not encontrado:
		return None

	numero = encontrado.group(1).replace(".", "").replace(",", ".")
	try:
		return float(numero)
	except ValueError:
		return None


def _formatar_preco_brl(valor):
	if valor is None:
		return "Preço não encontrado"
	return f"R$ {float(valor):.2f}".replace(".", ",")


def _extrair_asin_de_texto(texto):
	texto_limpo = (texto or "").upper()
	encontrado = re.search(r"\b([A-Z0-9]{10})\b", texto_limpo)
	if not encontrado:
		return ""
	return encontrado.group(1)


def _extrair_asin_de_url(url):
	texto = (url or "")
	match_dp = re.search(r"/dp/([A-Z0-9]{10})", texto, flags=re.IGNORECASE)
	if match_dp:
		return match_dp.group(1).upper()

	match_gp = re.search(r"/gp/product/([A-Z0-9]{10})", texto, flags=re.IGNORECASE)
	if match_gp:
		return match_gp.group(1).upper()

	return _extrair_asin_de_texto(texto)


def _normalizar_url_produto_amazon(url, affiliate_tag=None):
	href = (url or "").strip()
	if not href:
		return ""

	if href.startswith("/"):
		href = urljoin("https://www.amazon.com.br", href)

	asin = _extrair_asin_de_url(href)
	if not asin:
		return href

	base = f"https://www.amazon.com.br/dp/{asin}"
	if affiliate_tag:
		return f"{base}?tag={affiliate_tag}"
	return base


def _calcular_desconto(preco_antigo, preco_atual):
	if preco_antigo is None or preco_atual is None:
		return None
	if preco_antigo <= 0 or preco_atual > preco_antigo:
		return None
	return int(round(((preco_antigo - preco_atual) / preco_antigo) * 100))


def _tem_preco_no_intervalo(preco_atual, preco_minimo, preco_maximo):
	if preco_atual is None:
		return False
	if preco_minimo is not None and preco_atual < preco_minimo:
		return False
	if preco_maximo is not None and preco_atual > preco_maximo:
		return False
	return True


def _coletar_cards_amazon_da_pagina(html, url_referencia, categoria, desconto_minimo, preco_minimo, preco_maximo):
	soup = BeautifulSoup(html, "html.parser")
	candidatos = []
	vistos = set()

	search_cards = soup.select("div[data-component-type='s-search-result'][data-asin]")

	for card in search_cards:
		asin = (card.get("data-asin") or "").strip().upper()
		if not asin or asin in vistos:
			continue

		title_el = card.select_one("h2 a span")
		descricao = _normalizar_texto(title_el.get_text(" ", strip=True) if title_el else "")
		if not descricao:
			continue

		link_el = card.select_one("h2 a[href]")
		href = (link_el.get("href") if link_el else "") or ""
		url_produto = _normalizar_url_produto_amazon(urljoin("https://www.amazon.com.br", href))
		if not url_produto:
			continue

		preco_atual = None
		preco_antigo = None

		preco_atual_el = card.select_one("span.a-price:not(.a-text-price) span.a-offscreen")
		if preco_atual_el:
			preco_atual = _parse_preco_float(preco_atual_el.get_text(" ", strip=True))

		preco_antigo_el = card.select_one("span.a-price.a-text-price span.a-offscreen")
		if preco_antigo_el:
			preco_antigo = _parse_preco_float(preco_antigo_el.get_text(" ", strip=True))

		if not _tem_preco_no_intervalo(preco_atual, preco_minimo, preco_maximo):
			continue

		desconto = _calcular_desconto(preco_antigo, preco_atual)
		if desconto_minimo is not None:
			if desconto is None or desconto < desconto_minimo:
				continue

		vistos.add(asin)
		candidatos.append(
			{
				"id_anuncio": asin,
				"categoria": _normalizar_texto(categoria) or "Amazon",
				"descricao": descricao,
				"antes": _formatar_preco_brl(preco_antigo) if preco_antigo is not None else "-",
				"depois": _formatar_preco_brl(preco_atual),
				"desconto": (f"{desconto}%" if desconto is not None else "-"),
				"link_original": url_produto,
				"link": url_produto,
				"url_listagem": url_referencia,
			}
		)

	if candidatos:
		return candidatos

	# Fallback para páginas que não são resultados padrão (ex.: central de afiliados).
	for anchor in soup.select("a[href*='/dp/'], a[href*='/gp/product/']"):
		href = anchor.get("href") or ""
		url_produto = _normalizar_url_produto_amazon(urljoin("https://www.amazon.com.br", href))
		asin = _extrair_asin_de_url(url_produto)
		if not url_produto or not asin or asin in vistos:
			continue

		texto_ancora = _normalizar_texto(anchor.get_text(" ", strip=True))
		if len(texto_ancora) < 8:
			continue

		vistos.add(asin)
		candidatos.append(
			{
				"id_anuncio": asin,
				"categoria": _normalizar_texto(categoria) or "Amazon",
				"descricao": texto_ancora,
				"antes": "-",
				"depois": "Preço não encontrado",
				"desconto": "-",
				"link_original": url_produto,
				"link": url_produto,
				"url_listagem": url_referencia,
			}
		)

	return candidatos


def _obter_link_curto_sitestripe(page_produto):
	botoes = [
		"#amzn-ss-get-link-button",
		"button#amzn-ss-get-link-button",
		"button[title='Obter link']",
	]

	clicou = False
	for seletor in botoes:
		with suppress(Exception):
			page_produto.locator(seletor).first.click(timeout=3500)
			clicou = True
			break

	if not clicou:
		return ""

	# Tenta selecionar explicitamente opção de link curto.
	opcoes_curto = [
		"text=Link curto",
		"text=Short Link",
		"button:has-text('Link curto')",
		"button:has-text('Short Link')",
		"a:has-text('Link curto')",
	]
	for seletor in opcoes_curto:
		with suppress(Exception):
			page_produto.locator(seletor).first.click(timeout=1200)
			break

	campos_link = [
		"#amzn-ss-text-shortlink-textarea",
		"input[id*='shortlink']",
		"textarea[id*='shortlink']",
		"input[value*='amzn.to']",
		"textarea",
		"input",
	]

	for seletor in campos_link:
		with suppress(Exception):
			loc = page_produto.locator(seletor).first
			loc.wait_for(state="visible", timeout=2500)
			valor = ""
			with suppress(Exception):
				valor = (loc.input_value(timeout=800) or "").strip()
			if not valor:
				with suppress(Exception):
					valor = (loc.inner_text(timeout=800) or "").strip()
			if "amzn.to" in valor or "amazon" in valor:
				return valor

	texto_modal = ""
	with suppress(Exception):
		texto_modal = page_produto.locator("body").inner_text(timeout=1500)
	if texto_modal:
		encontrado = re.search(r"https?://(?:www\.)?amzn\.to/[\w\-/?=&]+", texto_modal)
		if encontrado:
			return encontrado.group(0)

	return ""


def _enriquecer_link_afiliado(page, url_produto, affiliate_tag):
	pagina_item = page.context.new_page()
	try:
		pagina_item.goto(url_produto, timeout=90000, wait_until="domcontentloaded")
		time.sleep(random.uniform(1.2, 2.3))
		link_curto = _obter_link_curto_sitestripe(pagina_item)
		if link_curto:
			return link_curto
	except Exception as exc:
		print(f"[AVISO] Falha no SiteStripe para {url_produto}: {exc}")
	finally:
		with suppress(Exception):
			pagina_item.close()

	return _normalizar_url_produto_amazon(url_produto, affiliate_tag=affiliate_tag)


def _montar_url_busca_amazon(descricao, categoria):
	termos = [
		_normalizar_texto(descricao),
		_normalizar_texto(categoria),
	]
	consulta = " ".join([t for t in termos if t])
	if not consulta:
		return URL_AMAZON_AFILIADOS
	return f"https://www.amazon.com.br/s?k={quote_plus(consulta)}"


def processar_produtos_amazon_por_afiliados(
	page,
	categoria=None,
	subcategoria=None,
	descricao=None,
	urls=None,
	preco_minimo=None,
	preco_maximo=None,
	desconto_minimo=None,
	limite_candidatos=None,
	historico_anuncios=None,
	limite_validos=10,
	affiliate_tag="",
):
	"""Coleta candidatos na Amazon e enriquece com link curto via SiteStripe."""

	categoria_texto = _normalizar_texto(subcategoria or categoria)
	historico_ids = {
		_normalizar_chave_historico(item)
		for item in (historico_anuncios or set())
		if _normalizar_chave_historico(item)
	}

	limite_validos = max(1, int(limite_validos or 1))
	limite_candidatos = None if limite_candidatos is None else max(1, int(limite_candidatos))

	urls_listagem = [
		_normalizar_texto(u)
		for u in (urls or [])
		if _normalizar_texto(u)
	]

	if not urls_listagem:
		urls_listagem = [
			URL_AMAZON_AFILIADOS,
			_montar_url_busca_amazon(descricao, categoria_texto),
		]

	print("\n[AMAZON] Sessao validada. Iniciando coleta nas listagens configuradas.")

	candidatos = []
	ids_vistos = set()

	for url_listagem in urls_listagem:
		if not url_listagem:
			continue

		print(f"\n[AMAZON] Coletando candidatos em: {url_listagem}")
		try:
			page.goto(url_listagem, timeout=90000, wait_until="domcontentloaded")
			time.sleep(random.uniform(2.0, 3.2))
		except Exception as exc:
			print(f"[AVISO] Falha ao abrir listagem Amazon: {exc}")
			continue

		html = page.content()
		lote = _coletar_cards_amazon_da_pagina(
			html,
			url_listagem,
			categoria_texto,
			desconto_minimo,
			preco_minimo,
			preco_maximo,
		)

		for item in lote:
			anuncio_id = _normalizar_chave_historico(item.get("id_anuncio"))
			if not anuncio_id or anuncio_id in ids_vistos or anuncio_id in historico_ids:
				continue

			ids_vistos.add(anuncio_id)
			candidatos.append(item)

			if limite_candidatos is not None and len(candidatos) >= limite_candidatos:
				break

		if limite_candidatos is not None and len(candidatos) >= limite_candidatos:
			break

	if not candidatos:
		print("\n[AMAZON] Nenhum candidato encontrado.")
		return []

	aprovados = []
	for candidato in candidatos:
		url_produto = candidato.get("link_original") or ""
		if not url_produto:
			continue

		link_afiliado = _enriquecer_link_afiliado(page, url_produto, affiliate_tag=affiliate_tag)
		if not link_afiliado:
			continue

		candidato["link"] = link_afiliado
		if not candidato.get("categoria"):
			candidato["categoria"] = "Amazon"

		aprovados.append(candidato)
		if len(aprovados) >= limite_validos:
			break

	if not aprovados:
		print("\n[AMAZON] Nenhum candidato com link de afiliado valido.")
		return []

	print(f"\n[AMAZON] {len(aprovados)} oferta(s) validada(s) com link de afiliado.")
	return aprovados
