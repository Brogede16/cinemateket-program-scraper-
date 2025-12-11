import os
import re
import sys
import time
import json
from datetime import datetime, date
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

# ---------------- Konfiguration ----------------
BASE = "https://www.dfi.dk"
START_URL = f"{BASE}/cinemateket/biograf/alle-film"

# Vi øger timeout, da DFI kan være langsom
TIMEOUT = 30 
UA = "Mozilla/5.0 (compatible; DFIPrintScraper/4.0)"

app = Flask(__name__, static_folder=".", static_url_path="")

# Opsætning af requests session
session = requests.Session()
session.headers.update({"User-Agent": UA})

# Danske måneder til parsing
DANISH_MONTHS = {
    "jan": 1, "januar": 1, "feb": 2, "februar": 2, "mar": 3, "marts": 3, 
    "apr": 4, "april": 4, "maj": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7, 
    "aug": 8, "august": 8, "sep": 9, "september": 9, "okt": 10, "oktober": 10, 
    "nov": 11, "november": 11, "dec": 12, "december": 12
}

# ---------------- Hjælpefunktioner ----------------

def log(msg):
    print(f"[SCRAPER] {msg}", flush=True)

def get_soup(url):
    """Henter URL og returnerer BeautifulSoup objekt"""
    try:
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.content, "lxml")
    except Exception as e:
        log(f"Fejl ved {url}: {e}")
        return None

def parse_dfi_date(date_text, time_text):
    """
    Parser datoer specifikt fra billet-listen.
    Eks: date_text="Fre 12. dec", time_text="16:15"
    """
    try:
        # Find dag og måned (Ignorer ugedag)
        match = re.search(r"(\d+)\.?\s+([a-zæøå]+)", date_text.lower())
        if not match: return None
        
        day = int(match.group(1))
        month_str = match.group(2)
        month = DANISH_MONTHS.get(month_str[:3], 0)
        
        if month == 0: return None

        # Rens tid (fjern 'kl.' og punktummer)
        clean_time = re.sub(r"[^0-9:]", "", time_text.replace('.', ':'))
        if ":" not in clean_time: return None
        
        hour, minute = map(int, clean_time.split(':'))

        # Årstal-gætning (håndterer årsskifte)
        now = datetime.now()
        year = now.year
        
        # Hvis vi er i Nov/Dec og dato er Jan/Feb/Mar -> Næste år
        if now.month >= 11 and month <= 3:
            year += 1
        
        return datetime(year, month, day, hour, minute)
    except:
        return None

def split_description_and_credits(soup):
    """
    Henter beskrivelse KUN fra content-feltet og splitter teknik fra.
    Dette forhindrer at menuer og footere kommer med.
    """
    # CSS Selector specifik for DFI artikler
    body = soup.select_one(".field-name-body .field-item") or soup.select_one("article .content")
    
    if not body: return "", ""
    
    # Hent tekst med linjeskift
    full_text = body.get_text("\n", strip=True)
    lines = full_text.split('\n')
    
    desc_lines = []
    credit_lines = []
    is_credits = False
    
    # Markører der starter teknik-sektionen
    split_markers = [
        "Instruktør:", "Medvirkende:", "Original titel:", "USA,", "Danmark,", 
        "Frankrig,", "Storbritannien,", "Sverige,", "Stemmer:", "Længde:", "Tilladt for", "Manuskript:"
    ]
    
    blacklist = ["Læs mere", "Bestil billet", "Køb billetter", "Se mere"]
    
    for line in lines:
        l = line.strip()
        if not l: continue
        if any(b in l for b in blacklist): continue
        
        # Detektion af credits sektion
        if not is_credits:
            if any(l.startswith(m) for m in split_markers):
                is_credits = True
            # Regex for "Land, Årstal" (eks: "USA, 1950")
            elif re.search(r"^[A-ZÆØÅ][a-zæøå]+,\s*(19|20)\d{2}", l):
                is_credits = True
                
        if is_credits:
            credit_lines.append(l)
        else:
            desc_lines.append(l)
            
    return "\n".join(desc_lines), ", ".join(credit_lines)

