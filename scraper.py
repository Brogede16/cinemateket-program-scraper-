import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
from urllib.parse import urljoin
import time

# Base URL
BASE_URL = "https://www.dfi.dk"

# Dansk dato-mapping
DANISH_MONTHS = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, 
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12
}

def get_soup(url):
    """Henter HTML fra en URL sikkert."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.content, "lxml")
    except Exception as e:
        print(f"⚠️ Fejl ved hentning af {url}: {e}")
        return None

def parse_danish_date_string(date_str, time_str):
    """
    Omdanner 'Søndag 4. januar' og '16:15' til et datetime objekt.
    Håndterer årsskifte (hvis vi er i dec men booker til jan).
    """
    try:
        # Regex for at finde dag og måned tekst
        match = re.search(r"(\d+)\.?\s+([a-zæøå]+)", date_str.lower())
        if not match:
            return None
        
        day = int(match.group(1))
        month_str = match.group(2)
        
        # Find månedsnummer
        month = DANISH_MONTHS.get(month_str, 0)
        if month == 0:
            month = DANISH_MONTHS.get(month_str[:3], 1) # Prøv forkortelse
        
        # Tidspunkt
        clean_time = time_str.replace(".", ":").strip()
        hour, minute = map(int, clean_time.split(":"))

        # Årstal logik
        now = datetime.now()
        year = now.year
        
        # Hvis vi er i slutningen af året (okt-dec) og ser en dato i starten (jan-mar), er det næste år
        if now.month >= 10 and month <= 3:
            year += 1
            
        return datetime(year, month, day, hour, minute)
    except Exception:
        return None

def get_all_film_links(progress_callback=None):
    """
    Gennemgår alle sider på 'Alle film' oversigten (paginering).
    """
    links = {}
    page = 0
    keep_going = True
    
    print("🔄 Starter indeksering af alle film...")
    
    while keep_going:
        # URL til oversigtssiden med sidetal
        url = f"{BASE_URL}/cinemateket/biograf/alle-film?page={page}"
        soup = get_soup(url)
        
        if not soup:
            break
            
        found_on_this_page = 0
        
        # Find alle film-links på denne side
        movie_links = soup.select("a[href^='/cinemateket/biograf/alle-film/film/']")
        
        if not movie_links:
            keep_going = False
            break
            
        for a in movie_links:
            href = a['href']
            full_url = urljoin(BASE_URL, href)
            title = a.get_text(strip=True)
            
            if full_url not in links and title:
                links[full_url] = title
                found_on_this_page += 1
        
        # Feedback til konsollen
        print(f"   Side {page}: Fandt {found_on_this_page} film.")
        
        # Opdater progress bar hvis den findes
        if progress_callback:
            progress_callback.progress(0.1, text=f"Scanner oversigter... Side {page} fundet.")

        if found_on_this_page == 0:
            keep_going = False
        else:
            page += 1
            # Pause for ikke at overbelaste DFI
            time.sleep(0.2)
            
    return links

def scrape_series_details(url):
    """Henter info om en serie (billede og beskrivelse)."""
    soup = get_soup(url)
    if not soup:
        return {"description": "", "image_url": None}

    desc_tag = soup.select_one(".field-name-body .field-item")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    img_tag = soup.select_one(".media-element-container img")
    if not img_tag:
        img_tag = soup.select_one(".img-responsive")
    image_url = img_tag['src'] if img_tag else None

    return {
        "description": description,
        "image_url": image_url
    }

def scrape_film_details(url, start_date, end_date):
    """
    Scraper en enkelt film for titel, billede, serie og visningstider.
    """
    soup = get_soup(url)
    if not soup:
        return None

    # 1. Metadata
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "Ukendt titel"
    
    desc_tag = soup.select_one(".field-name-body .field-item")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    img_tag = soup.select_one(".media-element-container img")
    image_url = img_tag['src'] if img_tag else None

    # 2. Serie info
    series_title = None
    series_url = None
    series_link = soup.select_one(".field-name-field-cinemateket-series .field-item a")
    if series_link:
        series_title = series_link.get_text(strip=True)
        series_url = urljoin(BASE_URL, series_link['href'])

    # 3. Er det et Event?
    is_event = False
    # Tjek labels
    labels = soup.select(".label-item")
    for l in labels:
        if "event" in l.get_text(strip=True).lower():
            is_event = True
    # Tjek URL struktur
    if "/event/" in url:
        is_event = True

    # 4. Visninger (Screenings)
    screenings = []
    rows = soup.select(".ct-cinema-movie-showings__list-item")
    
    for row in rows:
        try:
            date_el = row.select_one(".ct-cinema-movie-showings__date")
            time_el = row.select_one(".ct-cinema-movie-showings__time")
            btn_el = row.select_one("a.btn") 
            
            if date_el and time_el and btn_el:
                date_txt = date_el.get_text(strip=True)
                time_txt = time_el.get_text(strip=True)
                link = btn_el['href']
                
                dt = parse_danish_date_string(date_txt, time_txt)
                
                if dt:
                    # Tjek om datoen er inden for brugerens valg
                    if start_date <= dt <= end_date:
                        screenings.append({
                            "datetime": dt,
                            "display_date": dt.strftime("%d-%m-%Y kl. %H:%M"),
                            "link": link,
                            "is_sold_out": "udsolgt" in btn_el.get_text().lower()
                        })
        except Exception:
            continue

    # Returner kun data, hvis filmen vises i perioden
    if not screenings:
        return None

    return {
        "title": title,
        "description": description,
        "image_url": image_url,
        "url": url,
        "is_event": is_event,
        "series_title": series_title,
        "series_url": series_url,
        "screenings": screenings
    }

def get_program_data(start_date, end_date, progress_callback=None):
    """
    Hovedfunktion:
    1. Henter alle links
    2. Looper igennem dem og scraper detaljer
    3. Grupperer i serier
    """
    # Trin 1: Hent links (med paginering)
    film_links_map = get_all_film_links(progress_callback)
    total_films = len(film_links_map)
    
    series_map = {} 
    standalone_films = []
    
    # Trin 2: Scrape hver film
    film_items = list(film_links_map.items())
    
    for i, (url, title) in enumerate(film_items):
        # Opdater UI progress bar
        if progress_callback:
            percent = 0.1 + (0.9 * ((i + 1) / total_films))
            # Sikrer at vi ikke går over 1.0
            percent = min(percent, 1.0)
            progress_callback.progress(percent, text=f"Scanner {i+1}/{total_films}: {title[:30]}...")
        
        data = scrape_film_details(url, start_date, end_date)
        
        if data:
            s_url = data.get('series_url')
            if s_url:
                # Tilføj til serie
                if s_url not in series_map:
                    s_info = scrape_series_details(s_url)
                    series_map[s_url] = {
                        "title": data['series_title'],
                        "url": s_url,
                        "description": s_info['description'],
                        "image_url": s_info['image_url'],
                        "films": []
                    }
                series_map[s_url]['films'].append(data)
            else:
                # Tilføj til enkeltstående
                standalone_films.append(data)

    # Trin 3: Sortering
    final_series = sorted(list(series_map.values()), key=lambda x: x['title'])
    for s in final_series:
        s['films'].sort(key=lambda x: x['title'])
        
    standalone_films.sort(key=lambda x: x['title'])

    return {
        "series": final_series,
        "films": standalone_films
    }
