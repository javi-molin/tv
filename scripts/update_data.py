
import json
import os
import re
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from html.parser import HTMLParser

OUTPUT = "data/tv-data.json"
TIMEZONE = ZoneInfo("America/Santiago")

CHANNELS = [
    {
        "channel": "Mega",
        "url": "https://www.mega.cl/programacion/",
    },
    {
        "channel": "Chilevisión",
        "url": "https://www.chilevision.cl/page/programacion/",
    },
    {
        "channel": "Canal 13",
        "url": "https://www.13.cl/programacion",
    },
    {
        "channel": "TVN",
        "url": "https://www.tvn.cl/",
    },
]


def clean(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


class JsonLdParser(HTMLParser):
    """Recopila bloques JSON-LD publicados en el HTML de cada fuente."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_jsonld = False
        self.current = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "script" and "ld+json" in attrs.get("type", "").lower():
            self.in_jsonld = True
            self.current = []

    def handle_data(self, data):
        if self.in_jsonld:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.in_jsonld:
            raw = "".join(self.current).strip()
            if raw:
                try:
                    self.blocks.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
            self.in_jsonld = False
            self.current = []


def fetch_jsonld(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; TVChilenaScheduleBot/1.0)"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-CL,es;q=0.9",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        html = response.read().decode(
            response.headers.get_content_charset() or "utf-8",
            errors="replace",
        )

    parser = JsonLdParser()
    parser.feed(html)
    return parser.blocks


def walk_json(value):
    """Recorre objetos y listas dentro de JSON-LD."""

    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def parse_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)
        return parsed.astimezone(TIMEZONE)
    except ValueError:
        return None


def extract_schedule(channel, source_url, blocks):
    found = {}

    for block in blocks:
        for item in walk_json(block):
            title = clean(
                item.get("name")
                or item.get("headline")
                or item.get("title")
            )

            # No se aceptan objetos sin nombre ni hora de inicio verificable.
            start_value = (
                item.get("startDate")
                or item.get("startTime")
                or item.get("start_time")
                or item.get("startDateTime")
            )
            start = parse_datetime(start_value)

            if not title or not start:
                continue

            # Una fecha sin hora no sirve para construir una parrilla horaria.
            if isinstance(start_value, str) and "T" not in start_value:
                continue

            # Evita elementos que parecen metadatos genéricos y no programas.
            if len(title) > 180:
                continue

            url = item.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                url = source_url

            entry = {
                "channel": channel,
                "title": title,
                "date": start.date().isoformat(),
                "time": start.strftime("%H:%M"),
                "source_url": url,
            }

            key = (entry["date"], entry["time"], entry["title"].casefold())
            found[key] = entry

    return list(found.values())


def main():
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    schedule_items = []
    channel_status = []

    for channel_info in CHANNELS:
        channel = channel_info["channel"]
        url = channel_info["url"]

        try:
            blocks = fetch_jsonld(url)
            entries = extract_schedule(channel, url, blocks)
            schedule_items.extend(entries)

            channel_status.append({
                "channel": channel,
                "status": "ok" if entries else "no_schedule_found",
                "source_url": url,
                "count": len(entries),
                "message": (
                    "Se identificaron horarios."
                    if entries
                    else "La página no entregó horarios estructurados reconocibles."
                ),
            })

            print(f"{channel}: {len(entries)} horarios detectados")

        except Exception as exc:
            channel_status.append({
                "channel": channel,
                "status": "error",
                "source_url": url,
                "count": 0,
                "message": str(exc)[:250],
            })
            print(f"Error consultando {channel}: {exc}")

    # Elimina duplicados sin inventar ni completar horarios.
    unique = {}
    for item in schedule_items:
        key = (
            item["channel"],
            item["date"],
            item["time"],
            item["title"].casefold(),
        )
        unique[key] = item

    schedule_items = sorted(
        unique.values(),
        key=lambda item: (item["date"], item["time"], item["channel"]),
    )

    data = {
        "updated_at": now,
        "timezone": "America/Santiago",
        "status": (
            "ok"
            if channel_status and all(
                entry["status"] == "ok" for entry in channel_status
            )
            else "partial"
        ),
        "schedule_status": (
            "available" if schedule_items else "not_found"
        ),
        "schedule_note": (
            "Horarios identificados en datos estructurados de fuentes oficiales. "
            "Confirma cambios en la web del canal."
            if schedule_items
            else
            "No se identificaron horarios estructurados. "
            "No se han inventado horarios."
        ),
        "schedule_items": schedule_items,
        "channel_status": channel_status,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(
        f"Actualización terminada: {len(schedule_items)} horarios; "
        f"archivo generado en {OUTPUT}"
    )


if __name__ == "__main__":
    main()
