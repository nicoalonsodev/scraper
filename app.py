from flask import Flask, request, jsonify
import os
import re
import requests
from bs4 import BeautifulSoup
# from flask_cors import CORS  # <- descomenta si lo vas a consumir desde otro dominio

app = Flask(__name__)
# CORS(app, resources={r"/*": {"origins": "*"}})  # opcional

# Tipo de cambio (configurable por env var en Railway)
USD_ARS = float(os.environ.get("ML_USD_ARS", 1210))

# -------------------- UTILIDADES --------------------
def _parse_price(texto: str):
    """
    Acepta: $ 1.234.567  |  US$ 10.500  |  U$S 10.500
    Devuelve (monto_ARS_float, string_mostrado) o (None, original)
    """
    t = (texto or "").replace("\xa0", " ").strip()

    m_usd = re.search(r'(?:US\$|U\$S)\s*([\d\.\,]+)', t)
    if m_usd:
        digits = re.sub(r'[^\d]', '', m_usd.group(1))
        if digits:
            usd = float(digits)
            return usd * USD_ARS, f"US$ {usd:,}".replace(",", ".")
    m_ars = re.search(r'\$\s*([\d\.\,]+)', t)
    if m_ars:
        digits = re.sub(r'[^\d]', '', m_ars.group(1))
        if digits:
            ars = float(digits)
            return ars, f"$ {int(ars):,}".replace(",", ".")
    return None, texto

def _extract_year_km(card):
    text = card.get_text(" ", strip=True)
    year = None
    km = None
    my = re.search(r'\b(19|20)\d{2}\b', text)
    if my:
        year = my.group(0)
    mk = re.search(r'([\d\.\,]+)\s*km\b', text, re.I)
    if mk:
        km = mk.group(0)
    return year, km

def _extract_title_and_link(card):
    # 1) tu selector original
    t = card.find(class_="poly-component__title")
    if t and t.get_text(strip=True):
        a = t.find('a')
        href = a['href'] if a and a.has_attr('href') else None
        return t.get_text(strip=True), href
    # 2) variantes comunes
    a = card.select_one("a.ui-search-result__content-wrapper, a.ui-search-link")
    if a and a.get_text(strip=True):
        return a.get_text(strip=True), (a['href'] if a.has_attr('href') else None)
    # 3) fallback genérico
    a2 = card.find('a', href=True)
    if a2 and a2.get_text(strip=True):
        return a2.get_text(strip=True), a2['href']
    return None, None

def _extract_price_text(card):
    # 1) contenedores de precio más comunes
    for sel in [
        ".andes-money-amount",
        ".price-tag-amount",
        ".ui-search-price__part",
        ".ui-search-price__second-line",
    ]:
        node = card.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if re.search(r'(?:US\$|U\$S|\$)\s*[\d\.\,]+', txt):
                return txt
    # 2) símbolo + fracción
    symbol = card.select_one(".andes-money-amount__currency-symbol, .price-tag-symbol")
    fraction = card.select_one(".andes-money-amount__fraction, .price-tag-fraction, .ui-search-price__fraction")
    if fraction:
        return f"{symbol.get_text(strip=True) if symbol else '$'} {fraction.get_text(strip=True)}"
    # 3) aria-label (variante accesible)
    for el in card.select('[aria-label]'):
        val = el.get("aria-label", "")
        if re.search(r'(?:US\$|U\$S|\$)\s*[\d\.\,]+', val):
            return val
    # 4) itemprop/metadata
    itemprop_price = card.select_one('[itemprop="price"], meta[itemprop="price"]')
    if itemprop_price:
        content = itemprop_price.get("content") or itemprop_price.get_text(" ", strip=True)
        if content and re.search(r'[\d\.\,]+', content):
            return f"$ {content}"
    # 5) regex sobre todo el texto
    full_text = card.get_text(" ", strip=True)
    m = re.search(r'(?:US\$|U\$S|\$)\s*[\d\.\,]+', full_text)
    if m:
        return m.group(0)
    return None

