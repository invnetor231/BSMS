"""Motor termodinâmico independente do SHARPpy para o BSMS.

Usa apenas níveis observados recebidos pela API. Não cria sondagens, não preenche
níveis ausentes e sinaliza como indisponíveis os índices que não puder calcular.
Métodos: Bolton para LCL; parcela pseudoadiabática aproximada por integração em
pressão para CAPE/CIN; definições padrão de K e Total Totals.
"""
import math

RD = 287.05
CP = 1004.0
EPS = 0.622
G = 9.80665
LV = 2.5e6


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _round(x, digits=1):
    return round(float(x), digits) if x is not None and math.isfinite(float(x)) else None


def saturation_vapor_pressure(tc):
    return 6.112 * math.exp(17.67 * tc / (tc + 243.5))


def mixing_ratio(p_hpa, td_c):
    e = saturation_vapor_pressure(td_c)
    return EPS * e / max(0.01, p_hpa - e)


def lcl_temperature_k(tk, tdk):
    # Bolton (1980), temperatura do LCL em kelvin.
    return 1.0 / (1.0 / (tdk - 56.0) + math.log(tk / tdk) / 800.0) + 56.0


def lcl_pressure(p_hpa, t_c, td_c):
    tk, tdk = t_c + 273.15, td_c + 273.15
    tlcl = lcl_temperature_k(tk, tdk)
    return p_hpa * (tlcl / tk) ** (CP / RD)


def theta_k(t_c, p_hpa):
    return (t_c + 273.15) * (1000.0 / p_hpa) ** (RD / CP)


def theta_e_k(t_c, td_c, p_hpa):
    tk, tdk = t_c + 273.15, td_c + 273.15
    tlcl = lcl_temperature_k(tk, tdk)
    r = mixing_ratio(p_hpa, td_c)
    return tk * (1000.0 / p_hpa) ** (0.2854 * (1.0 - 0.28 * r)) * math.exp((3376.0 / tlcl - 2.54) * r * (1.0 + 0.81 * r))


def moist_lapse_rate_k_per_pa(tk, p_pa):
    # dT/dp para uma parcela saturada, aproximação pseudoadiabática.
    tc = tk - 273.15
    es = saturation_vapor_pressure(tc) * 100.0
    p_pa = max(p_pa, es + 10.0)
    rs = EPS * es / (p_pa - es)
    numerator = RD * tk / p_pa * (1.0 + LV * rs / (RD * tk))
    denominator = CP + (LV * LV * rs * EPS) / (RD * tk * tk)
    return numerator / denominator


def parcel_temperature_at(p0, t0_c, td0_c, target_p):
    """Temperatura da parcela em target_p por elevação seca até LCL e úmida acima."""
    if target_p >= p0:
        return (t0_c + 273.15) * (target_p / p0) ** (RD / CP) - 273.15
    tlcl_p = lcl_pressure(p0, t0_c, td0_c)
    tk0 = t0_c + 273.15
    if target_p >= tlcl_p:
        return tk0 * (target_p / p0) ** (RD / CP) - 273.15
    tlcl_k = lcl_temperature_k(tk0, td0_c + 273.15)
    # Integra em passos de até 2 hPa a partir do LCL até à pressão de destino.
    p = tlcl_p * 100.0
    tk = tlcl_k
    end = target_p * 100.0
    n = max(1, int(math.ceil((p - end) / 200.0)))
    dp = (end - p) / n
    for _ in range(n):
        k1 = moist_lapse_rate_k_per_pa(tk, p)
        k2 = moist_lapse_rate_k_per_pa(tk + 0.5 * dp * k1, p + 0.5 * dp)
        k3 = moist_lapse_rate_k_per_pa(tk + 0.5 * dp * k2, p + 0.5 * dp)
        k4 = moist_lapse_rate_k_per_pa(tk + dp * k3, p + dp)
        tk += dp * (k1 + 2*k2 + 2*k3 + k4) / 6.0
        p += dp
    return tk - 273.15


def virtual_temperature(t_c, td_c, p_hpa):
    r = mixing_ratio(p_hpa, min(td_c, t_c))
    return (t_c + 273.15) * (1.0 + r / EPS) / (1.0 + r) - 273.15


def _interp_pressure(rows, target):
    # rows ordenadas por pressão decrescente; interpolação linear em log(p).
    for a, b in zip(rows, rows[1:]):
        if a["p"] >= target >= b["p"]:
            f = (math.log(target) - math.log(a["p"])) / (math.log(b["p"]) - math.log(a["p"]))
            return {k: a[k] + f * (b[k] - a[k]) for k in ("p", "h", "t", "td")}
    return None


def _parcel_indices(rows, start):
    p0, t0, td0 = start["p"], start["t"], start["td"]
    lclp = lcl_pressure(p0, t0, td0)
    path = []
    for row in rows:
        if row["p"] > p0:
            continue
        tp = parcel_temperature_at(p0, t0, td0, row["p"])
        env_tv = virtual_temperature(row["t"], row["td"], row["p"]) + 273.15
        parcel_td = td0 if row["p"] >= lclp else tp
        par_tv = virtual_temperature(tp, parcel_td, row["p"]) + 273.15
        path.append({**row, "tp": tp, "buoy": G * (par_tv - env_tv) / env_tv})
    if len(path) < 2:
        return None
    cape = cin = 0.0
    lfc = el = None
    positive_seen = False
    for a, b in zip(path, path[1:]):
        dz = b["h"] - a["h"]
        if dz <= 0 or dz > 5000:
            continue
        mean_b = (a["buoy"] + b["buoy"]) / 2.0
        if mean_b > 0:
            cape += mean_b * dz
            positive_seen = True
            if lfc is None:
                lfc = a["p"]
        elif not positive_seen:
            cin += mean_b * dz
        elif el is None:
            el = a["p"]
    if positive_seen and el is None:
        el = path[-1]["p"]
    li500 = None
    env500 = _interp_pressure(rows, 500.0)
    if env500:
        parcel500 = parcel_temperature_at(p0, t0, td0, 500.0)
        li500 = env500["t"] - parcel500
    return {"cape": max(0.0, cape), "cin": min(0.0, cin), "lclp": lclp, "lfcp": lfc, "elp": el, "li500": li500}


