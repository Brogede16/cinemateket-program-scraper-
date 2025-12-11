import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

# ---------------- Opsætning ----------------
BASE_URL = "https://www.dfi.dk"
START_URL = f"{BASE_URL}/cinemateket/biograf/alle-film"

# Vi faker en rigtig browser for at undgå blokering
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7'
}

app = Flask(__name__, static_folder=".", static_url_path="")

# ---------------- Hjælpefunktioner ----------------

def log(msg):
    """Skriver til Renders log"""
    print(f"[LOG] {msg}", flush=True)

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return BeautifulSoup(r.content, "lxml")
    except Exception as e:
        log(f"Fejl ved {url}: {e}")
        return None

def parse_danish_date(date_str, time_str):
    """Omdanner 'Fre 12. dec' + '16:00' til datetime objekt"""
    try:
        # Map danske måneder
        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'maj': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'okt': 10, 'nov': 11, 'dec': 12
        }
        
        # Regex: Find "12" og "dec"
        match = re.search(r"(\d+)\.?\s+([a-zæøå]+)", date_str.lower())
        if not match: return None
        
        day = int(match.group(1))
        mon_str = match.group(2)[:3] # Tag kun de første 3 bogstaver
        month = months.get(mon_str)
        
        if not month: return None
        
        # Tid: 16:00
        clean_time = re.sub(r"[^0-9:]", "", time_str.replace('.', ':'))
        hour, minute = map(int, clean_time.split(':'))
        
        # Årstal logik
        now = datetime.now()
        year = now.year
        if now.month >= 11 and month <= 3: year += 1 # Nytårsskifte
        
        return datetime(year, month, day, hour, minute)
    except:
        return None

def get_all_film_links():
    """Henter ALLE links der ligner film fra oversigten."""
    film_links = set()
    
    # Vi scanner de første 5 sider. DFI viser ca 24 film pr side.
    # 5 sider = ca 120 film frem i tiden. Det burde dække de næste 4-7 dage rigeligt.
    for page in range(5):
        url = f"{START_URL}?page={page}"
        log(f"Scanner side {page}: {url}")
        
        soup = get_soup(url)
        if not soup: break
        
        # FIND ALLE LINKS (Støvsuger-metoden)
        # Vi filtrerer i Python i stedet for CSS selector for at være sikre
        all_anchors = soup.find_all("a", href=True)
        count = 0
        
        for a in all_anchors:
            href = a['href']
            # Kriterie: Skal indeholde /film/ og må ikke være admin/db støj
            if "/film/" in href and "viden-om-film" not in href:
                full_url = urljoin(BASE_URL, href)
                film_links.add(full_url)
                count += 1
        
        log(f"  -> Fandt {count} potentielle film på side {page}")
        
    return list(film_links)

