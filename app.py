from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import os
import re

app = Flask(__name__)

# Endpoint para scrapear productos de MercadoLibre por búsqueda
@app.route('/scrap', methods=['POST'])
def scrap():
    data = request.json
    if not data:
        return jsonify({"error": "Falta el body"}), 400

    marca = data.get('marca', '').strip()
    modelo = data.get('modelo', '').strip()
    version = data.get('version', '').strip()  # Recibimos la versión
    anio = data.get('anio', '').strip()
    kilometraje = data.get('kilometraje', '').strip()  # Recibimos el kilometraje

    # Validación y ajuste del kilometraje
    if kilometraje and not kilometraje.lower().endswith("km"):
        # Si el kilometraje no contiene "km", lo añadimos
        kilometraje = f"{kilometraje} km"

    # Armar el query inicial con todos los valores
    query_parts = [marca, modelo, version, anio, kilometraje]  # Incluimos versión y kilometraje
    search_query = ' '.join([part for part in query_parts if part])

    if not search_query:
        return jsonify({"error": "No se recibió ninguna palabra clave para la búsqueda"}), 400

    # -------- perform_search NUEVO (más tolerante) --------
    def perform_search(query):
        search_term = query.replace(' ', '-')
        url = f'https://listado.mercadolibre.com.ar/{search_term}'

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Referer": "https://listado.mercadolibre.com.ar/"
        }

        resp = requests.get(url, headers=headers, timeout=15)
        print("Respuesta HTTP:", resp.status_code)
        if resp.status_code != 200:
            return [], 0, 0

        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        # Captura variantes de tarjetas (ML cambia clases seguido)
        cards = soup.select(
            "div.andes-card, li.ui-search-layout__item, div.ui-search-result__wrapper, div.poly-card"
        )
        print("Cantidad de resultados encontrados:", len(cards))

        resultados = []
        precios_convertidos = []

        def parse_price(node_text):
            """
            Acepta $ 1.234.567, U$S 10.500, US$ 10.500, limpia espacios no separables.
            Devuelve monto_en_ARS (float) o None, y el string original.
            """
            t = (node_text or "").replace("\xa0", " ").strip()

            # USD primero (US$ o U$S)
            m_usd = re.search(r'(?:US\$|U\$S)\s*([\d\.\,]+)', t)
            if m_usd:
                raw = m_usd.group(1)
                num = re.sub(r'[^\d]', '', raw)  # quita . , espacios
                if not num:
                    return None, t
                usd = float(num)
                ars = usd * 1210  # tipo de cambio usado en tu lógica
                return ars, t

            # ARS ($ …)
            m_ars = re.search(r'\$\s*([\d\.\,]+)', t)
            if m_ars:
                raw = m_ars.group(1)
                num = re.sub(r'[^\d]', '', raw)
                if not num:
                    return None, t
                ars = float(num)
                return ars, t

            return None, t

        def extract_title_and_link(card):
            # 1) tu selector original
            t = card.find(class_="poly-component__title")
            if t and t.get_text(strip=True):
                a = t.find('a')
                href = a['href'] if a and a.has_attr('href') else None
                return t.get_text(strip=True), href

            # 2) variantes comunes de listado
            a = card.select_one("a.ui-search-result__content-wrapper, a.ui-search-link")
            if a and a.get_text(strip=True):
                return a.get_text(strip=True), (a['href'] if a.has_attr('href') else None)

            # 3) fallback genérico
            a2 = card.find('a', href=True)
            if a2 and a2.get_text(strip=True):
                return a2.get_text(strip=True), a2['href']

            return None, None

        def extract_year_km(card):
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

        for idx, card in enumerate(cards[:15]):  # Limitar a los primeros 15 resultados
            try:
                title, link = extract_title_and_link(card)

                # Precio: buscar contenedor y luego texto, con fallback a fracciones separadas
                price_node = card.find(class_="andes-money-amount")
                price_text = price_node.get_text(" ", strip=True) if price_node else None
                if not price_text:
                    symbol = card.select_one(".andes-money-amount__currency-symbol")
                    fraction = card.select_one(".andes-money-amount__fraction")
                    if fraction:
                        price_text = f"{symbol.get_text(strip=True) if symbol else '$'} {fraction.get_text(strip=True)}"

                if not title or not price_text:
                    print(f"[DESCARTADO {idx}] sin título o precio. title={bool(title)} price_text={price_text}")
                    continue

                monto_ars, precio_str = parse_price(price_text)
                if monto_ars is None:
                    print(f"[DESCARTADO {idx}] no se pudo parsear precio: {price_text}")
                    continue

                year, mileage = extract_year_km(card)

                precios_convertidos.append(monto_ars)
                resultados.append({
                    "titulo": title,
                    "precio": precio_str,
                    "link": link,
                    "anio": year,
                    "kilometraje": mileage,
                    "version": version
                })

            except Exception as e:
                print(f"[ERROR {idx}] procesando producto: {e}")

        promedio = sum(precios_convertidos) / len(precios_convertidos) if precios_convertidos else 0
        promedio_dolares = (promedio / 1210) if promedio else 0  # conversión inversa correcta

        return resultados, promedio, promedio_dolares
    # -------- fin perform_search NUEVO --------

    # Realizamos la primera búsqueda con todos los campos
    resultados, promedio, promedio_dolares = perform_search(search_query)

    # Si no se encontraron resultados, realizamos la búsqueda sin la versión
    if not resultados:
        search_query_without_version = ' '.join([part for part in [marca, modelo, anio, kilometraje] if part])
        if search_query_without_version:
            resultados, promedio, promedio_dolares = perform_search(search_query_without_version)

    # Si aún no se encuentran resultados, devolver un mensaje de error
    if not resultados:
        return jsonify({"error": "No se encontraron resultados para la búsqueda"}), 404

    return jsonify({
        "query_usado": search_query,
        "resultados": resultados,
        # "promedio_estimado_ars": int(promedio) if promedio else 0,
        # "promedio_estimado_usd": round(promedio_dolares, 2) if promedio_dolares else 0.0
    })


# Nuevo endpoint para scrapear una URL específica de MercadoLibre
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
        "Connection": "keep-alive",
        "Referer": "https://www.mercadolibre.com.ar/"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Respuesta HTTP: {response.status_code}")  # Verifica el código de estado HTTP
        if response.status_code != 200:
            return jsonify({"error": "No se pudo acceder a la URL"}), 500

        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Extraer título, descripción y precio (con fallback a fracciones)
        titulo = soup.find(class_='ui-pdp-title')
        descripcion = soup.find(class_='ui-pdp-subtitle')

        precio_node = soup.find(class_='andes-money-amount')
        if precio_node:
            precio_text = precio_node.get_text(" ", strip=True)
        else:
            symbol = soup.select_one(".andes-money-amount__currency-symbol")
            fraction = soup.select_one(".andes-money-amount__fraction")
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
