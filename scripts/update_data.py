
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Recolector de programación para la Guía de TV Chile.
Fuentes oficiales. Si una fuente no se puede interpretar, se registra
el error y no se inventan horarios.
"""

import json
import re
import html
import os
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Santiago")

SOURCES = {
    "Mega": "https://www.mega.cl/programacion/",
    "Chilevisión": "https://www.chilevision.cl/page/programacion/",
    "Canal 13": "https://www.13.cl/programacion",
    "TVN": "https://www.tvn.cl/",
}

CANAL13_EPG = "https://www.13.cl/sites/default/files/tools/epg-canal13.json"

OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "tv-data.json",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GuiaTVChile/1.0; "
        "+https://github.com/)"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
}

TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
TIME_IN_TEXT = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)")


class TextExtractor(HTMLParser):
    """Extrae texto visible de una página, ignorando scripts y estilos."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript", "svg", "iframe"):
            self.skip_depth += 1
        if tag.lower() in ("br", "p", "div", "li", "article", "section"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript", "svg", "iframe"):
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag.lower() in ("p", "div", "li", "article", "section"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)

    def get_text(self):
        return "\n".join(self.parts)


def fetch(url, timeout=25):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")


def fetch_json(url):
    raw = fetch(url)
    return json.loads(raw)


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def valid_title(value):
    title = clean_text(value)
    if not title or len(title) < 3 or len(title) > 180:
        return False

    low = title.casefold()
    bad = (
        "ver programa", "ver más", "ver mas", "leer más", "leer mas",
        "programación", "programacion", "señal en vivo",
        "señal online", "menú", "menu", "inicio", "facebook",
        "instagram", "youtube", "publicidad",
    )
    if low in bad:
        return False
    if TIME_RE.fullmatch(title):
        return False
    if len(re.findall(r"\d", title)) > len(title) * 0.55:
        return False

    return True


def add_item(items, channel, title, time_value, source_url, summary=""):
    title = clean_text(title)
    time_value = clean_text(time_value)

    if not valid_title(title) or not TIME_RE.fullmatch(time_value):
        return

    items.append({
        "channel": channel,
        "title": title,
        "time": time_value.zfill(5),
        "source_url": source_url,
        "summary": clean_text(summary),
    })


def recursive_json_events(obj, output, channel, source_url):
    """
    Busca objetos JSON con un nombre y un campo horario.
    Se aceptan solo campos reconocibles; no se interpreta una fecha
    aislada como si fuera la hora de un programa.
    """
    if isinstance(obj, dict):
        lowered = {str(k).lower(): v for k, v in obj.items()}

        title = None
        for key in ("title", "titulo", "name", "nombre", "programa",
                    "program_name", "eventtitle"):
            value = lowered.get(key)
            if isinstance(value, str) and valid_title(value):
                title = value
                break

        time_value = None
        for key in ("time", "hora", "start_time", "starttime",
                    "start", "begin", "begin_time", "horainicio"):
            value = lowered.get(key)
            if isinstance(value, str):
                match = TIME_IN_TEXT.search(value)
                if match:
                    time_value = match.group(0)
                    break
            elif isinstance(value, (int, float)):
                # Unix timestamps se manejan aparte, no como minutos.
                continue

        summary = ""
        for key in ("description", "descripcion", "summary", "sinopsis"):
            value = lowered.get(key)
            if isinstance(value, str) and value.strip():
                summary = value
                break

        if title and time_value:
            add_item(output, channel, title, time_value, source_url, summary)

        for value in obj.values():
            recursive_json_events(value, output, channel, source_url)

    elif isinstance(obj, list):
        for value in obj:
            recursive_json_events(value, output, channel, source_url)


def parse_json_ld(page, channel, source_url):
    items = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.I | re.S,
    )

    for match in pattern.finditer(page):
        try:
            data = json.loads(match.group(1).strip())
        except (ValueError, TypeError):
            continue

        recursive_json_events(data, items, channel, source_url)

    return items


def parse_channel13_epg():
    """
    Intenta leer el EPG JSON publicado por Canal 13.
    La estructura puede cambiar; si no se reconocen sus campos,
    la fuente queda marcada como no interpretable.
    """
    items = []
    data = fetch_json(CANAL13_EPG)
    recursive_json_events(data, items, "Canal 13", CANAL13_EPG)
    return deduplicate(items)


