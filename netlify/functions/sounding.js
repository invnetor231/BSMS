
const STATIONS = {
  "82022": "Boa Vista",
  "82099": "Macapá",
  "82193": "Belém",
  "82281": "São Luís",
  "82332": "Manaus",
  "82397": "Fortaleza",
  "82599": "Natal",
  "82824": "Porto Velho",
  "82900": "Recife",
  "82917": "Rio Branco",
  "82965": "Alta Floresta",
  "82983": "Petrolina",
  "83208": "Vilhena",
  "83229": "Salvador",
  "83362": "Cuiabá",
  "83378": "Brasília",
  "83498": "Caravelas",
  "83566": "Confins / Belo Horizonte",
  "83612": "Campo Grande",
  "83649": "Vitória",
  "83746": "Rio de Janeiro / Galeão",
  "83779": "São Paulo / Marte",
  "83780": "São Paulo / Congonhas",
  "83840": "Curitiba",
  "83899": "Florianópolis",
  "83937": "Santa Maria",
  "83971": "Porto Alegre"
};

const UWYO_URL = "https://weather.uwyo.edu/wsgi/sounding";

function jsonResponse(statusCode, body) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    },
    body: JSON.stringify(body)
  };
}

function decodeHtml(text) {
  return text
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#(\d+);/g, (_, n) =>
      String.fromCodePoint(Number(n))
    )
    .replace(/&#x([0-9a-f]+);/gi, (_, n) =>
      String.fromCodePoint(parseInt(n, 16))
    );
}

function parseSounding(text) {
  const rows = [];

  for (const line of text.replace(/\r/g, "").split("\n")) {
    const trimmed = line.trim();

    if (
      !trimmed ||
      /^(PRES|PRESSURE|hPa|-----|Station|Observation|Showalter|LIFT|CAPE|CIN)/i.test(trimmed)
    ) {
      continue;
    }

    const fields = trimmed.split(/\s+/);
    if (fields.length < 4) continue;

    const pressure = Number(fields[0]);
    const temperature = Number(fields[2]);
    const dewpoint = Number(fields[3]);

    if (
      !Number.isFinite(pressure) ||
      pressure <= 0 ||
      !Number.isFinite(temperature) ||
      temperature < -150 ||
      temperature > 80
    ) {
      continue;
    }

    const direction = Number(fields[6]);
    const knots = Number(fields[7]);

    rows.push({
      pressure,
      temperature,
      dewpoint:
        Number.isFinite(dewpoint) &&
        dewpoint >= -150 &&
        dewpoint <= temperature
          ? dewpoint
          : null,
      wind_direction:
        Number.isFinite(direction) ? direction : null,
      wind_speed:
        Number.isFinite(knots) && knots >= 0
          ? knots * 0.514444
          : null
    });
  }

  const unique = new Map();

  for (const row of rows) {
    if (!unique.has(row.pressure)) {
      unique.set(row.pressure, row);
    }
  }

  return [...unique.values()].sort(
    (a, b) => b.pressure - a.pressure
  );
}

exports.handler = async function (event) {
  if (event.httpMethod !== "GET") {
    return jsonResponse(405, {
      error: "Use uma requisição GET."
    });
  }

  const params = event.queryStringParameters || {};
  const station = String(params.station || "");
  const date = String(params.date || "");
  const hour = String(params.hour || "");

  if (!Object.prototype.hasOwnProperty.call(STATIONS, station)) {
    return jsonResponse(400, {
      error: "Estação inválida ou não cadastrada."
    });
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return jsonResponse(400, {
      error: "Data inválida. Use AAAA-MM-DD."
    });
  }

  if (!["00", "12"].includes(hour)) {
    return jsonResponse(400, {
      error: "Horário inválido. Use 00 ou 12 UTC."
    });
  }

  const requested = new Date(`${date}T${hour}:00:00Z`);

  if (
    Number.isNaN(requested.getTime()) ||
    requested.toISOString().slice(0, 10) !== date
  ) {
    return jsonResponse(400, {
      error: "Data inexistente."
    });
  }

  if (requested.getTime() > Date.now()) {
    return jsonResponse(400, {
      error: "O horário selecionado ainda está no futuro (UTC)."
    });
  }

  const url = new URL(UWYO_URL);
  url.searchParams.set("datetime", `${date} ${hour}:00:00`);
  url.searchParams.set("id", station);
  url.searchParams.set("src", "UNKNOWN");
  url.searchParams.set("type", "TEXT:LIST");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);

  try {
    const response = await fetch(url.toString(), {
      headers: {
        "User-Agent": "BSMS-Monitoramento-Meteorologico/1.0",
        "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8"
      },
      signal: controller.signal
    });

    const page = await response.text();

    if (!response.ok) {
      return jsonResponse(502, {
        error: `A fonte de radiossondagens respondeu HTTP ${response.status}.`,
        source_status: response.status,
        station: STATIONS[station],
        station_id: station,
        date,
        hour
      });
    }

    const match = page.match(/<pre[^>]*>([\s\S]*?)<\/pre>/i);
    const rawText = decodeHtml(match ? match[1] : page);

    const levels = parseSounding(rawText);

    if (levels.length < 2) {
      return jsonResponse(404, {
        error:
          "A fonte respondeu, mas não foram encontrados níveis válidos. A sondagem pode não estar disponível para esta estação, data e horário.",
        station: STATIONS[station],
        station_id: station,
        date,
        hour,
        levels: []
      });
    }

    return jsonResponse(200, {
      source: "University of Wyoming",
      station: STATIONS[station],
      station_id: station,
      observation_utc: `${date} ${hour}Z`,
      count: levels.length,
      levels
    });
  } catch (error) {
    return jsonResponse(502, {
      error:
        error && error.name === "AbortError"
          ? "A fonte de radiossondagens demorou demais para responder. Tente novamente."
          : "Não foi possível consultar a fonte de radiossondagens.",
      detail: error?.message || String(error)
    });
  } finally {
    clearTimeout(timeout);
  }
};
  
