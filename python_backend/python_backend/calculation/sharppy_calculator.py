"""Motor de cálculo termodinâmico do BSMS usando SHARPpy.

Recebe exclusivamente níveis observados. Não interpola nem inventa valores
meteorológicos; índices sem suporte suficiente retornam null/indisponível.
"""
import math

def _finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def _safe(value, digits=1):
    n = _finite(value)
    return round(n, digits) if n is not None else None

def calculate_indices(rows, payload=None):
    payload = payload or {}
    if not isinstance(rows, list) or len(rows) < 10:
        raise ValueError("A sondagem precisa conter pelo menos 10 níveis observados para análise termodinâmica.")

    import numpy as np
    from sharppy.sharptab import profile, params

    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        p, h, t, td = (_finite(row.get(k)) for k in ("pressure", "height", "temperature", "dewpoint"))
        if p is None or h is None or t is None or td is None:
            continue
        if not (100 <= p <= 1100 and -120 <= t <= 70 and -120 <= td <= 70 and -1000 <= h <= 50000):
            continue
        if td > t + 0.5:
            td = t
        direction = _finite(row.get("wind_direction"))
        speed_ms = _finite(row.get("wind_speed"))
        speed_kt = speed_ms / 0.514444 if speed_ms is not None and speed_ms >= 0 else -9999.
        cleaned.append((p, h, t, td,
            direction if direction is not None and 0 <= direction <= 360 else -9999.,
            speed_kt if speed_kt >= 0 else -9999.))

    cleaned.sort(key=lambda x: x[0], reverse=True)
    unique, seen = [], set()
    for row in cleaned:
        key = round(row[0], 2)
        if key not in seen:
            unique.append(row)
            seen.add(key)
    if len(unique) < 10:
        raise ValueError("Níveis insuficientes com pressão, temperatura, ponto de orvalho e altura observada. Nenhum valor foi inventado.")

    p = np.array([x[0] for x in unique], dtype=float)
    h = np.array([x[1] for x in unique], dtype=float)
    t = np.array([x[2] for x in unique], dtype=float)
    td = np.array([x[3] for x in unique], dtype=float)
    wd = np.array([x[4] for x in unique], dtype=float)
    ws = np.array([x[5] for x in unique], dtype=float)
    prof = profile.create_profile(profile="convective", pres=p, hght=h, tmpc=t, dwpc=td,
        wdir=wd, wspd=ws, missing=-9999., strictQC=False,
        location=str(payload.get("station_name", "BSMS")))

    output = []
    def add(label, value, unit="", digits=1):
        value = _safe(value, digits)
        output.append({"name": label, "value": value, "unit": unit, "available": value is not None})

    for name, flag in (("SBCAPE", 1), ("MLCAPE", 4), ("MUCAPE", 3)):
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

    return {"engine": "SHARPpy", "station": payload.get("station_name"),
        "observation_utc": payload.get("observation_utc"), "levels_used": len(unique),
        "indices": output,
        "note": "Índices calculados com os níveis observados recebidos. Índices sem dados suficientes aparecem indisponíveis."}
      
