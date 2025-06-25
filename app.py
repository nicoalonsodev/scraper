from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

@app.route('/scrap', methods=['POST'])
def scrap():
    query = request.json.get('query')
    if not query:
        return jsonify({"error": "Falta el parámetro 'query' en el body"}), 400

    # Convertir a slug con guiones
    search_term = query.strip().replace(' ', '-')
    url = f'https://listado.mercadolibre.com.ar/{search_term}'

    try:
        html = requests.get(url).text
        soup = BeautifulSoup(html, 'html.parser')

        cards = soup.find_all('div', class_='andes-card')

        resultados = []
        for card in cards:
            titulo = card.find(class_='poly-component__title')
            precio = card.find(class_='andes-money-amount')
            link_tag = titulo.find('a') if titulo else None
            link = link_tag['href'] if link_tag else None

            if titulo and precio:
                resultados.append({
                    "titulo": titulo.text.strip(),
                    "precio": precio.text.strip(),
                    "link": link
                })

        return jsonify({"resultados": resultados})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
