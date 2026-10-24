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
    return jsonify({"service": "BSMS SHARPpy", "status": "ok", "endpoint": "POST /indices"})


@app.post("/indices")
def indices():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("levels")
    if not isinstance(rows, list) or len(rows) < 10:
        return jsonify({"error": "A sondagem precisa conter pelo menos 10 níveis observados para análise termodinâmica."}), 422
    try:
        import numpy as np
        from sharppy.sharptab import profile, params, thermo
    except Exception as exc:
        app.logger.exception("SHARPpy import failed")
        return jsonify({"error": "SHARPpy não está disponível no serviço.", "detail": str(exc)}), 503

    # Requer altura geopotencial real da fonte. Não estimar silenciosamente alturas ausentes.
    cleaned = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        p, h, t, td = (finite(r.get(k)) for k in ("pressure", "height", "temperature", "dewpoint"))
        if p is None or h is None or t is None or td is None:
            continue
        if not (100 <= p <= 1100 and -120 <= t <= 70 and -120 <= td <= 70 and -1000 <= h <= 50000):
            continue
        if td > t + 0.5:
            td = t
        direction = finite(r.get("wind_direction"))
        speed_ms = finite(r.get("wind_speed"))
        # API sounding.js fornece velocidade em m/s; SHARPpy espera nós.
        speed_kt = speed_ms / 0.514444 if speed_ms is not None and speed_ms >= 0 else -9999.
        cleaned.append((p, h, t, td, direction if direction is not None and 0 <= direction <= 360 else -9999., speed_kt if speed_kt >= 0 else -9999.))

    # Remove duplicatas de pressão e ordena da superfície para o topo.
    cleaned.sort(key=lambda x: x[0], reverse=True)
    unique = []
    seen = set()
    for row in cleaned:
        key = round(row[0], 2)
        if key not in seen:
            unique.append(row); seen.add(key)
    if len(unique) < 10:
        return jsonify({"error": "Níveis insuficientes com pressão, temperatura, ponto de orvalho e altura observada. Nenhum valor foi inventado."}), 422

    p = np.array([x[0] for x in unique], dtype=float)
    h = np.array([x[1] for x in unique], dtype=float)
    t = np.array([x[2] for x in unique], dtype=float)
    td = np.array([x[3] for x in unique], dtype=float)
    wd = np.array([x[4] for x in unique], dtype=float)
    ws = np.array([x[5] for x in unique], dtype=float)
    try:
        prof = profile.create_profile(profile="convective", pres=p, hght=h, tmpc=t, dwpc=td,
                                      wdir=wd, wspd=ws, missing=-9999., strictQC=False,
                                      location=str(payload.get("station_name", "BSMS")))
        out = []
        def add(label, value, unit="", digits=1):
            v = safe(value, digits)
            out.append({"name": label, "value": v, "unit": unit, "available": v is not None})
        # Parcelas padrão SHARPpy: superfície, camada mista de 100 hPa e mais instável nos 300 hPa inferiores.
        parcel_specs = [("SBCAPE", 1), ("MLCAPE", 4), ("MUCAPE", 3)]
        for name, flag in parcel_specs:
            try:
                parcel = params.DefineParcel(prof, flag=flag, **({"pres": 300} if flag == 3 else {}))
                lifted = params.cape(prof, lplvals=parcel)
                add(name, lifted.bplus, "J/kg", 0)
                add(name.replace("CAPE", "CIN"), lifted.bminus, "J/kg", 0)
                if name == "SBCAPE":
                    add("LCL superfície", lifted.lclpres, "hPa", 1)
                    add("LFC superfície", lifted.lfcpres, "hPa", 1)
                    add("Nível de equilíbrio (EL)", lifted.elpres, "hPa", 1)
                    add("Lifted Index 500 hPa (LI)", lifted.li5, "°C", 1)
            except Exception:
                add(name, None, "J/kg")
                add(name.replace("CAPE", "CIN"), None, "J/kg")
        try: add("Índice K", params.k_index(prof), "°C")
        except Exception: add("Índice K", None, "°C")
        try: add("Total Totals (TT)", params.t_totals(prof), "°C")
        except Exception: add("Total Totals (TT)", None, "°C")
        try: add("Água precipitável", params.precip_water(prof), "in", 2)
        except Exception: add("Água precipitável", None, "in", 2)
        return jsonify({"engine": "SHARPpy", "station": payload.get("station_name"),
                        "observation_utc": payload.get("observation_utc"),
                        "levels_used": len(unique), "indices": out,
                        "note": "Índices calculados com os níveis observados recebidos. Índices sem dados suficientes aparecem indisponíveis."})
    except Exception as exc:
        app.logger.exception("Thermodynamic calculation failed")
        return jsonify({"error": "Não foi possível calcular os índices desta sondagem.", "detail": str(exc)}), 422

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