def scrape_film_details(url, start_date_obj, end_date_obj):
    """Går ind på en film og henter detaljer + KUN relevante tider."""
    soup = get_soup(url)
    if not soup: return None
    
    # 1. Hent tider KUN fra billet-listen
    # Vi ignorerer alt andet tekst på siden for at undgå åbningstider
    valid_screenings = []
    rows = soup.select(".ct-cinema-movie-showings__list-item")
    
    if not rows:
        # Fallback: Hvis der slet ingen liste er, er det måske et special-event?
        # Vi leder efter knapper med "billet" i teksten
        pass # (Implementer evt senere, men listen dækker 99%)

    for row in rows:
        try:
            d_el = row.select_one(".ct-cinema-movie-showings__date")
            t_el = row.select_one(".ct-cinema-movie-showings__time")
            btn = row.select_one("a.btn")
            
            if d_el and t_el:
                dt = parse_danish_date(d_el.get_text(strip=True), t_el.get_text(strip=True))
                
                if dt:
                    # TJEK DATO FILTER HER
                    if start_date_obj <= dt <= end_date_obj:
                        status = "Udsolgt" if "udsolgt" in row.get_text().lower() else "Ledig"
                        valid_screenings.append({
                            "sort_key": dt.timestamp(),
                            "display": dt.strftime("%d/%m kl. %H:%M"),
                            "link": btn['href'] if btn else "#",
                            "status": status
                        })
        except:
            continue
            
    # HVIS INGEN VISNINGER I PERIODEN: STOP HER (Spar tid)
    if not valid_screenings:
        return None
        
    # 2. Hent Metadata (Titel, Billede, Beskrivelse)
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Ukendt Titel"
    
    # Billede
    img = soup.select_one(".media-element-container img") or soup.select_one("article img")
    img_url = urljoin(BASE_URL, img['src']) if img else None
    
    # Beskrivelse (Split credits fra)
    body = soup.select_one(".field-name-body .field-item") or soup.select_one("article .content")
    full_text = body.get_text("\n", strip=True) if body else ""
    
    lines = full_text.split('\n')
    desc_lines = []
    credit_lines = []
    is_credits = False
    
    markers = ["Instruktør:", "Medvirkende:", "Original titel:", "USA,", "Danmark,", "Længde:", "Tilladt for"]
    
    for l in lines:
        l = l.strip()
        if not l or l in ["Læs mere", "Bestil billet", "Se mere"]: continue
        
        if not is_credits:
            if any(l.startswith(m) for m in markers): is_credits = True
            elif re.search(r"^[A-ZÆØÅ][a-zæøå]+,\s*(19|20)\d{2}", l): is_credits = True
        
        if is_credits: credit_lines.append(l)
        else: desc_lines.append(l)
            
    # Serie Info
    series_name = "Øvrige Film & Events"
    s_link = soup.select_one(".field-name-field-cinemateket-series a")
    if s_link:
        series_name = s_link.get_text(strip=True)

    return {
        "title": title,
        "desc": "\n".join(desc_lines),
        "credits": ", ".join(credit_lines),
        "image": img_url,
        "screenings": sorted(valid_screenings, key=lambda x: x['sort_key']),
        "series": series_name
    }

# ---------------- Routes ----------------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/program")
def program():
    d_from = request.args.get("from")
    d_to = request.args.get("to")
    
    if not d_from or not d_to:
        return jsonify({"error": "Mangler datoer"}), 400
        
    # Konverter string datoer til datetime
    try:
        start_dt = datetime.strptime(d_from, "%Y-%m-%d")
        # Sæt slut-tid til slutningen af dagen (23:59:59)
        end_dt = datetime.strptime(d_to, "%Y-%m-%d").replace(hour=23, minute=59)
    except:
        return jsonify({"error": "Ugyldigt datoformat"}), 400

    log(f"STARTER SCRAPING: {start_dt} til {end_dt}")
    
    # 1. Hent alle potentielle links
    links = get_all_film_links()
    log(f"Fandt totalt {len(links)} unikke links at tjekke.")
    
    # 2. Besøg hver og filtrer
    results = {}
    
    for i, link in enumerate(links):
        # Log status hver 5. film så du kan se fremskridt
        if i % 5 == 0: log(f"Behandler {i}/{len(links)}...")
        
        data = scrape_film_details(link, start_dt, end_dt)
        
        if data:
            s_name = data['series']
            if s_name not in results: results[s_name] = []
            results[s_name].append(data)
            
    # 3. Formatér output
    final_output = []
    for name, items in results.items():
        # Sorter film internt efter første visning
        items.sort(key=lambda x: x['screenings'][0]['sort_key'])
        final_output.append({"name": name, "items": items})
        
    # Sorter serier efter første film i serien
    if final_output:
        final_output.sort(key=lambda s: s['items'][0]['screenings'][0]['sort_key'])
        
    log(f"Færdig! Fandt {sum(len(s['items']) for s in final_output)} film.")
    return jsonify({"series": final_output})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