def calculate_indices(rows, payload=None):
    payload = payload or {}
    if not isinstance(rows, list) or len(rows) < 10:
        raise ValueError("A sondagem precisa conter pelo menos 10 níveis observados.")
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        p = _num(r.get("pressure", r.get("p")))
        h = _num(r.get("height", r.get("h")))
        t = _num(r.get("temperature", r.get("t")))
        td = _num(r.get("dewpoint", r.get("td")))
        if None in (p, h, t, td) or not (100 <= p <= 1100 and -100 <= t <= 60 and -120 <= td <= 60 and -500 <= h <= 50000):
            continue
        if td > t:
            td = t
        clean.append({"p": p, "h": h, "t": t, "td": td})
    clean.sort(key=lambda x: x["p"], reverse=True)
    unique, seen = [], set()
    for r in clean:
        key = round(r["p"], 2)
        if key not in seen:
            unique.append(r); seen.add(key)
    if len(unique) < 10:
        raise ValueError("Menos de 10 níveis observados válidos com pressão, altura, temperatura e ponto de orvalho. Nenhum valor foi inventado.")

    out = []
    def add(name, value, unit="", digits=1):
        value = _round(value, digits)
        out.append({"name": name, "value": value, "unit": unit, "available": value is not None})

    sfc = unique[0]
    # K e Total Totals precisam de dados nos níveis de 850, 700 e 500 hPa.
    r850, r700, r500 = (_interp_pressure(unique, p) for p in (850.0, 700.0, 500.0))
    if r850 and r700 and r500:
        k = (r850["t"] - r850["td"]) + r700["t"] - (r500["t"] - r500["td"])
        tt = (r850["t"] - r500["t"]) + (r850["td"] - r500["t"])
        add("Índice K", k, "°C")
        add("Total Totals (TT)", tt, "°C")
    else:
        add("Índice K", None, "°C")
        add("Total Totals (TT)", None, "°C")

    # SBCAPE: parcela da superfície observada.
    sb = _parcel_indices(unique, sfc)
    if sb:
        add("SBCAPE", sb["cape"], "J/kg", 0); add("SBCIN", sb["cin"], "J/kg", 0)
        add("LCL superfície", sb["lclp"], "hPa")
        add("LFC superfície", sb["lfcp"], "hPa")
        add("Nível de equilíbrio (EL)", sb["elp"], "hPa")
        add("Lifted Index 500 hPa (LI)", sb["li500"], "°C")
    else:
        for n, u in (("SBCAPE","J/kg"),("SBCIN","J/kg"),("LCL superfície","hPa"),("LFC superfície","hPa"),("Nível de equilíbrio (EL)","hPa"),("Lifted Index 500 hPa (LI)","°C")): add(n, None, u)

    # MLCAPE: média de theta e razão de mistura nos primeiros 100 hPa da sondagem.
    mix_levels = [r for r in unique if r["p"] >= sfc["p"] - 100.0]
    if len(mix_levels) >= 2:
        theta_mean = sum(theta_k(r["t"], r["p"]) for r in mix_levels) / len(mix_levels)
        w_mean = sum(mixing_ratio(r["p"], r["td"]) for r in mix_levels) / len(mix_levels)
        e = (w_mean * sfc["p"]) / (EPS + w_mean)
        td_mean = 243.5 * math.log(max(e, 0.01) / 6.112) / (17.67 - math.log(max(e, 0.01) / 6.112))
        t_mean = theta_mean / ((1000.0 / sfc["p"]) ** (RD / CP)) - 273.15
        ml = _parcel_indices(unique, {"p": sfc["p"], "t": t_mean, "td": td_mean, "h": sfc["h"]})
    else: ml = None
    add("MLCAPE", ml["cape"] if ml else None, "J/kg", 0); add("MLCIN", ml["cin"] if ml else None, "J/kg", 0)

    # MUCAPE: parcela com maior theta-e entre os níveis observados nos 300 hPa inferiores.
    candidates = [r for r in unique if r["p"] >= sfc["p"] - 300.0]
    if candidates:
        most_unstable = max(candidates, key=lambda r: theta_e_k(r["t"], r["td"], r["p"]))
        mu = _parcel_indices(unique, most_unstable)
    else: mu = None
    add("MUCAPE", mu["cape"] if mu else None, "J/kg", 0); add("MUCIN", mu["cin"] if mu else None, "J/kg", 0)

    # Água precipitável integrada por camadas usando razão de mistura observada.
    pw_mm = 0.0
    for a, b in zip(unique, unique[1:]):
        dp = (a["p"] - b["p"]) * 100.0
        if dp > 0:
            pw_mm += G ** -1 * (mixing_ratio(a["p"], a["td"]) + mixing_ratio(b["p"], b["td"])) * 0.5 * dp
    add("Água precipitável", pw_mm / 25.4, "in", 2)

    return {"engine": "BSMS-equações-termodinâmicas", "station": payload.get("station_name"),
        "observation_utc": payload.get("observation_utc"), "levels_used": len(unique), "indices": out,
        "note": "Cálculos próprios a partir de níveis observados. CAPE/CIN usam integração aproximada da parcela; valide para uso operacional. Índices sem suporte de dados aparecem indisponíveis."}
