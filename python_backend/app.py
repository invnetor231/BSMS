"""BSMS SHARPpy API. Recebe níveis observados; não gera perfis sintéticos."""
import math
import os
import warnings
from flask import Flask, request, jsonify
from flask_cors import CORS

warnings.filterwarnings("ignore")
app = Flask(__name__)
CORS(app, resources={r"/indices": {"origins": os.getenv("ALLOWED_ORIGIN", "*")}})


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
    return jsonify({"service": "BSMS Thermodynamic Calculator", "status": "ok", "endpoint": "POST /indices"})


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
