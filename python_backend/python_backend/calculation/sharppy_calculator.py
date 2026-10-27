
"""API termodinâmica do BSMS, sem dependência do SHARPpy."""

import math
import os
import warnings

from flask import Flask, request, jsonify
from flask_cors import CORS

warnings.filterwarnings("ignore")

app = Flask(__name__)

CORS(
    app,
    resources={
        r"/indices": {
            "origins": os.getenv("ALLOWED_ORIGIN", "*")
        }
    },
)


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def safe(value, digits=1):
    number = finite(value)
    return round(number, digits) if number is not None else None


@app.get("/")
def health():
    return jsonify({
        "service": "BSMS Thermodynamic Calculator",
        "status": "ok",
        "endpoint": "POST /indices",
    })


@app.post("/indices")
def indices():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("levels")

    if not isinstance(rows, list) or len(rows) < 10:
        return jsonify({
            "error": (
                "A sondagem precisa conter pelo menos "
                "10 níveis observados para análise termodinâmica."
            )
        }), 422

    try:
        # Importação do motor próprio, sem SHARPpy.
        from calculation.sharppy_calculator import calculate_indices

        result = calculate_indices(rows, payload)
        return jsonify(result), 200

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    except ImportError as exc:
        app.logger.exception("Falha ao importar o motor termodinâmico")
        return jsonify({
            "error": "Não foi possível importar o motor de cálculo.",
            "detail": str(exc),
        }), 503

    except Exception as exc:
        app.logger.exception("Falha no cálculo termodinâmico")
        return jsonify({
            "error": "Não foi possível calcular os índices desta sondagem.",
            "detail": str(exc),
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
    
