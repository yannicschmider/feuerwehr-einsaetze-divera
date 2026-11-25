"""
Holt die Einsätze aus Divera, ergänzt sie in einsatzdaten.json und erzeugt
daraus einsatz_website.html.

Läuft genau einmal durch (keine Endlosschleife) und ist für GitHub Actions
gedacht: Der Workflow ruft das Skript per Cron auf und committet danach
einsatzdaten.json + einsatz_website.html, falls sich etwas geändert hat.
"""
from typing import Any, Dict, Iterable
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
import json
import os
import re
import sys

import requests

ACCESS_KEY = os.environ.get("DIVERA_API_KEY")
ALARMS_API_URL = "https://app.divera247.com/api/v2/alarms"
REQUEST_TIMEOUT = 15  # Sekunden
EINSATZDATEN_FILE = "einsatzdaten.json"
TRANSLATIONS_FILE = "translations.json"
OUTPUT_HTML_FILE = "einsatz_website.html"
FILTER_WORDS = ["test", "übung", "noshow"]
# GitHub-Runner laufen in UTC, die Uhrzeiten sollen aber deutsche Zeit sein
TIMEZONE = ZoneInfo("Europe/Berlin")
# Auf der Seite werden nur Einsätze dieses Jahres angezeigt
YEAR = int(os.environ.get("EINSATZ_JAHR", datetime.now(TIMEZONE).year))
# Gruppe "Kommando" soll immer zuerst stehen
KOMMANDO_GROUP_ID = 99789
# Nur diese Felder landen in einsatzdaten.json. Das Repo ist öffentlich,
# Alarmtext, Leitstellennummer usw. haben dort nichts zu suchen.
PUBLIC_FIELDS = ["id", "date", "time", "title", "address", "group", "closed"]


