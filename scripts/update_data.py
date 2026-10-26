
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

OUTPUT = "data/tv-data.json"

QUERIES = [
    ("Mega", "site:mega.cl programas invitados televisión Chile"),
    ("Chilevisión", "site:chilevision.cl programas invitados televisión"),
    ("Canal 13", "site:13.cl programas invitados televisión Chile"),
    ("TVN", "site:tvn.cl programas invitados televisión Chile"),
    ("Farándula", "farándula chilena polémicas televisión hoy"),
    ("Realities", "reality chileno participantes novedades hoy"),
    ("Entretención", "programas de entretención Chile invitados"),
]

OFFICIAL_DOMAINS = (
    "mega.cl",
    "chilevision.cl",
    "13.cl",
    "tvn.cl",
)

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None

def is_official(source_url):
    host = urllib.parse.urlparse(source_url or "").hostname or ""
    host = host.lower().removeprefix("www.")
    return any(
        host == domain or host.endswith("." + domain)
        for domain in OFFICIAL_DOMAINS
    )

def fetch(query, category):
    params = urllib.parse.urlencode({
        "q": query,
        "hl": "es-419",
        "gl": "CL",
        "ceid": "CL:es-419",
    })
    url = "https://news.google.com/rss/search?" + params
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 TVGuide/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read())

    items = []
    for item in root.findall(".//item"):
        title = clean(item.findtext("title"))
        link = clean(item.findtext("link"))
        source_node = item.find("source")
        source = clean(source_node.text if source_node is not None else "")
        source_url = (
            source_node.attrib.get("url", "")
            if source_node is not None else ""
        )

        if not title or not link:
            continue

        official = is_official(source_url)
        items.append({
            "title": title,
            "url": link,
            "source": source or "Fuente no identificada",
            "source_url": source_url,
            "published_at": parse_date(item.findtext("pubDate")),
            "category": category,
            "confidence": "probable" if official else "unverified",
            "confidence_reason": (
                "Publicación atribuida a un sitio oficial; el dato específico debe comprobarse."
                if official else
                "Noticia encontrada; no confirma por sí sola horarios ni invitados."
            ),
        })

    return items

def main():
    now = datetime.now(timezone.utc).isoformat()
    results = []
    errors = []

    for category, query in QUERIES:
        try:
            results.extend(fetch(query, category))
        except Exception as exc:
            errors.append({
                "category": category,
                "error": str(exc)[:300],
            })

    unique = {}
    for item in results:
        key = item["url"] or item["title"]
        if key not in unique:
            unique[key] = item

    items = sorted(
        unique.values(),
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )

    data = {
        "updated_at": now,
        "timezone": "America/Santiago",
        "status": "partial" if errors else "ok",
        "schedule_status": "not_verified",
        "schedule_note": (
            "Los horarios de emisión no se publican como confirmados "
            "hasta disponer de una fuente fiable de programación."
        ),
        "items": items[:100],
        "errors": errors,
    }

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    print(
        f"Guardados {len(data['items'])} elementos; "
        f"errores de consulta: {len(errors)}"
    )

if __name__ == "__main__":
    main()
