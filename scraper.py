# scraper.py
"""
Cinemateket program scraper
----------------------------
Scraper filmserier, enkeltfilm og visninger fra https://www.dfi.dk/cinemateket

Returnerer en datastruktur som bruges af Streamlit-appen (app.py):
{
  "series": [ ... ],
  "films": [ ... ]
}
"""

import re
from datetime import datetime, date, time, timedelta
from functools import lru_cache
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.dfi.dk"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0 Safari/537.36"
    )
}

# ---------------------------------------------------------
# Hjælpefunktioner
# ---------------------------------------------------------
def parse_danish_date(text: str, default_year: Optional[int] = None) -> date:
    """
    Parser dansk dato som '10. jan.' eller '2. november 2025' til datetime.date
    """
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    months = {
        "jan": 1, "januar": 1, "feb": 2, "februar": 2, "mar": 3, "marts": 3,
        "apr": 4, "april": 4, "maj": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7,
        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "okt": 10, "oktober": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    m = re.search(r"(\d{1,2})\.\s*([a-zæøå\.]+)", text)
    if not m:
        raise ValueError(f"Kan ikke parse dato: {text}")
    day = int(m.group(1))
    month_name = m.group(2).strip(".")
    month = months.get(month_name)
    if not month:
        raise ValueError(f"Ukendt måned i dato: {text}")
    m_year = re.search(r"(\d{4})", text)
    if m_year:
        year = int(m_year.group(1))
    else:
        year = default_year or datetime.now().year
    return date(year, month, day)


def _fetch_day_program_html(d: date) -> str:
    """Henter HTML for en bestemt dag i Cinematekets program."""
    url = f"{BASE_URL}/cinemateket/biograf?date={d.isoformat()}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def _parse_time(t: str) -> time:
    """Parser tidspunkt som '19:30'."""
    try:
        h, m = t.strip().split(":")
        return time(int(h), int(m))
    except Exception:
        return time(0, 0)


# ---------------------------------------------------------
# Scraper for én dags program
# ---------------------------------------------------------
def _scrape_day_screenings(d: date) -> List[Dict]:
    """Scraper alle visninger på en given dato."""
    try:
        html = _fetch_day_program_html(d)
    except Exception:
        return []

    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one(".view-biograf-program")
    if not container:
        return []

    results: List[Dict] = []
    for item in container.select(".views-row"):
        text = item.get_text(" ", strip=True)
        link_el = item.find("a")
        if not link_el:
            continue
        film_title = link_el.get_text(strip=True)
        film_url = urljoin(BASE_URL, link_el.get("href", ""))

        # Tidspunkt
        m = re.search(r"(\d{1,2}:\d{2})", text)
        visningstid = _parse_time(m.group(1)) if m else time(0, 0)
        show_dt = datetime.combine(d, visningstid)

        # Billet-link
        ticket_el = item.select_one("a.list-item__ticket")
        ticket_url = None
        if ticket_el and ticket_el.get("href"):
            ticket_url = urljoin(BASE_URL, ticket_el["href"])

        # Serie (hvis nævnt)
        series_title = None
        series_url = None
        for span in item.find_all(["span", "div", "p"]):
            t = span.get_text(" ", strip=True).lower()
            if "serie" in t:
                a = span.find("a")
                if a and a.get("href"):
                    series_title = a.get_text(strip=True)
                    series_url = urljoin(BASE_URL, a["href"])
                break

        is_event = "/cinemateket/biograf/events/" in film_url

        results.append({
            "datetime": show_dt,
            "title": film_title,
            "film_url": film_url,
            "ticket_url": ticket_url,
            "series_title": series_title,
            "series_url": series_url,
            "is_event": is_event,
        })
    return results


# ---------------------------------------------------------
# Scraping af serie- og film-sider
# ---------------------------------------------------------
@lru_cache(maxsize=256)
def scrape_series(series_url: str) -> Dict:
    """Scraper en serieside for titel, beskrivelse og billede."""
    result = {"title": None, "description": "", "image_url": None, "url": series_url}
    try:
        resp = requests.get(series_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    title_el = soup.find("h2") or soup.find("h1")
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    desc_parts = []
    if title_el:
        for sib in title_el.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h2", "h3"):
                break
            if hasattr(sib, "get_text"):
                text = sib.get_text(" ", strip=True)
            else:
                text = str(sib).strip()
            if text:
                desc_parts.append(text)
    result["description"] = "\n\n".join(desc_parts).strip()

    img = soup.find("img")
    if img and img.get("src"):
        result["image_url"] = urljoin(BASE_URL, img["src"])
    return result


@lru_cache(maxsize=512)
def scrape_film(film_url: str, fallback_title: Optional[str] = None) -> Dict:
    """Scraper en film- eller eventside for titel, beskrivelse og billede."""
    result = {"title": fallback_title, "description": "", "image_url": None, "url": film_url}
    try:
        resp = requests.get(film_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    title_el = soup.find("h2") or soup.find("h1")
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    desc_parts = []
    stop_words = {"medvirkende", "køb billetter", "film i serien", "se mere"}
    if title_el:
        for sib in title_el.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h2", "h3"):
                break
            if hasattr(sib, "get_text"):
                text = sib.get_text(" ", strip=True)
            else:
                text = str(sib).strip()
            if not text:
                continue
            if any(word in text.lower() for word in stop_words):
                break
            desc_parts.append(text)
    result["description"] = "\n\n".join(desc_parts).strip()

    img = soup.find("img")
    if img and img.get("src"):
        result["image_url"] = urljoin(BASE_URL, img["src"])
    return result


# ---------------------------------------------------------
# Samlet dataudtræk
# ---------------------------------------------------------
def scrape_biograf(start_dt: datetime, end_dt: datetime) -> List[Dict]:
    """Henter alle visninger mellem to datoer."""
    results: List[Dict] = []
    current = start_dt.date()
    while current <= end_dt.date():
        results.extend(_scrape_day_screenings(current))
        current += timedelta(days=1)
    # filtrér kun indenfor intervallet
    return [r for r in results if start_dt <= r["datetime"] <= end_dt]


def get_program_data(start_dt: datetime, end_dt: datetime) -> Dict:
    """Returnerer samlet datastruktur med serier og film."""
    all_screenings = scrape_biograf(start_dt, end_dt)

    # --- Serier ---
    series_map: Dict[str, Dict] = {}
    for s in all_screenings:
        s_url = s.get("series_url")
        if not s_url:
            continue
        if s_url not in series_map:
            info = scrape_series(s_url)
            series_map[s_url] = {
                "title": info.get("title") or s.get("series_title") or "Serie",
                "description": info.get("description", ""),
                "image_url": info.get("image_url"),
                "url": s_url,
                "tickets": [],
            }
        series_map[s_url]["tickets"].append({
            "film": s["title"],
            "date": s["datetime"],
            "link": s.get("ticket_url") or s["film_url"],
            "event": bool(s.get("is_event")),
        })

    # --- Enkeltfilm ---
    films_map: Dict[str, Dict] = {}
    for s in all_screenings:
        f_url = s["film_url"]
        if f_url not in films_map:
            info = scrape_film(f_url, fallback_title=s["title"])
            films_map[f_url] = {
                "title": info.get("title") or s["title"],
                "description": info.get("description", ""),
                "image_url": info.get("image_url"),
                "url": f_url,
                "screenings": [],
            }
        films_map[f_url]["screenings"].append({
            "title": films_map[f_url]["title"],
            "description": films_map[f_url]["description"],
            "date": s["datetime"],
            "link": s.get("ticket_url") or f_url,
            "event": bool(s.get("is_event")),
        })

    # Sortér
    series_list = sorted(series_map.values(), key=lambda x: x["title"].lower())
    films_list = sorted(
        films_map.values(),
        key=lambda x: x["screenings"][0]["date"] if x["screenings"] else datetime(2100, 1, 1)
    )
    for f in films_list:
        f["screenings"].sort(key=lambda sc: sc["date"])

    return {"series": series_list, "films": films_list}