def fetch_einsaetze() -> Iterable[Dict[str, Any]]:
    response = requests.get(
        ALARMS_API_URL, params={"accesskey": ACCESS_KEY}, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    items = data.get("data", {}).get("items", {})
    # Divera liefert ein Objekt {id: alarm}, bei keinen Alarmen teils eine leere Liste
    return items.values() if isinstance(items, dict) else items


# --- Hilfsfunktionen zum Säubern ---
def sanitize_address(address: str) -> str:
    if not address:
        return ""

    # Hausnummern inkl. Varianten wie "7A" oder "7 A" entfernen
    address = re.sub(r"\b\d+\s?[a-zA-Z]?\b", "", address)

    # Leerzeichen vor Komma entfernen
    address = re.sub(r"\s+,", ",", address)

    # Überflüssige Leerzeichen bereinigen
    address = re.sub(r"\s{2,}", " ", address).strip()

    # Doppelte Ortsbezeichnungen (e.g. "Hausach Hausach-Ost")
    parts = address.split(", ")
    if len(parts) == 2:
        city_parts = parts[1].split()
        # Fall 1: "Hausach Hausach-Ost"
        if len(city_parts) == 2 and city_parts[0] in city_parts[1]:
            parts[1] = city_parts[1]
        # Fall 2: "Haslach im Kinzigtal Haslach"
        elif len(city_parts) >= 2 and city_parts[-1] in city_parts[:-1]:
            parts[1] = " ".join(city_parts[:-1])
        address = ", ".join(parts)

    return address


def sanitize_stichwort(stichwort: str) -> str:
    if not stichwort:
        return ""
    # Doppelte Kürzel entfernen (z. B. "M M 1" -> "M 1")
    stichwort = re.sub(r"\b(\w+)(?:\s+\1)+\b", r"\1", stichwort)
    # Leitstellen-Zusätze ab "//" entfernen (z. B. "// R 1.2", "// N1 3.2", "// N1 01")
    stichwort = re.sub(r"\s*//.*$", "", stichwort)
    # Angehängtes "P" und/oder laufende Nummer entfernen (z. B. "Gebäudebrand P 01",
    # "Luftfahrzeug P", "BMA  01")
    stichwort = re.sub(r"(\s+P)?(\s+\d{2})?\s*$", "", stichwort)
    return stichwort.strip()


# --- Einsatzspeicherlogik ---
def load_einsatzdaten() -> list:
    try:
        with open(EINSATZDATEN_FILE, "r", encoding="utf-8") as f:
            return [strip_private(e) for e in json.load(f)]
    except FileNotFoundError:
        return []


def strip_private(einsatz: Dict[str, Any]) -> Dict[str, Any]:
    return {k: einsatz[k] for k in PUBLIC_FIELDS if k in einsatz}


def process_einsaetze(einsatz_list: list) -> list:
    """Ergänzt/aktualisiert die Einsätze aus Divera in einsatz_list."""
    einsatz_index = {e["id"]: e for e in einsatz_list}

    for einsatz in fetch_einsaetze():
        title = einsatz.get("title", "").lower()
        text = einsatz.get("text", "").lower()
        if any(word in title or word in text for word in FILTER_WORDS):
            continue

        ts = datetime.fromtimestamp(einsatz.get("date", 0), TIMEZONE)
        fields = {
            "date": ts.strftime("%Y-%m-%d"),
            "time": ts.strftime("%H:%M:%S"),
            "title": sanitize_stichwort(einsatz.get("title", "")),
            "address": sanitize_address(einsatz.get("address", "")),
            "group": einsatz.get("group", []),
            "closed": einsatz.get("closed", True),
        }

        if einsatz["id"] in einsatz_index:
            einsatz_index[einsatz["id"]].update(fields)
        else:
            new_einsatz = {"id": einsatz["id"], **fields}
            einsatz_list.append(new_einsatz)
            einsatz_index[einsatz["id"]] = new_einsatz

    # Neueste oben
    einsatz_list.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return einsatz_list


def save_einsatzdaten(einsatz_list: list) -> None:
    with open(EINSATZDATEN_FILE, "w", encoding="utf-8") as f:
        json.dump(einsatz_list, f, ensure_ascii=False, indent=4)
        f.write("\n")


# --- HTML Erstellung ---
HTML_HEAD = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Einsätze {year}</title>
<style>
body {{
    font-family: Montserrat, sans-serif;
    background-color: #2E2E2E;
    color: #ffffff;
}}
h1 {{
    color: #E94232;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    background-color: #3E3E3E;
}}
th, td {{
    border: 1px solid #222;
    padding: 8px;
    text-align: left;
    color: #ffffff;
}}
th {{
    background-color: #555555;
}}
tr:nth-child(even) {{
    background-color: #4E4E4E;
}}
.live-indicator {{
    display: inline-block;
    width: 12px;
    height: 12px;
    margin-right: 5px;
    border-radius: 50%;
    background-color: #E94232;
    animation: pulse 1.5s infinite;
    vertical-align: middle;
}}
@keyframes pulse {{
    0% {{ transform: scale(1); opacity: 1; }}
    50% {{ transform: scale(1.5); opacity: 0.6; }}
    100% {{ transform: scale(1); opacity: 1; }}
}}
</style>
</head>
<body>
<h1>Einsätze {year}</h1>
<table>
<tr>
<th>Datum</th>
<th>Uhrzeit</th>
<th>Stichwort</th>
<th>Ort</th>
<th>Gruppe</th>
</tr>
"""


def generate_html_page(einsatz_list: list) -> None:
    with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
        group_trans = json.load(f).get("groups", {})

    html = HTML_HEAD.format(year=YEAR)

    for einsatz in einsatz_list:
        if not einsatz.get("date", "").startswith(str(YEAR)):
            continue

        datum = datetime.strptime(einsatz["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
        uhrzeit = escape(einsatz.get("time", ""))
        stichwort = escape(einsatz.get("title", ""))
        live_html = '<span class="live-indicator">LIVE</span>' if not einsatz.get("closed", True) else ""
        ort = escape(einsatz.get("address", ""))

        gruppen_ids = einsatz.get("group", [])
        if KOMMANDO_GROUP_ID in gruppen_ids:
            gruppen_ids = [KOMMANDO_GROUP_ID] + [g for g in gruppen_ids if g != KOMMANDO_GROUP_ID]
        gruppen_str = escape(", ".join(group_trans.get(str(gid), str(gid)) for gid in gruppen_ids))

        html += (
            f"<tr><td>{datum}</td><td>{uhrzeit}</td><td>{stichwort} {live_html}</td>"
            f"<td>{ort}</td><td>{gruppen_str}</td></tr>\n"
        )

    html += "</table>\n</body>\n</html>\n"

    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)


def main() -> None:
    if not ACCESS_KEY:
        sys.exit("DIVERA_API_KEY ist nicht gesetzt!")

    einsatz_list = process_einsaetze(load_einsatzdaten())
    save_einsatzdaten(einsatz_list)
    generate_html_page(einsatz_list)
    print(f"{len(einsatz_list)} Einsätze gespeichert, HTML erstellt.")


if __name__ == "__main__":
    main()
