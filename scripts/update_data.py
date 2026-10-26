
import json
import os
import re
import html
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from html.parser import HTMLParser

OUTPUT = "data/tv-data.json"
TZ = ZoneInfo("America/Santiago")

CHANNELS = [
    ("Mega", "https://www.mega.cl/programacion/"),
    ("Chilevisión", "https://www.chilevision.cl/page/programacion/"),
    ("Canal 13", "https://www.13.cl/programacion"),
    ("TVN", "https://www.tvn.cl/"),
]

TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
BLOCK_TAGS = {
    "br", "p", "div", "li", "tr", "td", "th",
    "section", "article", "h1", "h2", "h3",
    "h4", "header", "footer"
}


def clean(value):
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", value).strip(" \t\r\n|–—-:")


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif not self.skip and tag.lower() in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag.lower() in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def get_text(self):
        return clean(" ".join(self.parts))


def fetch_page(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-CL,es;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def title_is_valid(title):
    title = clean(title)

    if len(title) < 3 or len(title) > 100:
        return False

    lowered = title.casefold()

    unwanted = [
        "programación", "programacion", "inicio",
        "contacto", "privacidad", "cookies",
        "facebook", "instagram", "youtube",
        "lunes", "martes", "miércoles", "miercoles",
        "jueves", "viernes", "sábado", "sabado", "domingo",
        "ver más", "ver mas", "leer más", "leer mas",
        "noticias recientes", "todos los derechos reservados",
    ]

    if any(word in lowered for word in unwanted):
        return False

    if not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", title):
        return False

    # Evita tomar bloques de texto descriptivo como nombre del programa.
    if len(title.split()) > 10:
        return False

    return True


def extract_schedule(channel, url, page_html):
    parser = VisibleTextParser()
    parser.feed(page_html)
    text = parser.get_text()

    matches = list(TIME_RE.finditer(text))
    found = {}

    for index, match in enumerate(matches):
        # En las parrillas habituales el nombre del programa aparece
        # inmediatamente antes de su hora.
        previous_end = matches[index - 1].end() if index > 0 else 0
        title = clean(text[previous_end:match.start()])

        # El texto inicial puede contener navegación y encabezados.
        # Se toma solo el fragmento final, no todo el bloque.
        title = re.split(r"[.!?]\s+", title)[-1].strip()

        if not title_is_valid(title):
            continue

        hour = int(match.group(1))
        minute = int(match.group(2))
        time = f"{hour:02d}:{minute:02d}"

        item = {
            "channel": channel,
            "title": title,
            "time": time,
            "source_url": url,
        }

        key = (channel, time, title.casefold())
        found[key] = item

    return list(found.values())


def main():
    updated_at = datetime.now(TZ).isoformat(timespec="seconds")
    all_items = []
    statuses = []

    for channel, url in CHANNELS:
        try:
            page = fetch_page(url)
            entries = extract_schedule(channel, url, page)

            statuses.append({
                "channel": channel,
                "status": "ok" if entries else "no_schedule_found",
                "source_url": url,
                "count": len(entries),
                "message": (
                    "Se detectaron posibles programas y horarios."
                    if entries else
                    "La página se pudo leer, pero no se identificaron horarios fiables."
                ),
            })

            all_items.extend(entries)
            print(f"{channel}: {len(entries)} horarios detectados")

        except Exception as exc:
            statuses.append({
                "channel": channel,
                "status": "error",
                "source_url": url,
                "count": 0,
                "message": str(exc)[:250],
            })
            print(f"{channel}: error al consultar la página: {exc}")

    # Elimina duplicados y ordena por hora.
    unique = {}
    for item in all_items:
        key = (
            item["channel"],
            item["time"],
            item["title"].casefold(),
        )
        unique[key] = item

    all_items = sorted(
        unique.values(),
        key=lambda item: (item["time"], item["channel"]),
    )

    has_errors = any(
        status["status"] != "ok" for status in statuses
    )

    data = {
        "updated_at": updated_at,
        "timezone": "America/Santiago",
        "status": "partial" if has_errors else "ok",
        "schedule_status": "available" if all_items else "not_found",
        "schedule_note": (
            "Horarios extraídos del texto visible de las páginas oficiales. "
            "Comprueba el canal para confirmar cambios."
            if all_items else
            "No se detectaron horarios en las páginas consultadas."
        ),
        "schedule_items": all_items,
        "channel_status": statuses,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(
        f"Resultado: {len(all_items)} horarios en total. "
        f"Archivo: {OUTPUT}"
    )


if __name__ == "__main__":
    main()
