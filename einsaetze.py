from typing import Any, Dict, Iterable
import requests
import json
from datetime import datetime
import re
import time
import hashlib
import base64

ACCESS_KEY = "xxxx"
ALARMS_API_URL = f"https://app.divera247.com/api/v2/alarms?accesskey={ACCESS_KEY}"
REQUEST_TIMEOUT = 10  # Sekunden
EINSATZDATEN_FILE = "einsatzdaten.json"
TRANSLATIONS_FILE = "translations.json"
OUTPUT_HTML_FILE = "einsatz_website.html"
FILTER_WORDS = ["test", "übung", "noshow"]
GITHUB_TOKEN = "github_pat_xxx"
OWNER = "yannicschmider"
REPO = "feuerwehr-einsaetze-divera"
BRANCH = "main"

last_hash = None

def fetch_einsaetze() -> Iterable[Dict[str, Any]]:
    response = requests.get(ALARMS_API_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    items = data.get("data", {}).get("items", {})
    return items.values()

def get_vehicle_status(vehicle_id):
    url = f"https://www.divera247.com/api/v2/using-vehicles/get-status/{vehicle_id}?accesskey={ACCESS_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Fehler beim Abrufen von Fahrzeug {vehicle_id}: {e}")
        return None

# --- JSON mit Fahrzeugen laden ---
with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
    translations = json.load(f)

all_vehicles = list(translations.get("vehicles", {}).keys())
print(all_vehicles)

def get_active_vehicles():
    """
    Prüft die Fahrzeuge nur bei aktiven Einsätzen und gibt eine Liste
    von IDs zurück, deren Status 3 oder 4 ist.
    """
    active_vehicles = []
    for vid in all_vehicles:
        status = get_vehicle_status(vid)
        if status and status.get("status") in [3, 4]:
            active_vehicles.append(vid)
    return active_vehicles

    
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

# --- Funktion um den Status der Fahrzeuge zu loggen ---
last_vehicle_status = {}  # vehicle_id -> status

