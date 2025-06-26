from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

@app.route('/scrap', methods=['POST'])
def scrap():
    query = request.json.get('query')
    if not query:
        return jsonify({"error": "Falta el parámetro 'query' en el body"}), 400

    search_term = query.strip().replace(' ', '-')
    url = f'https://listado.mercadolibre.com.ar/{search_term}'

    try:
        html = requests.get(url).text
        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.find_all('div', class_='andes-card')

        resultados = []
        precios_convertidos = []

        for card in cards:
            if len(resultados) >= 5:
                break  # solo procesar los primeros 5 resultados válidos

            titulo = card.find(class_='poly-component__title')
            precio_tag = card.find(class_='andes-money-amount')
            link_tag = titulo.find('a') if titulo else None
            link = link_tag['href'] if link_tag else None

            if titulo and precio_tag:
                precio_str = precio_tag.text.strip()
                precio_num = None

                if "US$" in precio_str:
                    precio_num = float(precio_str.replace("US$", "").replace(".", "").replace(",", "").strip()) * 1200
                elif "$" in precio_str:
                    precio_num = float(precio_str.replace("$", "").replace(".", "").replace(",", "").strip())
                else:
                    continue

                precios_convertidos.append(precio_num)

                resultados.append({
                    "titulo": titulo.text.strip(),
                    "precio": precio_str,
                    "link": link
                })

        promedio = sum(precios_convertidos) / len(precios_convertidos) if precios_convertidos else 0
        promedio_dolares = promedio / 1.20 if promedio else 0

        return jsonify({
            "resultados": resultados,
            "promedio_estimado": int(promedio),
            "promedio_minimo": int(promedio_dolares)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
