import requests
import datetime
import os
import re
import json

ACCESS_KEY = os.environ.get("DIVERA_API_KEY")
API_URL = f"https://app.divera247.com/api/v2/alarms?accesskey={ACCESS_KEY}"

def fetch_einsaetze():
    response = requests.get(API_URL)
    response.raise_for_status()
    data = response.json()
    return data["data"]["items"].values()

def sanitize_address(address):
    if not address:
        return ""

    # Hausnummern entfernen (Ziffern und ggf. Buchstaben, z.B. "7A")
    address = re.sub(r"\b\d+[a-zA-Z]?\b", "", address)

    # Überflüssige Leerzeichen bereinigen
    address = re.sub(r"\s{2,}", " ", address).strip()

    # Doppelte Ortsbezeichnungen (z. B. "Hausach Hausach-Ost")
    parts = address.split(", ")
    if len(parts) == 2:
        city_parts = parts[1].split()
        if len(city_parts) == 2 and city_parts[0] in city_parts[1]:
            parts[1] = city_parts[1]  # z. B. "Hausach-Ost"
        address = ", ".join(parts)

    return address

def sanitize_stichwort(stichwort):
    # Doppelte Kürzel entfernen (z. B. "M M 1" -> "M 1")
    stichwort = re.sub(r"(\b\w+\b)\s+\1", r"\1", stichwort)

    # Muster "// R" gefolgt von einer Zahl entfernen (z. B. "// R 1.2" oder "// R 84")
    stichwort = re.sub(r"// R\s?\d+(\.\d+)?", "", stichwort)

    return stichwort.strip()

def load_translations(file_path="translations.json"):
    with open(file_path, "r", encoding="utf-8") as f:
        translations = json.load(f)
    return translations

# Lade die Übersetzungen
translations = load_translations()

# Zugriff auf die Gruppen- und Fahrzeugübersetzungen
GROUPS = translations["groups"]
VEHICLES = translations["vehicles"]

def translate_group(group_id):
    return GROUPS.get(group_id, "Unbekannte Gruppe")

def translate_vehicle(vehicle_id):
    return VEHICLES.get(vehicle_id, "Unbekanntes Fahrzeug")


def generate_html(einsaetze):
    html = f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Einsätze</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 8px 12px; border: 1px solid #ccc; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
<h2>Einsätze des Jahres {datetime.datetime.now().year}</h2>
<table>
    <tr><th>Datum</th><th>Uhrzeit</th><th>Stichwort</th><th>Ort</th><th>Report</th><th>Fahrzeug</th><th>Gruppe</th></tr>
"""

    for einsatz in einsaetze:
        ts = datetime.datetime.fromtimestamp(int(einsatz["date"]))
        if ts.year == datetime.datetime.now().year:
            raw_address = einsatz.get("address", "")
            clean_address = sanitize_address(raw_address)
            report = einsatz.get("report", "")  # Füge Report hinzu
            vehicle = translate_vehicle(einsatz.get("vehicle", "Unbekannt"))  # Übersetze Fahrzeug-ID
            group = translate_group(einsatz.get("group", 0))  # Übersetze Gruppen-ID
            
            html += f"""<tr>
                <td>{ts.strftime('%d.%m.%Y')}</td>
                <td>{ts.strftime('%H:%M')}</td>
                <td>{sanitize_stichwort(einsatz.get('title', ''))}</td>
                <td>{clean_address}</td>
                <td>{report}</td>
                <td>{vehicle}</td>
                <td>{group}</td>
            </tr>"""

    html += """
</table>
</body>
</html>
"""
    with open("einsaetze.html", "w", encoding="utf-8") as f:
        f.write(html)
