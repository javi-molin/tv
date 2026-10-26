
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Recolector de programación para TV Chile.

Lee páginas oficiales usando únicamente la biblioteca estándar de Python.
Guarda el resultado en data/tv-data.json.

Nota: si una web carga su programación mediante JavaScript o bloquea
las solicitudes automáticas, puede que no sea posible extraer los horarios.
"""

import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "data" / "tv-data.json"

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

TIME_RE = re.compile(
    r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)"
)

BAD_TITLES = {
    "programacion",
    "programación",
    "ver mas",
    "ver más",
    "leer mas",
    "leer más",
    "inicio",
    "menu",
    "menú",
    "buscar",
    "noticias",
    "contacto",
    "facebook",
    "instagram",
    "youtube",
    "twitter",
    "x",
    "en vivo",
    "envivo",
}

SKIP_TAGS = {
    "script", "style", "noscript", "svg", "iframe",
    "header", "footer", "nav", "form", "button",
}


def clean_text(value):
    """Normaliza espacios y caracteres invisibles."""
    value = str(value or "").replace("\xa0", " ")
    value = re.sub(r"[\u200b-\u200f\uFEFF]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n|·•-–—:")


def fetch_html(url):
    """Descarga HTML de una página oficial."""
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; TVChileGuide/1.0; "
                "+https://github.com/)"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
        },
    )

    with urlopen(request, timeout=25) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read()

        charset_match = re.search(
            r"charset=([^\s;]+)", content_type, flags=re.I
        )
        charset = charset_match.group(1).strip('"\'') if charset_match else "utf-8"

        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")


class PageParser(HTMLParser):
    """
    Extrae texto de bloques que podrían representar programas.
    No considera texto de scripts, navegación ni estilos.
    """

    BLOCK_TAGS = {"tr", "li", "article"}
    BLOCK_HINTS = (
        "program", "horario", "schedule", "parrilla",
        "emision", "emisión", "evento", "show",
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.active_blocks = []
        self.blocks = []
        self.jsonld_parts = []
        self.capture_jsonld_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = str(attrs.get("class", "")).lower()
        element_id = str(attrs.get("id", "")).lower()
        hint_text = classes + " " + element_id

        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return

        if tag == "script" and str(attrs.get("type", "")).lower() == "application/ld+json":
            self.capture_jsonld_depth = 1
            self.jsonld_parts.append("")
            return

        if self.skip_depth:
            return

        is_candidate = (
            tag in self.BLOCK_TAGS
            or any(hint in hint_text for hint in self.BLOCK_HINTS)
        )

        if is_candidate:
            self.active_blocks.append({
                "tag": tag,
                "depth": 1,
                "text": [],
            })

        for block in self.active_blocks:
            if block["tag"] != tag or block not in self.active_blocks[-1:]:
                # La profundidad se gestiona en los eventos de cierre.
                pass

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.capture_jsonld_depth:
            if tag == "script":
                self.capture_jsonld_depth = 0
            return

        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return

        if self.skip_depth:
            return

        completed = []
        for block in self.active_blocks:
            if block["tag"] == tag:
                text = clean_text(" ".join(block["text"]))
                if text:
                    self.blocks.append(text)
                completed.append(block)

        for block in completed:
            self.active_blocks.remove(block)

    def handle_data(self, data):
        if self.capture_jsonld_depth:
            if self.jsonld_parts:
                self.jsonld_parts[-1] += data
            return

        if self.skip_depth:
            return

        text = clean_text(data)
        if not text:
            return

        for block in self.active_blocks:
            block["text"].append(text)


def walk_json(value):
    """Recorre objetos JSON-LD buscando nombres y horas de programas."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_jsonld(parser, channel, url):
    items = []

    for raw in parser.jsonld_parts:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        for obj in walk_json(data):
            title = (
                obj.get("name")
                or obj.get("headline")
                or obj.get("title")
            )

            if not isinstance(title, str):
                continue

            start = (
                obj.get("startDate")
                or obj.get("startTime")
                or obj.get("start_time")
            )

            if not isinstance(start, str):
                continue

            # ISO: 2026-10-26T20:30:00-03:00
            iso_match = re.search(
                r"T([01]?\d|2[0-3]):([0-5]\d)", start
            )
            if iso_match:
                hour = int(iso_match.group(1))
                minute = int(iso_match.group(2))
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", start)
                date_value = date_match.group(1) if date_match else None
            else:
                time_match = TIME_RE.search(start)
                if not time_match:
                    continue
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                date_value = None

            title = clean_text(title)
            if not valid_title(title):
                continue

            item = {
                "channel": channel,
                "title": title,
                "time": f"{hour:02d}:{minute:02d}",
                "source_url": url,
            }
            if date_value:
                item["date"] = date_value
            items.append(item)

    return items


