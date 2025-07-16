from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import os

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

    # Armar el query inicial con todos los valores
    query_parts = [marca, modelo, version, anio, kilometraje]  # Incluimos version y kilometraje
    search_query = ' '.join([part for part in query_parts if part])
    
    if not search_query:
        return jsonify({"error": "No se recibió ninguna palabra clave para la búsqueda"}), 400

    # Función para realizar la búsqueda en Mercado Libre
    def perform_search(query):
        search_term = query.replace(' ', '-')
        url = f'https://listado.mercadolibre.com.ar/{search_term}'

        # Agregar encabezado User-Agent para simular una solicitud desde un navegador
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        response = requests.get(url, headers=headers)
        print(f"Respuesta HTTP: {response.status_code}")  # Imprime el código de estado HTTP
        if response.status_code != 200:
            return [], 0, 0  # Retorna resultados vacíos si hay un error en la respuesta

        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.find_all('div', class_='andes-card')

        print(f"Cantidad de resultados encontrados: {len(cards)}")  # Imprime la cantidad de productos encontrados

        resultados = []
        precios_convertidos = []

        for card in cards[:15]:  # Limitar a los primeros 15 resultados
            try:
                titulo = card.find(class_='poly-component__title')
                precio_tag = card.find(class_='andes-money-amount')
                link_tag = titulo.find('a') if titulo else None
                link = link_tag['href'] if link_tag and 'href' in link_tag.attrs else None

                # Obtener atributos adicionales desde la clase 'poly-attributes_list'
                attributes = card.find(class_='poly-attributes_list')
                attribute_list = attributes.find_all('li', class_='poly-attributes_list__item') if attributes else []

                # Inicializar variables para año y kilometraje
                year = None
                mileage = None

                for attribute in attribute_list:
                    text = attribute.text.strip()
                    if "km" in text.lower():
                        mileage = text  # Asignar el kilometraje
                    elif any(char.isdigit() for char in text) and len(text.split()) == 1:  # Suponiendo que el año es un número único
                        year = text  # Asignar el año

                if titulo and precio_tag:
                    precio_str = precio_tag.text.strip()
                    precio_num = None

                    # Detectar si el precio está en USD y convertirlo a ARS
                    if "US$" in precio_str:
                        precio_num = float(precio_str.replace("US$", "").replace(".", "").replace(",", "").strip()) * 1210
                    elif "$" in precio_str:
                        precio_num = float(precio_str.replace("$", "").replace(".", "").replace(",", "").strip())
                    else:
                        continue

                    precios_convertidos.append(precio_num)

                    resultados.append({
                        "titulo": titulo.text.strip(),
                        "precio": precio_str,
                        "link": link,
                        "anio": year,  # Añado el año
                        "kilometraje": mileage,  # Añado el kilometraje
                        "version": version  # Añado la versión
                    })
            except Exception as e:
                print(f"Error procesando un producto: {e}")

        promedio = sum(precios_convertidos) / len(precios_convertidos) if precios_convertidos else 0
        promedio_dolares = promedio / 1.20 if promedio else 0

        return resultados, promedio, promedio_dolares

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
        # "promedio_estimado": int(promedio),
        # "promedio_minimo": int(promedio_dolares)
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

    # Agregar encabezado User-Agent para simular una solicitud desde un navegador
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers)
        print(f"Respuesta HTTP: {response.status_code}")  # Verifica el código de estado HTTP
        if response.status_code != 200:
            return jsonify({"error": "No se pudo acceder a la URL"}), 500

        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Extraer título, descripción y precio usando las clases proporcionadas
        titulo = soup.find(class_='ui-pdp-title')
        descripcion = soup.find(class_='ui-pdp-subtitle')
        precio = soup.find(class_='andes-money-amount')

        # Verificar si se encontraron los elementos
        if not titulo or not descripcion or not precio:
            return jsonify({"error": "No se encontraron los elementos en la página"}), 404

        return jsonify({
            "titulo": titulo.text.strip(),
            "descripcion": descripcion.text.strip(),
            "precio": precio.text.strip()
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
