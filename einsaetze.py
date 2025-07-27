import os
import re
import json
import html
import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

ACCESS_KEY = os.environ.get("DIVERA_API_KEY")
if not ACCESS_KEY:
    raise RuntimeError("Environment-Variable DIVERA_API_KEY ist nicht gesetzt!")

ALARMS_API_URL = f"https://app.divera247.com/api/v2/alarms?accesskey={ACCESS_KEY}"
VEHICLE_STATUS_URL = "https://www.divera247.com/api/v2/using-vehicles/get-status/{vid}?accesskey={accesskey}"

TRANSLATIONS_FILE = "translations.json"
ACTIVE_VEHICLES_FILE = "active_vehicles.json"  # Persistenz pro Einsatz-ID
REQUEST_TIMEOUT = 10  # Sekunden

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_json_file(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json_file(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_translations(file_path: str = TRANSLATIONS_FILE) -> Dict[str, Dict[str, str]]:
    data = load_json_file(file_path, {"groups": {}, "vehicles": {}})
    # Keys als Strings sicherstellen
    data["groups"] = {str(k): v for k, v in data.get("groups", {}).items()}
    data["vehicles"] = {str(k): v for k, v in data.get("vehicles", {}).items()}
    return data



# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------

def sanitize_address(address: str) -> str:
    if not address:
        return ""
    # Hausnummern inkl. Varianten wie "7A" oder "7 A" entfernen
    address = re.sub(r"\b\d+\s?[a-zA-Z]?\b", "", address)

    # Überflüssige Leerzeichen bereinigen
    address = re.sub(r"\s{2,}", " ", address).strip()

    # Doppelte Ortsbezeichnungen (e.g. "Hausach Hausach-Ost")
    parts = address.split(", ")
    if len(parts) == 2:
        city_parts = parts[1].split()
        if len(city_parts) == 2 and city_parts[0] in city_parts[1]:
            parts[1] = city_parts[1]  # z. B. "Hausach-Ost"
        address = ", ".join(parts)

    return address


def sanitize_stichwort(stichwort: str) -> str:
    if not stichwort:
        return ""
    # Doppelte Kürzel entfernen (z. B. "M M 1" -> "M 1")
    stichwort = re.sub(r"\b(\w+)(?:\s+\1)+\b", r"\1", stichwort)
    # Muster "// R" gefolgt von einer Zahl entfernen (z. B. "// R 1.2" oder "// R 84")
    stichwort = re.sub(r"// R\s?\d+(\.\d+)?", "", stichwort)
    return stichwort.strip()


# ---------------------------------------------------------------------------
# Übersetzer
# ---------------------------------------------------------------------------

translations = load_translations()
GROUPS: Dict[str, str] = translations.get("groups", {})
VEHICLES: Dict[str, str] = translations.get("vehicles", {})

def translate_group(group_data: Any) -> str:
    if isinstance(group_data, list):
        return ", ".join(GROUPS.get(str(g), "Unbekannte Gruppe") for g in group_data)
    return GROUPS.get(str(group_data), "Unbekannte Gruppe")


def translate_vehicle(vehicle_data: Any) -> str:
    if isinstance(vehicle_data, list):
        return ", ".join(VEHICLES.get(str(v), f"Unbekanntes Fahrzeug ({v})") for v in vehicle_data)
    return VEHICLES.get(str(vehicle_data), f"Unbekanntes Fahrzeug ({vehicle_data})")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_einsaetze() -> Iterable[Dict[str, Any]]:
    response = requests.get(ALARMS_API_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    items = data.get("data", {}).get("items", {})
    if isinstance(items, dict):
        return items.values()
    # Falls die API irgendwann eine Liste liefert
    return items


def fetch_vehicle_status(vehicle_id):
    url = f"https://www.divera247.com/api/v2/using-vehicles/get-status/{vehicle_id}?accesskey={ACCESS_KEY}"
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


def get_active_vehicles_currently() -> List[str]:
    """
    Liest für alle in translations.json gelisteten Fahrzeuge den Status
    und gibt eine Liste *übersetzter* Fahrzeugnamen zurück, wenn Status 3 oder 4.
    Fahrzeuge mit ID '60060' werden ignoriert und nicht zurückgegeben.
    """
    ignore_id = "60060"
    active = []
    
    for vid in VEHICLES.keys():
        if str(vid) == ignore_id:
            # Ignoriere dieses Fahrzeug/Gerätehaus komplett
            continue
        try:
            status_data = fetch_vehicle_status(vid)            
            status = status_data.get("status")
            if status in (3, 4):
                fahrzeug_name = VEHICLES.get(str(vid), f"ID {vid}")
                active.append(fahrzeug_name)
                print(f"--> Aktiv: {fahrzeug_name}")
        except Exception as e:
            print(f"[WARN] Fahrzeugstatus für {vid} konnte nicht gelesen werden: {e}")
    return active




# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def generate_html(einsaetze: Iterable[Dict[str, Any]], active_map: Dict[str, List[str]]) -> None:
    now = datetime.datetime.now()
    year_now = now.year

    ignore_pattern = re.compile(r"\b(test|übung|noshow)\b", re.IGNORECASE)

    html_doc = f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Einsätze</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 8px 12px; border: 1px solid #ccc; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        small {{ color: #666; }}
    </style>
</head>
<body>
<h2>Einsätze des Jahres {year_now}</h2>
<small>Zuletzt aktualisiert: {now.strftime('%d.%m.%Y %H:%M:%S')}</small>
<table>
    <tr>
        <th>Datum</th>
        <th>Uhrzeit</th>
        <th>Stichwort</th>
        <th>Ort</th>
        <th>Report</th>
        <th>Gruppe</th>
        <th>Fahrzeuge</th>
    </tr>
"""

    for einsatz in einsaetze:
        try:
            ts = datetime.datetime.fromtimestamp(int(einsatz["date"]))
        except Exception:
            ts = now

        if ts.year != year_now:
            continue

        titel = einsatz.get("title", "")
        text = einsatz.get("text", "")
        report = einsatz.get("report", "")

        # Wenn im Titel oder Text das Schlüsselwort vorkommt, überspringen
        if ignore_pattern.search(titel) or ignore_pattern.search(text):
            continue

        einsatz_id = str(einsatz.get("id", ""))
        raw_address = einsatz.get("address", "")
        clean_address = sanitize_address(raw_address)
        report_escaped = html.escape(report)
        group = translate_group(einsatz.get("group", []))
        stichwort = sanitize_stichwort(titel)

        ausgerueckt = ", ".join(active_map.get(einsatz_id, []))

        html_doc += f"""<tr>
            <td>{ts.strftime('%d.%m.%Y')}</td>
            <td>{ts.strftime('%H:%M')}</td>
            <td>{html.escape(stichwort)}</td>
            <td>{html.escape(clean_address)}</td>
            <td>{report_escaped}</td>
            <td>{html.escape(group)}</td>
            <td>{html.escape(ausgerueckt)}</td>
        </tr>
"""

    html_doc += """
</table>
</body>
</html>
"""

    with open("einsaetze.html", "w", encoding="utf-8") as f:
        f.write(html_doc)


def main() -> None:
    # Vorhandene Map laden (Persistenz)
    active_map: Dict[str, List[str]] = load_json_file(ACTIVE_VEHICLES_FILE, {})

    print("[INFO] Lade Einsätze…")
    einsaetze_list = list(fetch_einsaetze())
    print(f"[INFO] {len(einsaetze_list)} Einsätze erhalten.")

    # Hol dir die aktuell ausgerückten Fahrzeuge (Status 3/4)
    print("[INFO] Prüfe Fahrzeug-Status…")
    currently_active_vehicles = get_active_vehicles_currently()

    # Pro Einsatz aktualisieren, wenn nicht geschlossen
    updated = False
    for einsatz in einsaetze_list:
        einsatz_id = str(einsatz.get("id", ""))
        closed = einsatz.get("closed", False)

        # Wenn closed False oder 0 etc., dann updaten
        if not closed:
            prev = set(active_map.get(einsatz_id, []))
            new = set(currently_active_vehicles)
            merged = sorted(prev.union(new))
            if merged != active_map.get(einsatz_id, []):
                active_map[einsatz_id] = merged
                updated = True
        else:
            # Einsatz geschlossen: nichts mehr hinzufügen; Eintrag bleibt bestehen
            if einsatz_id not in active_map:
                active_map[einsatz_id] = []

    if updated:
        print("[INFO] Speichere aktualisierte aktive Fahrzeugliste…")
        save_json_file(ACTIVE_VEHICLES_FILE, active_map)

    print("[INFO] Generiere HTML…")
    generate_html(einsaetze_list, active_map)
    print("[INFO] Fertig. Datei 'einsaetze.html' erstellt/aktualisiert.")


if __name__ == "__main__":
    main()