def valid_title(title):
    title = clean_text(title)
    lowered = title.lower()

    if len(title) < 3 or len(title) > 100:
        return False

    if lowered in BAD_TITLES:
        return False

    if TIME_RE.fullmatch(title):
        return False

    # Evita capturar bloques que sean solamente etiquetas de navegación.
    if lowered.startswith(("http://", "https://", "www.")):
        return False

    return True


def extract_block_items(blocks, channel, url):
    """
    Busca horarios dentro de bloques que podrían representar una emisión.
    Los títulos largos se filtran para reducir capturas accidentales.
    """
    items = []
    seen = set()

    for block in blocks:
        text = clean_text(block)

        if len(text) > 260:
            continue

        matches = list(TIME_RE.finditer(text))
        if len(matches) != 1:
            continue

        match = matches[0]
        time_value = f"{int(match.group(1)):02d}:{match.group(2)}"

        # Retira la hora y separadores del texto candidato.
        title = text[:match.start()] + " " + text[match.end():]
        title = clean_text(title)

        # Si queda más texto después de la hora, puede ser una descripción.
        # Preferimos la parte más cercana antes de la hora cuando es legible.
        if " | " in title:
            title = title.split(" | ")[0].strip()

        if not valid_title(title):
            continue

        key = (channel, time_value, title.lower())
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "channel": channel,
            "title": title,
            "time": time_value,
            "source_url": url,
        })

    return items


def collect_channel(channel_info):
    channel = channel_info["channel"]
    url = channel_info["url"]

    try:
        html = fetch_html(url)

        parser = PageParser()
        parser.feed(html)
        parser.close()

        # Primero prioriza los datos estructurados.
        items = extract_jsonld(parser, channel, url)

        # Si no hay JSON-LD útil, intenta bloques de programación del HTML.
        if not items:
            items = extract_block_items(parser.blocks, channel, url)

        # Deduplicación final.
        unique = {}
        for item in items:
            key = (
                item["channel"],
                item["time"],
                item["title"].casefold(),
            )
            unique[key] = item

        items = sorted(
            unique.values(),
            key=lambda item: item["time"]
        )

        if items:
            return items, {
                "channel": channel,
                "status": "ok",
                "count": len(items),
                "source_url": url,
                "message": "Se detectaron horarios en la página oficial.",
            }

        return [], {
            "channel": channel,
            "status": "no_schedule_found",
            "count": 0,
            "source_url": url,
            "message": (
                "La página respondió, pero no se detectó una programación "
                "que se pudiera interpretar con seguridad."
            ),
        }

    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return [], {
            "channel": channel,
            "status": "error",
            "count": 0,
            "source_url": url,
            "message": f"No se pudo consultar la página: {type(exc).__name__}",
        }
    except Exception as exc:
        return [], {
            "channel": channel,
            "status": "error",
            "count": 0,
            "source_url": url,
            "message": f"Error al procesar la página: {type(exc).__name__}",
        }


def main():
    all_items = []
    channel_status = []

    for channel_info in CHANNELS:
        items, status = collect_channel(channel_info)
        all_items.extend(items)
        channel_status.append(status)

        print(
            f'{channel_info["channel"]}: '
            f'{status["status"]} ({len(items)} horarios)'
        )

        # Evita hacer solicitudes seguidas demasiado rápido.
        time.sleep(1)

    # Deduplicación global por canal, hora y título.
    deduplicated = {}
    for item in all_items:
        key = (
            item["channel"],
            item["time"],
            item["title"].casefold(),
        )
        deduplicated[key] = item

    all_items = sorted(
        deduplicated.values(),
        key=lambda item: (
            ["Mega", "Chilevisión", "Canal 13", "TVN"].index(item["channel"]),
            item["time"],
        ),
    )

    successful = sum(
        1 for status in channel_status if status["status"] == "ok"
    )

    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "America/Santiago",
        "status": "ok" if successful else "error",
        "schedule_status": "ok" if all_items else "error",
        "schedule_note": (
            "Horarios extraídos de páginas oficiales. "
            "La duración no se considera verificada."
        ),
        "schedule_items": all_items,
        "channel_status": channel_status,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\nTotal de horarios detectados: {len(all_items)}")
    print(f"Archivo guardado en: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
