# scraper.py

import json
import re
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://www.dfi.dk"
CALENDAR_URL_TEMPLATE = (
    BASE_URL
    + "/ajax/load/cinemateket/biograf/calendar/{start}/{end}?display=calendar&serieid=0&tag=all"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# Hjælpefunktion: dansk dato-parse (mest til evt. fremtidig brug)
# ---------------------------------------------------------
def parse_danish_date(text: str, default_year: Optional[int] = None) -> date:
    """
    Parse en dansk dato som fx '10. jan.', '2. november 2025' til datetime.date.
    Brugt som helper – app'en bruger primært kalender-API'et, men vi eksporterer
    den fordi app.py importerer funktionen.
    """
    text = (text or "").strip().lower()
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    months = {
        "jan": 1,
        "januar": 1,
        "feb": 2,
        "februar": 2,
        "mar": 3,
        "marts": 3,
        "apr": 4,
        "april": 4,
        "maj": 5,
        "jun": 6,
        "juni": 6,
        "jul": 7,
        "juli": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "okt": 10,
        "oktober": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    # Find dag og måned
    m = re.search(r"(\d{1,2})\.\s*([a-zæøå\.]+)", text)
    if not m:
        raise ValueError(f"Kan ikke parse dansk dato: {text!r}")

    day = int(m.group(1))
    month_token = m.group(2).strip(".")
    if month_token not in months:
        raise ValueError(f"Ukendt måned i dansk dato: {text!r}")
    month = months[month_token]

    # Find evt. år
    m_year = re.search(r"(\d{4})", text)
    if m_year:
        year = int(m_year.group(1))
    else:
        if default_year is not None:
            year = default_year
        else:
            # Fallback: i år
            year = datetime.now().year

    return date(year, month, day)


# ---------------------------------------------------------
# Kald til Cinematekets kalender-API for én dag
# ---------------------------------------------------------
def _fetch_day_program_html(d: date) -> str:
    """
    Hent HTML-fragmentet med dagens program via AJAX-kaldet, og returner det
    samlede 'program'-HTML som en string.
    """
    start = d.isoformat()
    end = (d + timedelta(days=1)).isoformat()
    url = CALENDAR_URL_TEMPLATE.format(start=start, end=end)

    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()

    data = json.loads(resp.text)
    if not isinstance(data, list):
        return ""

    html_parts = []
    for item in data:
        program_html = item.get("program")
        if program_html:
            html_parts.append(program_html)

    return "\n".join(html_parts)


def _parse_time(time_str: str) -> time:
    """
    Parse '17:45' til datetime.time.
    """
    time_str = time_str.strip()
    # Simpelt format: HH:MM
    try:
        hour, minute = time_str.split(":")
        return time(int(hour), int(minute))
    except Exception:
        # Fallback til 00:00 hvis noget går galt
        return time(0, 0)


def _scrape_day_screenings(d: date) -> List[Dict]:
    """
    Scraper alle visninger for en given dato via kalender-API'et.
    Returnerer en liste af dictionaries med:
        - datetime
        - title
        - film_url
        - ticket_url
        - series_title
        - series_url
        - is_event
    """
    try:
        html = _fetch_day_program_html(d)
    except Exception:
        # Hvis kalender-API'et fejler for en dag, returnér tom liste
        return []

    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    screenings = []

    # Strukturen: <div class="list__item"><div class="list-item ...">...</div></div>
    for wrapper in soup.select("div.list__item"):
        item = wrapper.select_one("div.list-item")
        if not item:
            continue

        time_el = item.select_one("p.list-item__prefix")
        title_el = item.select_one("p.list-item__title a")
        if not time_el or not title_el:
            continue

        time_str = time_el.get_text(strip=True)
        show_time = _parse_time(time_str)
        show_dt = datetime.combine(d, show_time)

        film_title = title_el.get_text(strip=True)
        film_href = title_el.get("href") or ""
        film_url = urljoin(BASE_URL, film_href)

        # Billetlink
        ticket_url = None
        ticket_el = item.select_one("div.list-item__actions a")
        if ticket_el and ticket_el.get("href"):
            ticket_url = ticket_el["href"]

        # Serier (hvis angivet)
        series_title = None
        series_url = None
        for p in item.select("div.list-item__properties p.list-item__property"):
            txt = p.get_text(" ", strip=True).lower()
            if txt.startswith("serier"):
                a = p.find("a")
                if a and a.get("href"):
                    series_title = a.get_text(strip=True)
                    series_url = urljoin(BASE_URL, a["href"])
                break

        # Event eller 'ren' film?
        is_event = "/biograf/events/event" in film_url

        screenings.append(
            {
                "datetime": show_dt,
                "title": film_title,
                "film_url": film_url,
                "ticket_url": ticket_url,
                "series_title": series_title,
                "series_url": series_url,
                "is_event": is_event,
            }
        )

    return screenings


# ---------------------------------------------------------
# Scraping af serie- og filmsider (beskrivelse m.m.)
# ---------------------------------------------------------
@lru_cache(maxsize=256)
def scrape_series(series_url: str) -> Dict:
    """
    Scraper en serieside for:
        - title
        - description (tekst mellem serien-title og 'Film i serien')
        - image_url (første billede på siden)
    Bruges i get_program_data, men kan også kaldes direkte hvis du vil teste.
    """
    result = {
        "title": None,
        "description": "",
        "image_url": None,
        "url": series_url,
    }

    try:
        resp = requests.get(series_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception:
        return result

    soup = BeautifulSoup(resp.text, "lxml")

    # Titel: første h2 efter "Serie"-overskrift
    title_el = None
    for h2 in soup.find_all("h2"):
        # På seriesider er første h2 typisk selve serietitlen
        # fx 'Efterårsferie i Cinemateket'
        title_el = h2
        break

    if not title_el:
        return result

    series_title = title_el.get_text(strip=True)
    result["title"] = series_title

    # Beskrivelse: tekst mellem denne h2 og næste h3 med "Film i serien"
    desc_parts = []
    for sibling in title_el.next_siblings:
        if getattr(sibling, "name", None) in ("h2", "h3"):
            # Stop når vi rammer næste overskrift
            break
        text = ""
        if hasattr(sibling, "get_text"):
            text = sibling.get_text(" ", strip=True)
        else:
            text = str(sibling).strip()
        if text:
            desc_parts.append(text)

    result["description"] = "\n\n".join(desc_parts).strip()

    # Billede: første <img> efter titel
    img = None
    # Først prøver vi at lede efter 'picture__image', som bruges mange steder
    img = soup.select_one("img.picture__image")
    if not img:
        img = soup.find("img")
    if img and img.get("src"):
        result["image_url"] = img["src"]

    return result


@lru_cache(maxsize=512)
def scrape_film(film_url: str, fallback_title: Optional[str] = None) -> Dict:
    """
    Scraper en film-/event-side for:
        - title
        - description (tekst mellem titel og '***'/Medvirkende osv.)
        - image_url
    Hvis noget går galt, returneres minimal info.
    """
    result = {
        "title": fallback_title,
        "description": "",
        "image_url": None,
        "url": film_url,
    }

    try:
        resp = requests.get(film_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception:
        return result

    soup = BeautifulSoup(resp.text, "lxml")

    # Prøv at finde passende titel (h2 efter 'Film'/'Event')
    title_el = None
    # Først: find alle h2 og vælg en der ikke er global navigation
    candidates = soup.find_all("h2")
    if candidates:
        title_el = candidates[0]

    if title_el:
        result["title"] = title_el.get_text(strip=True)

    # Beskrivelse: tekst efter titel, indtil vi rammer '***', 'Medvirkende', 'Køb billetter' osv.
    desc_parts: List[str] = []
    stop_markers = {"medvirkende:", "køb billetter", "film i serien", "se mere"}

    if title_el:
        for sibling in title_el.next_siblings:
            if getattr(sibling, "name", None) in ("h2", "h3"):
                break
            text = ""
            if hasattr(sibling, "get_text"):
                text = sibling.get_text(" ", strip=True)
            else:
                text = str(sibling).strip()
            if not text:
                continue
            lower = text.lower()
            if lower == "* * *":
                break
            if any(marker in lower for marker in stop_markers):
                break
            desc_parts.append(text)

    result["description"] = "\n\n".join(desc_parts).strip()

    # Billede: igen prøv 'picture__image' først
    img = soup.select_one("img.picture__image")
    if not img:
        img = soup.find("img")
    if img and img.get("src"):
        result["image_url"] = img["src"]

    return result


# ---------------------------------------------------------
# (Legacy) scrape_biograf – wrapper om dags-scrape
# ---------------------------------------------------------
def scrape_biograf(start_dt: datetime, end_dt: datetime) -> List[Dict]:
    """
    'Legacy'-funktion, hvis du vil hente rå screeningsdata.
    Bruger kalender-API'et til at hente alle visninger mellem to datoer.
    Returnerer en flad liste med screenings (samme struktur som _scrape_day_screenings).
    """
    screenings: List[Dict] = []
    current = start_dt.date()
    end_date_only = end_dt.date()

    while current <= end_date_only:
        screenings.extend(_scrape_day_screenings(current))
        current += timedelta(days=1)

    # Filtrér i tilfælde af at nogen visninger ligger udenfor klokkeslæt-intervallet
    filtered = []
    for s in screenings:
        dt = s["datetime"]
        if start_dt <= dt <= end_dt:
            filtered.append(s)

    return filtered


# ---------------------------------------------------------
# Hovedfunktion: get_program_data
# ---------------------------------------------------------
def get_program_data(start_dt: datetime, end_dt: datetime) -> Dict:
    """
    Hoved-funktion som bruges af Streamlit-appen.

    Returnerer:
        {
          "series": [
            {
              "title": ...,
              "description": ...,
              "image_url": ...,
              "url": ...,
              "tickets": [
                {
                  "film": ...,
                  "date": datetime,
                  "link": ...,
                  "event": bool,
                },
                ...
              ],
            },
            ...
          ],
          "films": [
            {
              "title": ...,
              "description": ...,
              "image_url": ...,
              "url": ...,
              "screenings": [
                {
                  "title": ...,
                  "description": ...,
                  "date": datetime,
                  "link": ...,
                  "event": bool,
                },
                ...
              ],
            },
            ...
          ],
        }
    """
    # 1) Hent alle screenings fra kalenderen
    all_screenings = scrape_biograf(start_dt, end_dt)

    # 2) Grupper efter serier
    series_map: Dict[str, Dict] = {}  # key: series_url
    for s in all_screenings:
        series_url = s.get("series_url")
        series_title = s.get("series_title")

        if not series_url or not series_title:
            continue

        if series_url not in series_map:
            # Hent serie-info (beskrivelse, billede osv.)
            series_info = scrape_series(series_url)
            # Brug scraped titel hvis den findes
            display_title = series_info.get("title") or series_title

            series_map[series_url] = {
                "title": display_title,
                "description": series_info.get("description", ""),
                "image_url": series_info.get("image_url"),
                "url": series_url,
                "tickets": [],
            }

        series_map[series_url]["tickets"].append(
            {
                "film": s["title"],
                "date": s["datetime"],
                "link": s.get("ticket_url") or s["film_url"],
                "event": bool(s.get("is_event")),
            }
        )

    # 3) Grupper efter film (uanset serie), så vi kan vise "Enkeltfilm"
    films_map: Dict[str, Dict] = {}  # key: film_url
    for s in all_screenings:
        film_url = s["film_url"]
        if film_url not in films_map:
            film_info = scrape_film(film_url, fallback_title=s["title"])
            films_map[film_url] = {
                "title": film_info.get("title") or s["title"],
                "description": film_info.get("description", ""),
                "image_url": film_info.get("image_url"),
                "url": film_url,
                "screenings": [],
            }

        films_map[film_url]["screenings"].append(
            {
                "title": films_map[film_url]["title"],
                "description": films_map[film_url]["description"],
                "date": s["datetime"],
                "link": s.get("ticket_url") or film_url,
                "event": bool(s.get("is_event")),
            }
        )

    # 4) Byg endelig struktur
    series_list = list(series_map.values())

    # Sorter serier alfabetisk
    series_list.sort(key=lambda x: x["title"].lower())

    films_list = list(films_map.values())

    # Sorter film efter første visningsdato
    for f in films_list:
        f["screenings"].sort(key=lambda s: s["date"])
    films_list.sort(key=lambda f: f["screenings"][0]["date"])

    return {
        "series": series_list,
        "films": films_list,
    }