def log_vehicle_statuses(active_title: str = ""):
    """
    Loggt den Status aller Fahrzeuge in eine Textdatei.
    Nur Änderungen zum letzten bekannten Status werden protokolliert.
    :param active_title: Titel des aktuellen aktiven Einsatzes, leer wenn keiner aktiv.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines_to_write = []

    for vid, vname in translations.get("vehicles", {}).items():
        status_info = get_vehicle_status(vid)
        if not status_info:
            continue

        current_status = status_info.get("status")
        last_status = last_vehicle_status.get(vid)

        # Nur loggen, wenn Status neu ist oder sich geändert hat
        if last_status != current_status:
            last_vehicle_status[vid] = current_status
            if active_title == "":
                line = f"{timestamp} | {vname.ljust(4)} | {current_status}"
            else:
                line = f"{timestamp} | {vname.ljust(4)} | {current_status} | Einsatz: {active_title}"
            lines_to_write.append(line)

    # Anhängen in die Logdatei
    if lines_to_write:
        with open("vehicle_status.log", "a", encoding="utf-8") as f:
            f.write("\n".join(lines_to_write) + "\n")



# --- Einsatzspeicherlogik ---
def process_einsaetze():
    """
    Aktualisiert alle Einsätze, schreibt sie in die JSON-Datei und gibt
    den Titel des aktuell offenen Einsatzes zurück (leer, wenn keiner offen).
    """
    try:
        active_mission_title = ""  # Default: kein aktiver Einsatz
        # Alte Daten laden, falls vorhanden
        try:
            with open(EINSATZDATEN_FILE, "r", encoding="utf-8") as f:
                einsatz_list = json.load(f)
        except FileNotFoundError:
            einsatz_list = []

        # Index für schnellen Zugriff nach Einsatz-ID
        einsatz_index = {e["id"]: e for e in einsatz_list}

        for einsatz in fetch_einsaetze():
            title = einsatz.get("title", "").lower()
            text = einsatz.get("text", "").lower()
            if any(word in title or word in text for word in FILTER_WORDS):
                continue
            einsatz_id = einsatz["id"]

            # Datum und Uhrzeit
            ts = einsatz.get("date", 0)
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")

            # vehicle_reallife nur bei aktiven Einsätzen prüfen
            if not einsatz.get("closed", True):
                active_vehicles = [int(vid) for vid in get_active_vehicles()]
                active_mission_title = sanitize_stichwort(einsatz.get("title", ""))
            else:
                active_vehicles = []

            if einsatz_id in einsatz_index:
                existing = einsatz_index[einsatz_id]
    
                # Alle Attribute außer vehicle_reallife aktualisieren
                existing["foreign_id"] = einsatz.get("foreign_id", "")
                existing["date"] = date
                existing["time"] = time_str
                existing["title"] = sanitize_stichwort(einsatz.get("title", ""))
                existing["address"] = sanitize_address(einsatz.get("address", ""))
                existing["report"] = einsatz.get("report", "")
                existing["group"] = einsatz.get("group", [])
                existing["vehicle_planned"] = einsatz.get("vehicle", [])
                existing["text"] = einsatz.get("text", "")
                existing["closed"] = einsatz.get("closed", True)

                # vehicle_reallife additiv aktualisieren
                existing_vehicles = set(existing.get("vehicle_reallife", []))
                existing["vehicle_reallife"] = list(existing_vehicles.union(active_vehicles))

            else:
                # Neuer Einsatz
                einsatz_dict = {
                    "id": einsatz_id,
                    "foreign_id": einsatz.get("foreign_id", ""),
                    "date": date,
                    "time": time_str,
                    "title": sanitize_stichwort(einsatz.get("title", "")),
                    "address": sanitize_address(einsatz.get("address", "")),
                    "report": einsatz.get("report", ""),
                    "group": einsatz.get("group", []),
                    "vehicle_planned": einsatz.get("vehicle", []),
                    "text": einsatz.get("text", ""),
                    "closed": einsatz.get("closed", True),
                    "vehicle_reallife": active_vehicles,
                }
                einsatz_list.append(einsatz_dict)
                einsatz_index[einsatz_id] = einsatz_dict

        # Sortiere nach Datum + Zeit, neueste zuerst
        einsatz_list.sort(
            key=lambda x: (x["date"], x["time"]),
            reverse=True  # neueste oben
        )

        # --- In JSON-Datei schreiben ---
        with open(EINSATZDATEN_FILE, "w", encoding="utf-8") as f:
            json.dump(einsatz_list, f, ensure_ascii=False, indent=4)

        print(f"{len(einsatz_list)} Einsätze gespeichert/aktualisiert.")
        return active_mission_title

    except Exception as e:
        print(f"Fehler in process_einsaetze: {e}")
    
# --- HMTL Erstellung ---   
def generate_html_page():
    import json
    from html import escape
    from datetime import datetime

    # --- JSON Dateien laden ---
    with open(EINSATZDATEN_FILE, "r", encoding="utf-8") as f:
        einsatz_list = json.load(f)

    with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
        translations = json.load(f)

    group_trans = translations.get("groups", {})
    vehicle_trans = translations.get("vehicles", {})

    # --- HTML Header ---
    html = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Einsätze</title>
<style>
body {
    font-family: Montserrat, sans-serif;
    background-color: #2E2E2E;
    color: #ffffff;
}
h1 {
    color: #E94232;
}
table {
    border-collapse: collapse;
    width: 100%;
    background-color: #3E3E3E;
}
th, td {
    border: 1px solid #222;
    padding: 8px;
    text-align: left;
    color: #ffffff;
}
th {
    background-color: #555555;
}
tr:nth-child(even) {
    background-color: #4E4E4E;
}
.live-indicator {
        display: inline-block;
        width: 12px;
        height: 12px;
        margin-right: 5px;
        border-radius: 50%;
        background-color: #E94232;
        animation: pulse 1.5s infinite;
        vertical-align: middle;
    }
    @keyframes pulse {
        0% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.5); opacity: 0.6; }
        100% { transform: scale(1); opacity: 1; }
    }
</style>
</head>
<body>
<h1>Einsätze</h1>
<table>
<tr>
<th>Datum</th>
<th>Uhrzeit</th>
<th>Stichwort</th>
<th>Ort</th>
<th>Bericht</th>
<th>Gruppe</th>
<th>Fahrzeuge</th>
</tr>
"""

    # --- Tabelle befüllen ---
    for einsatz in einsatz_list:
        # Datum umformatieren
        datum_raw = einsatz.get("date", "")
        try:
            datum_obj = datetime.strptime(datum_raw, "%Y-%m-%d")
            datum = datum_obj.strftime("%d.%m.%Y")
        except ValueError:
            datum = datum_raw

        uhrzeit = escape(einsatz.get("time", ""))
        stichwort = escape(einsatz.get("title", ""))
        live_html = '<span class="live-indicator">LIVE</span>' if not einsatz["closed"] else ''
        ort = escape(einsatz.get("address", ""))
        bericht = escape(einsatz.get("report", ""))

        # Gruppen auflösen
        gruppen_ids = einsatz.get("group", [])
        gruppen_namen = [group_trans.get(str(gid), str(gid)) for gid in gruppen_ids]
        gruppen_str = ", ".join(gruppen_namen)

        # Fahrzeuge auflösen
        fahrzeug_ids = einsatz.get("vehicle_reallife", [])
        fahrzeuge_namen = [vehicle_trans.get(str(vid), str(vid)) for vid in fahrzeug_ids]
        fahrzeuge_str = ", ".join(fahrzeuge_namen)

        html += f"<tr><td>{datum}</td><td>{uhrzeit}</td><td>{stichwort} {live_html}</td><td>{ort}</td><td>{bericht}</td><td>{gruppen_str}</td><td>{fahrzeuge_str}</td></tr>\n"

    html += f"""
</table>
</body>
</html>
"""

    # --- Datei speichern ---
    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML-Seite '{OUTPUT_HTML_FILE}' erfolgreich erstellt.")
    
    
 # --- Github HTML Push ---   
