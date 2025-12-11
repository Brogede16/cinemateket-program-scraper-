import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
from urllib.parse import urljoin
import time

# Base URL for DFI
BASE_URL = "https://www.dfi.dk"

# Danish month map for parsing dates
DANISH_MONTHS = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, 
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12
}

def parse_danish_date_string(date_str, time_str):
    """
    Converts strings like '4. januar' and '16:15' into a datetime object.
    Assumes current year or next year depending on month.
    """
    try:
        # Clean string "Søndag 4. januar" -> "4. januar"
        clean_date = re.search(r"(\d+)\.?\s+([a-zæøå]+)", date_str.lower())
        if not clean_date:
            return None
        
        day = int(clean_date.group(1))
        month_name = clean_date.group(2)
        month = DANISH_MONTHS.get(month_name[:3], 1) # Try to match first 3 chars if full name fails
        
        # Parse time
        clean_time = time_str.replace(".", ":").strip()
        hour, minute = map(int, clean_time.split(":"))

        now = datetime.now()
        year = now.year
        
        # Logic: If scraping in Dec for a Jan show, it's next year.
        # If scraping in Jan for a Dec show, it's last year (unlikely for upcoming tickets).
        if now.month == 12 and month == 1:
            year += 1
        
        dt = datetime(year, month, day, hour, minute)
        return dt
    except Exception as e:
        # print(f"Date parse error: {e} | Input: {date_str} {time_str}")
        return None

def get_soup(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return BeautifulSoup(r.content, "lxml")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def get_all_film_links():
    """
    Fetches ALL film URLs by iterating through pagination pages.
    """
    links = {}
    page = 0
    has_more = True
    
    print("Starter indsamling af film-links...")
    
    while has_more:
        # DFI pagination structure: ?page=0, ?page=1, etc.
        overview_url = f"{BASE_URL}/cinemateket/biograf/alle-film?page={page}"
        soup = get_soup(overview_url)
        
        if not soup:
            break
            
        found_on_page = 0
        # Find film links
        for a in soup.select("a[href^='/cinemateket/biograf/alle-film/film/']"):
            href = a['href']
            full_url = urljoin(BASE_URL, href)
            title = a.get_text(strip=True)
            if full_url not in links:
                links[full_url] = title
                found_on_page += 1
        
        # Check if we should continue (if no films found, we reached the end)
        if found_on_page == 0:
            has_more = False
        else:
            print(f"Side {page} færdig: Fandt {found_on_page} film.")
            page += 1
            # Be polite to the server
            time.sleep(0.5)
            
    return links

def scrape_film_details(url, start_date, end_date):
    """
    Scrapes a specific film page for metadata and screenings within the date range.
    """
    soup = get_soup(url)
    if not soup:
        return None

    # 1. Basic Metadata
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "Ukendt titel"
    
    desc_tag = soup.select_one(".field-name-body .field-item")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    img_tag = soup.select_one(".media-element-container img")
    image_url = img_tag['src'] if img_tag else None
    
    # 2. Series info
    series_title = None
    series_url = None
    series_link = soup.select_one(".field-name-field-cinemateket-series .field-item a")
    if series_link:
        series_title = series_link.get_text(strip=True)
        series_url = urljoin(BASE_URL, series_link['href'])

    # 3. Screenings
    screenings = []
    
    # Selecting rows in the ticket section
    ticket_rows = soup.select(".ct-cinema-movie-showings .ct-cinema-movie-showings__list-item")
    
    for row in ticket_rows:
        try:
            date_div = row.select_one(".ct-cinema-movie-showings__date")
            time_div = row.select_one(".ct-cinema-movie-showings__time")
            link_tag = row.select_one("a.btn-primary") # Ticket link
            
            if date_div and time_div and link_tag:
                date_text = date_div.get_text(strip=True)
                time_text = time_div.get_text(strip=True)
                buy_link = link_tag['href']
                
                dt = parse_danish_date_string(date_text, time_text)
                
                if dt:
                    if start_date <= dt <= end_date:
                        screenings.append({
                            "datetime": dt,
                            "display_date": dt.strftime("%d-%m-%Y kl. %H:%M"),
                            "link": buy_link
                        })
        except Exception:
            continue

    if not screenings:
        return None

    return {
        "title": title,
        "description": description,
        "image_url": image_url,
        "url": url,
        "series_title": series_title,
        "series_url": series_url,
        "screenings": screenings
    }

def scrape_series_details(url):
    """
    Fetches description and image for a series page.
    """
    soup = get_soup(url)
    if not soup:
        return {"description": "", "image_url": None}

    desc_tag = soup.select_one(".field-name-body .field-item")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    img_tag = soup.select_one(".media-element-container img")
    image_url = img_tag['src'] if img_tag else None

    return {
        "description": description,
        "image_url": image_url
    }

def get_program_data(start_date, end_date, progress_callback=None):
    """
    Main orchestrator.
    progress_callback: A streamlit progress bar object (optional)
    """
    film_links = get_all_film_links()
    total_films = len(film_links)
    
    series_map = {} 
    standalone_films = []

    print(f"Behandler {total_films} film...")
    
    for i, (url, _) in enumerate(film_links.items()):
        # Update progress bar if provided
        if progress_callback:
            progress_callback.progress((i + 1) / total_films, text=f"Scanner film {i+1} af {total_films}")
            
        film_data = scrape_film_details(url, start_date, end_date)
        
        if not film_data:
            continue
            
        s_url = film_data.get('series_url')
        if s_url:
            if s_url not in series_map:
                s_details = scrape_series_details(s_url)
                series_map[s_url] = {
                    "title": film_data['series_title'],
                    "url": s_url,
                    "description": s_details['description'],
                    "image_url": s_details['image_url'],
                    "films": []
                }
            series_map[s_url]['films'].append(film_data)
        else:
            standalone_films.append(film_data)

    # Convert map to list and sort by title
    final_series = sorted(list(series_map.values()), key=lambda x: x['title'])
    
    # Sort films inside series by title
    for s in final_series:
        s['films'].sort(key=lambda x: x['title'])

    return {
        "series": final_series,
        "films": standalone_films
    }
