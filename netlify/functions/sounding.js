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
  "83780": "São Paulo / Congonhas",
  "83840": "Curitiba",
  "83899": "Florianópolis",
  "83937": "Santa Maria",
  "83971": "Porto Alegre"
};

const UWYO_URL = "https://weather.uwyo.edu/wsgi/sounding";

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    },
    body: JSON.stringify(body)
  };
}

function num(value) {
  if (
    value == null ||
    ["", "-", "/////", "99999", "9999"].includes(String(value).trim())
  ) {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function stripHtml(html) {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<\/(?:pre|tr|p|div|br|table|h[1-6])\s*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'");
}

exports.handler = async (event) => {
  if (event.httpMethod !== "GET") {
    return json(405, {
      error: "Método não permitido. Use GET."
    });
  }

  const query = event.queryStringParameters || {};

  const station = String(query.station || "");
  const dateUtc = String(query.date || "");
  const hour = String(query.hour || "");

  if (!Object.prototype.hasOwnProperty.call(STATIONS, station)) {
    return json(400, {
      error: "Estação WMO não reconhecida."
    });
  }

  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(dateUtc) ||
    Number.isNaN(Date.parse(`${dateUtc}T00:00:00Z`)) ||
    new Date(`${dateUtc}T00:00:00Z`)
      .toISOString()
      .slice(0, 10) !== dateUtc
  ) {
    return json(400, {
      error: "Data inválida. Use AAAA-MM-DD."
    });
  }

  if (hour !== "00" && hour !== "12") {
    return json(400, {
      error: "A hora deve ser 00 ou 12 UTC."
    });
  }

  const chosenDate = new Date(`${dateUtc}T00:00:00Z`);
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);

  if (chosenDate > today) {
    return json(400, {
      error: "A data selecionada está no futuro."
    });
  }

  const url = new URL(UWYO_URL);

  url.searchParams.set("datetime", `${dateUtc} ${hour}:00:00`);
  url.searchParams.set("id", station);
  url.searchParams.set("type", "TEXT:LIST");

  let response;

  try {
    response = await fetch(url, {
      headers: {
        "user-agent": "BSMS-Radiossondagens/1.0",
        "accept": "text/html,text/plain,*/*"
      },
      signal: AbortSignal.timeout(25000)
    });
  } catch (error) {
    return json(502, {
      error: "Falha ao conectar à fonte de radiossondagens. Tente novamente mais tarde."
    });
  }

  if (!response.ok) {
    return json(502, {
      error: `A fonte de radiossondagens respondeu HTTP ${response.status}.`
    });
  }

  const html = await response.text();
  const body = stripHtml(html);

  if (
    /no data available|no data found|no sounding|not found|no observations/i.test(body)
  ) {
    return json(404, {
      error: "Não há radiossondagem disponível para esta estação, data e hora."
    });
  }

  const levels = [];
  const seenPressures = new Set();

  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim();

    if (!/^\d{2,4}(?:\.\d+)?\s/.test(line)) {
      continue;
    }

    const fields = line.split(/\s+/);

    if (fields.length < 4) {
      continue;
    }

    const pressure = num(fields[0]);
    const height = num(fields[1]);
    const temperature = num(fields[2]);
    const dewpoint = num(fields[3]);

    // Só aceitar níveis com os quatro parâmetros necessários.
    if (
      pressure == null ||
      height == null ||
      temperature == null ||
      dewpoint == null
    ) {
      continue;
    }

    if (
      pressure < 100 ||
      pressure > 1100 ||
      height < -500 ||
      height > 60000 ||
      temperature < -120 ||
      temperature > 70 ||
      dewpoint < -120 ||
      dewpoint > 70
    ) {
      continue;
    }

    // Evitar duplicatas de pressão.
    const pressureKey = pressure.toFixed(1);

    if (seenPressures.has(pressureKey)) {
      continue;
    }

    seenPressures.add(pressureKey);

    const level = {
      pressure,
      height,
      temperature,
      dewpoint
    };

    const direction = num(fields[6]);
    const windKnots = num(fields[7]);

    if (
      direction != null &&
      direction >= 0 &&
      direction <= 360
    ) {
      level.wind_direction = direction;
    }

    if (
      windKnots != null &&
      windKnots >= 0 &&
      windKnots <= 250
    ) {
      // Converter nós para metros por segundo.
      level.wind_speed = windKnots * 0.514444;
    }

    levels.push(level);
  }

  // Ordenar da maior para a menor pressão.
  levels.sort((a, b) => b.pressure - a.pressure);

  if (levels.length < 10) {
    return json(422, {
      error: `A fonte retornou apenas ${levels.length} níveis observados válidos; são necessários pelo menos 10.`,
      station,
      station_name: STATIONS[station],
      observation_utc: `${dateUtc} ${hour}Z`,
      levels_received: levels.length,
      source: "University of Wyoming Atmospheric Science Radiosonde Archive (TEXT:LIST)"
    });
  }

  return json(200, {
    station,
    station_name: STATIONS[station],
    observation_utc: `${dateUtc} ${hour}Z`,
    source: "University of Wyoming Atmospheric Science Radiosonde Archive (TEXT:LIST)",
    source_url: "https://weather.arcc.uwyo.edu/upperair/sounding.shtml",
    levels
  });
};