def push_file_to_github():
    with open(OUTPUT_HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Datei muss base64-encodiert hochgeladen werden
    encoded_content = base64.b64encode(content.encode()).decode()

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{OUTPUT_HTML_FILE}"

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    # Prüfen, ob die Datei schon existiert → SHA brauchen wir für Update
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        sha = resp.json()["sha"]
    else:
        sha = None

    data = {
        "message": f"Automated Update einsatz_website.html ({datetime.now().isoformat(timespec='seconds')})",
        "content": encoded_content,
        "branch": BRANCH,
    }
    if sha:
        data["sha"] = sha  # nötig, wenn Datei schon existiert

    r = requests.put(url, headers=headers, json=data)

    if r.status_code in [200, 201]:
        print("✅ index.html erfolgreich zu GitHub gepusht.")
    else:
        print(f"❌ Fehler beim Push: {r.status_code} - {r.text}")
        
def has_file_changed():
    global last_hash
    new_hash = calculate_file_hash(OUTPUT_HTML_FILE)
    
    print(f"DEBUG: Neuer Hash: {new_hash}")
    print(f"DEBUG: Letzter Hash: {last_hash}")

    if last_hash is None:
        # erster Durchlauf -> nur merken
        last_hash = new_hash
        return True  

    if new_hash == last_hash:
        return False  # keine Änderung
    else:
        last_hash = new_hash
        return True
    
def calculate_file_hash(file_path: str) -> str:
    """Berechnet den SHA256-Hash einer Datei."""
    hash_sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    except FileNotFoundError:
        return ""  # falls die Datei noch nicht existiert

# --- Hauptschleife ---
while True:
    active_mission_title = process_einsaetze()
    log_vehicle_statuses(active_mission_title)
    generate_html_page()
    
    if has_file_changed() == True:
        push_file_to_github()
    
    time.sleep(120)

