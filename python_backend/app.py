"""API meteorológica do BSMS: índices termodinâmicos e proxy de CAPE."""
import math
import os
import warnings
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

warnings.filterwarnings("ignore")
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.getenv("ALLOWED_ORIGIN", "*")}})

def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def safe(value, digits=1):
    n = finite(value)
    return round(n, digits) if n is not None else None

@app.get("/")
def health():
    return jsonify({
        "service": "BSMS Meteorological Backend",
        "status": "ok",
        "endpoints": ["POST /indices", "POST /cape"]
    })

@app.post("/cape")
def cape():
    payload = request.get_json(silent=True) or {}
    latitudes = payload.get("latitude")
    longitudes = payload.get("longitude")
    if not isinstance(latitudes, list) or not isinstance(longitudes, list):
        return jsonify({"error": "Informe listas latitude e longitude."}), 400
    if not latitudes or len(latitudes) != len(longitudes) or len(latitudes) > 100:
        return jsonify({"error": "A grade deve conter de 1 a 100 pares de coordenadas."}), 400
    lats, lons = [], []
    for lat, lon in zip(latitudes, longitudes):
        a, b = finite(lat), finite(lon)
        if a is None or b is None or not -90 <= a <= 90 or not -180 <= b <= 180:
            return jsonify({"error": "A grade contém coordenadas inválidas."}), 400
        lats.append(a)
        lons.append(b)
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": ",".join(map(str, lats)),
                "longitude": ",".join(map(str, lons)),
                "hourly": "cape",
                "forecast_days": 2,
                "timezone": "UTC",
                "models": "best_match",
            },
            headers={"Accept": "application/json", "User-Agent": "BSMS-Meteorological-Monitor/1.0"},
            timeout=(8, 35),
        )
        if response.status_code != 200:
            return jsonify({
                "error": "Open-Meteo respondeu HTTP " + str(response.status_code),
                "detail": response.text[:500]
            }), 502
        if not response.content:
            return jsonify({"error": "Open-Meteo retornou corpo vazio ao backend do BSMS."}), 502
        data = response.json()
        locations = data if isinstance(data, list) else [data]
        valid = [
            item for item in locations
            if isinstance(item, dict)
            and isinstance(item.get("hourly"), dict)
            and isinstance(item["hourly"].get("time"), list)
            and isinstance(item["hourly"].get("cape"), list)
        ]
        if not valid:
            return jsonify({"error": "Open-Meteo não forneceu séries horárias válidas de CAPE."}), 502
        return jsonify({"source": "Open-Meteo", "product": "CAPE forecast", "locations": valid})
    except requests.Timeout:
        return jsonify({"error": "Tempo limite excedido ao consultar Open-Meteo."}), 504
    except requests.RequestException as exc:
        app.logger.exception("Open-Meteo request failed")
        return jsonify({"error": "Falha de conexão entre o backend BSMS e Open-Meteo.", "detail": str(exc)}), 502
    except ValueError:
        return jsonify({"error": "Open-Meteo devolveu conteúdo que não é JSON válido."}), 502

@app.post("/indices")
def indices():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("levels")
    if not isinstance(rows, list) or len(rows) < 10:
        return jsonify({"error": "A sondagem precisa conter pelo menos 10 níveis observados para análise termodinâmica."}), 422
    try:
        from calculation.sharppy_calculator import calculate_indices
        result = calculate_indices(rows, payload)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    except ImportError as exc:
        app.logger.exception("Calculation dependency import failed")
        return jsonify({"error": "Dependência do motor de cálculo indisponível.", "detail": str(exc)}), 503
    except Exception as exc:
        app.logger.exception("Thermodynamic calculation failed")
        return jsonify({"error": "Não foi possível calcular os índices desta sondagem.", "detail": str(exc)}), 422

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
