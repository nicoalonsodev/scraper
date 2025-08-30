from flask import Flask, request, jsonify
import os
import re
import requests
from bs4 import BeautifulSoup
# from flask_cors import CORS  # <- descomenta si vas a llamar desde un front en otro dominio

app = Flask(__name__)
# CORS(app, resources={r"/*": {"origins": "*"}})  # opcional

# Podés ajustar el TC por variable de entorno: ML_USD_ARS=1210
USD_ARS = float(os.environ.get("ML_USD_ARS", 1210))

@app.route("/_health")
def _health():
    return jsonify({"ok": True})

# ---------- Helpers compartidos ----------
def _parse_price(texto: str):
    """Acepta: $ 1.234.567  |  US$ 10.500  |  U$S 10.500
    Devuelve (monto_ARS_float, string_normalizado) o (None, original)"""
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
    aria = card.select('[aria-label]')
    for el in aria:
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

def _perform_search(query, version_value=None):
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

    resp = requests.get(url, headers=headers, timeout=15)
    print("Respuesta HTTP:", resp.status_code)
    if resp.status_code != 200:
        return [], 0, 0

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Variantes de cards en ML
    cards = soup.select(
        "div.andes-card, li.ui-search-layout__item, div.ui-search-result__wrapper, div.poly-card"
    )
    print("Cantidad de resultados encontrados:", len(cards))

    resultados = []
    precios_convertidos = []

    for idx, card in enumerate(cards[:15]):  # hasta 15 resultados
        try:
            title, link = _extract_title_and_link(card)
            price_text = _extract_price_text(card)

            if not title and not price_text:
                print(f"[DESCARTADO {idx}] sin título ni precio en ninguna variante")
                continue

            # Si hay título pero no precio, devolvemos igual para evitar 404
            if title and not price_text:
                print(f"[SIN PRECIO {idx}] devuelvo sin precio")
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

# ---------- Endpoints ----------
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

    # Búsqueda 1: todo junto
    resultados, promedio, promedio_dolares = _perform_search(search_query, version_value=version)

    # Fallback: sin versión si no hubo resultados
    if not resultados:
        search_query_without_version = ' '.join([part for part in [marca, modelo, anio, kilometraje] if part])
        if search_query_without_version:
            resultados, promedio, promedio_dolares = _perform_search(search_query_without_version, version_value=None)

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

        # Precio con fallbacks
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
