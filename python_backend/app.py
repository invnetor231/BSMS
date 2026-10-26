"""Backend termodinâmico do BSMS usando MetPy, sem dependência Git do SHARPpy."""
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
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def rounded(value, digits=1):
    try:
        number = float(value)
        return round(number, digits) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


@app.get("/")
def health():
    return jsonify({
        "service": "BSMS MetPy API",
        "status": "ok",
        "endpoint": "POST /indices",
        "engine": "MetPy"
    })


@app.post("/indices")
def indices():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("levels")
    if not isinstance(rows, list) or len(rows) < 10:
        return jsonify({"error": "A sondagem precisa conter pelo menos 10 níveis observados."}), 422

    try:
        import numpy as np
        import metpy.calc as mpcalc
        from metpy.units import units
    except Exception as exc:
        app.logger.exception("MetPy import failed")
        return jsonify({
            "error": "MetPy não está disponível no serviço.",
            "detail": str(exc)
        }), 503

    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pressure = finite(row.get("pressure"))
        temperature = finite(row.get("temperature"))
        dewpoint = finite(row.get("dewpoint"))
        if pressure is None or temperature is None or dewpoint is None:
            continue
        if not (100 <= pressure <= 1100 and -120 <= temperature <= 70 and -120 <= dewpoint <= 70):
            continue
        # Corrige apenas pequenas inconsistências físicas de Td > T no dado recebido.
        if dewpoint > temperature:
            if dewpoint - temperature <= 2:
                dewpoint = temperature
            else:
                continue
        cleaned.append((pressure, temperature, dewpoint))

    cleaned.sort(key=lambda item: item[0], reverse=True)
    unique = []
    seen = set()
    for row in cleaned:
        key = round(row[0], 2)
        if key not in seen:
            unique.append(row)
            seen.add(key)

    if len(unique) < 10:
        return jsonify({
            "error": "Níveis observados válidos insuficientes (mínimo 10). Nenhum perfil foi inventado."
        }), 422

    p = np.array([r[0] for r in unique], dtype=float) * units.hPa
    t = np.array([r[1] for r in unique], dtype=float) * units.degC
    td = np.array([r[2] for r in unique], dtype=float) * units.degC

    output = []

    def add(label, value, unit="", digits=1):
        val = rounded(value, digits)
        output.append({
            "name": label,
            "value": val,
            "unit": unit,
            "available": val is not None
        })

    def scalar(value):
        try:
            return float(np.asarray(value.magnitude).reshape(-1)[0])
        except Exception:
            try:
                return float(value)
            except Exception:
                return None

    # MetPy trabalha diretamente com pressão, temperatura e ponto de orvalho observados.
    try:
        parcel = mpcalc.parcel_profile(p, t[0], td[0])
        sbcape, sbcin = mpcalc.cape_cin(p, t, td, parcel)
        add("SBCAPE", scalar(sbcape), "J/kg", 0)
        add("SBCIN", scalar(sbcin), "J/kg", 0)
        lcl_p, lcl_t = mpcalc.lcl(p[0], t[0], td[0])
        add("LCL superfície", scalar(lcl_p.to("hPa")), "hPa", 1)

        # Lifted Index: temperatura ambiente menos temperatura da parcela a 500 hPa.
        p_hpa = p.to("hPa").magnitude
        env_c = t.to("degC").magnitude
        parcel_c = parcel.to("degC").magnitude
        if np.min(p_hpa) <= 500 <= np.max(p_hpa):
            env500 = float(np.interp(np.log(500.0), np.log(p_hpa[::-1]), env_c[::-1]))
            parcel500 = float(np.interp(np.log(500.0), np.log(p_hpa[::-1]), parcel_c[::-1]))
            add("Lifted Index 500 hPa (LI)", env500 - parcel500, "°C", 1)
        else:
            add("Lifted Index 500 hPa (LI)", None, "°C")
    except Exception:
        app.logger.exception("Surface parcel calculation failed")
        add("SBCAPE", None, "J/kg", 0)
        add("SBCIN", None, "J/kg", 0)
        add("LCL superfície", None, "hPa")
        add("Lifted Index 500 hPa (LI)", None, "°C")

    try:
        mlcape, mlcin = mpcalc.mixed_layer_cape_cin(p, t, td, depth=100 * units.hPa)
        add("MLCAPE", scalar(mlcape), "J/kg", 0)
        add("MLCIN", scalar(mlcin), "J/kg", 0)
    except Exception:
        add("MLCAPE", None, "J/kg", 0)
        add("MLCIN", None, "J/kg", 0)

    try:
        mucape, mucin = mpcalc.most_unstable_cape_cin(p, t, td, depth=300 * units.hPa)
        add("MUCAPE", scalar(mucape), "J/kg", 0)
        add("MUCIN", scalar(mucin), "J/kg", 0)
    except Exception:
        add("MUCAPE", None, "J/kg", 0)
        add("MUCIN", None, "J/kg", 0)

    try:
        add("Índice K", scalar(mpcalc.k_index(p, t, td).to("degC")), "°C", 1)
    except Exception:
        add("Índice K", None, "°C")

    try:
        add("Total Totals (TT)", scalar(mpcalc.total_totals_index(p, t, td).to("degC")), "°C", 1)
    except Exception:
        add("Total Totals (TT)", None, "°C")

    try:
        pw = mpcalc.precipitable_water(p, td)
        add("Água precipitável", scalar(pw.to("inch")), "in", 2)
    except Exception:
        add("Água precipitável", None, "in", 2)

    return jsonify({
        "engine": "MetPy",
        "station": payload.get("station_name"),
        "observation_utc": payload.get("observation_utc"),
        "levels_used": len(unique),
        "indices": output,
        "note": "Cálculos feitos com MetPy a partir dos níveis observados recebidos. Índices sem dados suficientes são marcados como indisponíveis; nenhum perfil foi inventado."
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