def _is_antibot_interstitial(soup: BeautifulSoup) -> bool:
    # Señales típicas del intersticial de registro/login de ML
    if soup.select_one('a[href*="registration?confirmation_url="]'):
        return True
    texto = soup.get_text(" ", strip=True).lower()
    claves = ["soy nuevo", "ingresá", "ingresa", "iniciá sesión", "inicia sesión", "creá tu cuenta", "crea tu cuenta"]
    return any(k in texto for k in claves)

def _perform_search_api(query, limit=15, version_value=None):
    """Fallback estable a la API pública de ML (sin OAuth para búsquedas)."""
    try:
        r = requests.get(
            "https://api.mercadolibre.com/sites/MLA/search",
            params={"q": query, "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("[API FALLBACK] Error llamando a MLA/search:", e)
        return [], 0, 0

    resultados = []
    precios_convertidos = []

    for it in data.get("results", []):
        title = it.get("title")
        link = it.get("permalink")
        currency = it.get("currency_id", "ARS")
        price = it.get("price")

        attrs = {a.get("id"): a.get("value_name") for a in it.get("attributes", []) if isinstance(a, dict)}
        year = attrs.get("VEHICLE_YEAR") or attrs.get("YEAR")
        km = attrs.get("KILOMETERS") or attrs.get("KILOMETER")

        precio_ars_num = None
        precio_mostrado = "N/D"
        if price is not None:
            if currency == "USD":
                precio_ars_num = float(price) * USD_ARS
                precio_mostrado = f"US$ {price}"
            else:
                precio_ars_num = float(price)
                precio_mostrado = f"$ {int(price):,}".replace(",", ".")

        if precio_ars_num is not None:
            precios_convertidos.append(precio_ars_num)

        resultados.append({
            "titulo": title or "",
            "precio": precio_mostrado,
            "precio_ars_num": int(precio_ars_num) if precio_ars_num is not None else None,
            "link": link,
            "anio": year,
            "kilometraje": km,
            "version": version_value
        })

    promedio = sum(precios_convertidos) / len(precios_convertidos) if precios_convertidos else 0
    promedio_dolares = (promedio / USD_ARS) if promedio else 0
    return resultados, promedio, promedio_dolares

def _perform_search(query, version_value=None):
    """Scraping con tolerancia + detección de intersticial anti-bot."""
    search_term = query.replace(' ', '-')
    url = f'https://listado.mercadolibre.com.ar/{search_term}'

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",  # evitamos 'br' para respuestas más estables
        "Connection": "keep-alive",
        "Referer": "https://listado.mercadolibre.com.ar/"
    }

    resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
    print("Respuesta HTTP:", resp.status_code)
    if resp.status_code != 200:
        return [], 0, 0

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Si detecta intersticial, devolvemos vacío para forzar fallback API
    if _is_antibot_interstitial(soup):
        print("[ANTIBOT] Intersticial de registro detectado: activando fallback API")
        return [], 0, 0

    cards = soup.select(
        "div.andes-card, li.ui-search-layout__item, div.ui-search-result__wrapper, div.poly-card"
    )
    print("Cantidad de resultados encontrados:", len(cards))

    resultados = []
    precios_convertidos = []

    for idx, card in enumerate(cards[:15]):
        try:
            title, link = _extract_title_and_link(card)
            price_text = _extract_price_text(card)

            # Filtrar tarjetas basura/intersticial
            if link and "registration?" in link:
                print(f"[DESCARTADO {idx}] link a registration/intersticial")
                continue

            if not title and not price_text:
                print(f"[DESCARTADO {idx}] sin título ni precio")
                continue

            if title and not price_text:
                # Devolvemos igual (evita 404), sin precio
                year, mileage = _extract_year_km(card)
                resultados.append({
                    "titulo": title,
                    "precio": "N/D",
                    "precio_ars_num": None,
                    "link": link,
                    "anio": year,
                    "kilometraje": mileage,
                    "version": version_value
                })
                continue

            monto_ars, precio_str = _parse_price(price_text)
            if monto_ars is None:
                print(f"[DESCARTADO {idx}] no se pudo parsear precio: {price_text}")
                continue

            year, mileage = _extract_year_km(card)

            precios_convertidos.append(monto_ars)
            resultados.append({
                "titulo": title or "",
                "precio": precio_str,
                "precio_ars_num": int(monto_ars),
                "link": link,
                "anio": year,
                "kilometraje": mileage,
                "version": version_value
            })

        except Exception as e:
            print(f"[ERROR {idx}] procesando producto: {e}")

    promedio = sum(precios_convertidos) / len(precios_convertidos) if precios_convertidos else 0
    promedio_dolares = (promedio / USD_ARS) if promedio else 0
    return resultados, promedio, promedio_dolares

# -------------------- ENDPOINTS --------------------
@app.route("/_health")
def _health():
    return jsonify({"ok": True})

@app.route('/scrap', methods=['POST'])
def scrap():
    data = request.json
    if not data:
        return jsonify({"error": "Falta el body"}), 400

    marca = data.get('marca', '').strip()
    modelo = data.get('modelo', '').strip()
    version = data.get('version', '').strip()
    anio = data.get('anio', '').strip()
    kilometraje = data.get('kilometraje', '').strip()

    if kilometraje and not kilometraje.lower().endswith("km"):
        kilometraje = f"{kilometraje} km"

    query_parts = [marca, modelo, version, anio, kilometraje]
    search_query = ' '.join([part for part in query_parts if part])

    if not search_query:
        return jsonify({"error": "No se recibió ninguna palabra clave para la búsqueda"}), 400

    # 1) Intento scraping
    resultados, promedio, promedio_dolares = _perform_search(search_query, version_value=version)

    # 2) Fallback a API si scraping no devolvió
    if not resultados:
        resultados, promedio, promedio_dolares = _perform_search_api(search_query, limit=15, version_value=version)

    # 3) Fallback adicional sin versión
    if not resultados and version:
        search_query_without_version = ' '.join([part for part in [marca, modelo, anio, kilometraje] if part])
        if search_query_without_version:
            resultados, promedio, promedio_dolares = _perform_search(search_query_without_version, version_value=None)
            if not resultados:
                resultados, promedio, promedio_dolares = _perform_search_api(search_query_without_version, limit=15, version_value=None)

    if not resultados:
        return jsonify({"error": "No se encontraron resultados para la búsqueda"}), 404

    return jsonify({
        "query_usado": search_query,
        "resultados": resultados,
        # "promedio_estimado_ars": int(promedio) if promedio else 0,
        # "promedio_estimado_usd": round(promedio_dolares, 2) if promedio_dolares else 0.0
    })

@app.route('/scrap_url', methods=['POST'])
def scrap_url():
    data = request.json
    if not data:
        return jsonify({"error": "Falta el body"}), 400

    url = data.get('url', '').strip()
    if not url:
        return jsonify({"error": "No se recibió la URL"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Referer": "https://www.mercadolibre.com.ar/"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Respuesta HTTP: {response.status_code}")
        if response.status_code != 200:
            return jsonify({"error": "No se pudo acceder a la URL"}), 500

        soup = BeautifulSoup(response.text, 'html.parser')

        titulo = soup.find(class_='ui-pdp-title')
        descripcion = soup.find(class_='ui-pdp-subtitle')

        precio_node = soup.find(class_='andes-money-amount')
        if precio_node:
            precio_text = precio_node.get_text(" ", strip=True)
        else:
            symbol = soup.select_one(".andes-money-amount__currency-symbol, .price-tag-symbol")
            fraction = soup.select_one(".andes-money-amount__fraction, .price-tag-fraction")
            precio_text = f"{symbol.get_text(strip=True) if symbol else '$'} {fraction.get_text(strip=True)}" if fraction else None

        if not titulo or not descripcion or not precio_text:
            return jsonify({"error": "No se encontraron los elementos en la página"}), 404

        return jsonify({
            "titulo": titulo.get_text(strip=True),
            "descripcion": descripcion.get_text(strip=True),
            "precio": precio_text
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))  # Railway usa 8080
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