def extract_screenings(soup, start_date, end_date):
    """
    Kernefunktionen: Finder visninger KUN i billet-listen.
    Ignorerer åbningstider og footer-tekst.
    """
    screenings = []
    
    # 1. Den primære metode: DFI's specifikke liste-container
    # Vi leder efter .ct-cinema-movie-showings__list-item
    rows = soup.select(".ct-cinema-movie-showings__list-item")
    
    for row in rows:
        try:
            d_el = row.select_one(".ct-cinema-movie-showings__date")
            t_el = row.select_one(".ct-cinema-movie-showings__time")
            btn = row.select_one("a.btn")
            
            if d_el and t_el:
                dt = parse_dfi_date(d_el.get_text(strip=True), t_el.get_text(strip=True))
                
                # Tjek om datoen er gyldig og inden for range
                if dt:
                    dt_date = dt.date()
                    start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
                    end_d = datetime.strptime(end_date, "%Y-%m-%d").date()
                    
                    if start_d <= dt_date <= end_d:
                        status = "Ledig"
                        if "udsolgt" in row.get_text().lower(): status = "Udsolgt"
                        
                        screenings.append({
                            "iso_dt": dt.isoformat(),
                            "display": dt.strftime("%d/%m kl. %H:%M"),
                            "sort_key": dt.timestamp(),
                            "link": btn['href'] if btn else "#",
                            "status": status
                        })
        except Exception:
            continue
            
    return sorted(screenings, key=lambda x: x['sort_key'])

def fetch_details_for_url(url, start_date, end_date):
    """Går ind på filmsiden og henter alt."""
    soup = get_soup(url)
    if not soup: return None
    
    # 1. Tjek visninger først (Optimering: Hvis ingen visninger, skip resten)
    screenings = extract_screenings(soup, start_date, end_date)
    if not screenings:
        return None
        
    # 2. Titel
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else "Ukendt Titel"
    
    # 3. Tekst (Beskrivelse vs Credits)
    desc, credits = split_description_and_credits(soup)
    
    # 4. Billede
    img = soup.select_one(".media-element-container img") or soup.select_one("article img")
    img_url = urljoin(BASE, img['src']) if img else None
    
    # 5. Serie info
    series_title = "Øvrige Film & Events"
    s_link = soup.select_one(".field-name-field-cinemateket-series a")
    if s_link:
        series_title = s_link.get_text(strip=True)

    return {
        "title": title,
        "description": desc,
        "credits": credits,
        "image": img_url,
        "screenings": screenings,
        "series": series_title,
        "url": url
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
        
    log(f"Starter scraping fra {d_from} til {d_to}")
    
    all_film_links = set()
    
    # 1. Scan oversigten (Alle film)
    # Vi scanner 8 sider for at være sikre på at fange film der måske ligger lidt nede
    # men har visninger snart.
    for page in range(8):
        url = f"{START_URL}?page={page}"
        soup = get_soup(url)
        if not soup: break
        
        links = soup.select("a[href^='/cinemateket/biograf/alle-film/film/']")
        if not links: break # Stop hvis siden er tom
        
        for a in links:
            all_film_links.add(urljoin(BASE, a['href']))
            
    log(f"Fandt {len(all_film_links)} unikke film-links. Tjekker detaljer...")
    
    # 2. Besøg hver film
    series_map = {}
    
    for link in list(all_film_links):
        data = fetch_details_for_url(link, d_from, d_to)
        
        if data:
            s_name = data['series']
            if s_name not in series_map:
                series_map[s_name] = []
            series_map[s_name].append(data)
            
    # 3. Formatér til JSON output
    output_series = []
    
    # Sorter serier
    for name, films in series_map.items():
        # Sorter film internt efter dato
        films.sort(key=lambda x: x['screenings'][0]['sort_key'])
        
        output_series.append({
            "name": name,
            "items": films
        })
        
    # Sorter listen af serier efter datoen på den første film i serien
    output_series.sort(key=lambda s: s['items'][0]['screenings'][0]['sort_key'])
    
    return jsonify({"series": output_series})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