def parse_html_schedule(channel, url, page):
    """
    Parser de respaldo para páginas que publican horarios como texto.
    Se empareja cada hora con un título cercano, y se descartan
    enlaces de navegación y textos que no parecen nombres de programas.
    Requiere revisión si el sitio cambia su estructura.
    """
    items = []
    extractor = TextExtractor()
    extractor.feed(page)
    lines = [
        clean_text(line)
        for line in extractor.get_text().splitlines()
        if clean_text(line)
    ]

    for i, line in enumerate(lines):
        time_match = TIME_IN_TEXT.fullmatch(line)
        if not time_match:
            continue

        time_value = time_match.group(0)

        # En algunas parrillas el nombre va antes de la hora y en otras
        # aparece inmediatamente después. Se prueban ambos lados.
        candidates = []
        if i > 0:
            candidates.append(lines[i - 1])
        if i + 1 < len(lines):
            candidates.append(lines[i + 1])

        title = next((candidate for candidate in candidates
                      if valid_title(candidate)), None)

        if title:
            add_item(items, channel, title, time_value, url)

    # El parser de texto no garantiza que cada pareja sea un programa real.
    # Se eliminan duplicados exactos; la acción registra cuántos obtuvo.
    return deduplicate(items)


def deduplicate(items):
    unique = {}
    for item in items:
        key = (
            item.get("channel", ""),
            item.get("title", "").casefold(),
            item.get("time", ""),
        )
        if key not in unique:
            unique[key] = item
        elif not unique[key].get("summary") and item.get("summary"):
            unique[key]["summary"] = item["summary"]
    return list(unique.values())


def collect_channel(channel, url):
    errors = []
    items = []

    try:
        page = fetch(url)
        items.extend(parse_json_ld(page, channel, url))
        items.extend(parse_html_schedule(channel, url, page))
    except Exception as exc:
        errors.append(f"No se pudo leer la página oficial: {exc}")

    items = deduplicate(items)

    if not items:
        return [], {
            "channel": channel,
            "status": "no_schedule_found",
            "source_url": url,
            "items_found": 0,
            "message": (
                "; ".join(errors) if errors
                else "La página se pudo consultar, pero no se detectó una parrilla interpretable."
            ),
        }

    return items, {
        "channel": channel,
        "status": "ok",
        "source_url": url,
        "items_found": len(items),
        "message": "Se detectaron horarios; revisar la parrilla si el sitio cambió su estructura.",
    }


def main():
    now = datetime.now(TZ)
    all_items = []
    statuses = []

    for channel, url in SOURCES.items():
        try:
            if channel == "Canal 13":
                try:
                    items = parse_json_ld(
                        fetch(url), channel, url
                    )
                except Exception:
                    items = []

                try:
                    epg_items = parse_json_ld(
                        fetch(CANAL13_EPG), channel, CANAL13_EPG
                    )
                except Exception:
                    epg_items = []

                try:
                    epg_items.extend(parse_json_ld(
                        json.dumps(fetch_json(CANAL13_EPG)),
                        channel,
                        CANAL13_EPG,
                    ))
                    recursive_json_events(
                        fetch_json(CANAL13_EPG),
                        epg_items,
                        channel,
                        CANAL13_EPG,
                    )
                except Exception:
                    pass

                if not epg_items:
                    try:
                        page = fetch(url)
                        epg_items = parse_html_schedule(channel, url, page)
                    except Exception:
                        epg_items = []

                items = deduplicate(items + epg_items)
                if items:
                    all_items.extend(items)
                    statuses.append({
                        "channel": channel,
                        "status": "ok",
                        "source_url": CANAL13_EPG,
                        "items_found": len(items),
                        "message": "Datos obtenidos de fuentes oficiales.",
                    })
                else:
                    statuses.append({
                        "channel": channel,
                        "status": "no_schedule_found",
                        "source_url": CANAL13_EPG,
                        "items_found": 0,
                        "message": "No se pudo interpretar una parrilla válida desde el EPG.",
                    })
                continue

            items, status = collect_channel(channel, url)
            all_items.extend(items)
            statuses.append(status)

        except Exception as exc:
            statuses.append({
                "channel": channel,
                "status": "error",
                "source_url": url,
                "items_found": 0,
                "message": str(exc),
            })

    all_items = deduplicate(all_items)
    all_items.sort(key=lambda item: (
        item.get("channel", ""),
        item.get("time", ""),
        item.get("title", ""),
    ))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

    success_count = sum(
        1 for status in statuses if status["status"] == "ok"
    )

    result = {
        "updated_at": now.isoformat(),
        "timezone": "America/Santiago",
        "status": (
            f"Actualización ejecutada: {success_count} de "
            f"{len(SOURCES)} canales con datos detectados."
        ),
        "schedule_status": (
            "ok" if success_count == len(SOURCES) else "partial"
        ),
        "schedule_note": (
            "Los horarios detectados provienen de páginas oficiales. "
            "Un canal sin datos interpretables se informa como tal; "
            "no se completan horarios con datos inventados."
        ),
        "schedule_items": all_items,
        "channel_status": statuses,
    }

    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(json.dumps({
        "output": OUTPUT,
        "items_total": len(all_items),
        "channels": statuses,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
