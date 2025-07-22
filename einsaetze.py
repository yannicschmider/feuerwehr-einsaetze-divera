import requests
import datetime
import os
import re

API_URL = "https://app.divera247.com/api/v2/operations"
API_KEY = os.environ.get("DIVERA_API_KEY")

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
}

def sanitize_address(address: str) -> str:
    if not address:
        return ""

    # 1. Hausnummern entfernen (inkl. Anhänge wie "7 A" oder "80A")
    address = re.sub(r"\s\d+[a-zA-Z\-\/]*", "", address)

    # 2. Doppelte Ortsnamen am Ende entfernen (z. B. "Hausach Hausach-Ost")
    parts = address.strip().split()
    if len(parts) >= 2 and parts[-1].startswith(parts[-2]):
        address = " ".join(parts[:-1] + [parts[-1]])

    return address.strip()

def fetch_einsaetze():
    response = requests.get(API_URL, headers=headers)
    response.raise_for_status()
    data = response.json()
    return data["data"]

def generate_html(einsaetze):
    html = f"""<html>
<head>
    <meta charset="UTF-8">
    <title>Einsätze</title>
    <meta http-equiv="refresh" content="300">
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
    <tr><th>Datum</th><th>Uhrzeit</th><th>Stichwort</th><th>Ort</th></tr>
"""

    for e in einsaetze:
        ts = datetime.datetime.fromtimestamp(int(e["timestamp"]))
        if ts.year == datetime.datetime.now().year:
            raw_address = e.get("address", "")
            safe_address = sanitize_address(raw_address)
            html += f"<tr><td>{ts.strftime('%d.%m.%Y')}</td><td>{ts.strftime('%H:%M')}</td><td>{e.get('keyword', '')}</td><td>{safe_address}</td></tr>"

    html += """
</table>
</body>
</html>
"""
    with open("einsaetze.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    einsaetze = fetch_einsaetze()
    generate_html(einsaetze)
