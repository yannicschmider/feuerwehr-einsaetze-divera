import requests
import datetime
import os

ACCESS_KEY = os.environ.get("DIVERA_API_KEY")
API_URL = f"https://app.divera247.com/api/v2/alarms?accesskey={ACCESS_KEY}"

def fetch_einsaetze():
    response = requests.get(API_URL)
    response.raise_for_status()
    data = response.json()
    return data["data"]["items"].values()

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
    <tr><th>Datum</th><th>Uhrzeit</th><th>Stichwort</th><th>Ort</th></tr>
"""

    for einsatz in einsaetze:
        ts = datetime.datetime.fromtimestamp(int(einsatz["date"]))
        if ts.year == datetime.datetime.now().year:
            html += f"<tr><td>{ts.strftime('%d.%m.%Y')}</td><td>{ts.strftime('%H:%M')}</td><td>{einsatz.get('title', '')}</td><td>{einsatz.get('address', '')}</td></tr>"

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
