# scraper.py – scraper Cinematekets program uden at bruge PDF-kalenderen
#
# Strategi (kort):
# - Vi henter alle aktuelle film fra siden "Alle film"
#     https://www.dfi.dk/cinemateket/biograf/alle-film (+ evt. "Næste"-sider)
# - For hver film går vi ind på dens egen side:
#     https://www.dfi.dk/cinemateket/biograf/alle-film/film/<slug>
#   Her finder vi:
#     * Titel
#     * Evt. "Film i serien – <serietitel>" + link til serien
#     * Afsnittet "Køb billetter" med et eller flere links, der indeholder
#       tekst som: "Himlen over Berlin Søndag 4. januar 16:15 Bestil billet"
# - Fra disse links parser vi dato/tid (dansk) og billetlink.
# - Seriessider bruges kun til at hente seriebeskrivelse + billede.
#
# Resultat-struktur fra get_program_data(start_dt, end_dt):
# {
#   "series": [
#       {
#           "title": str,
#           "url": str | None,
#           "description": str,
#           "image_url": str | None,
#           "screenings": [
#               {
#                   "film": str,
#                   "film_url": str,
#                   "date": datetime,
#                   "link": str,
#                   "event": bool,
#               },
#               ...
#           ],
#       },
#       ...
#   ],
#   "films": [
#       {
#           "title": str,
#           "url": str,
#           "description": str,
#           "image_url": str | None,
#           "is_event": bool,
#           "series_title": str | None,
#           "series_url": str | None,
#           "screenings": [
#               {
#                   "date": datetime,
#                   "link": str,
#               },
#               ...
#           ],
#       },
#       ...
#   ],
# }

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://www.dfi.dk"


# -------------------- Hjælpefunktioner --------------------


def _get(url: str) -> requests.Response:
    """Wrapper omkring requests.get med simple headers + timeout."""
    resp = requests.get(url, headers={"User-Agent": "cinemateket-scraper/1.0"}, timeout=15)
    resp.raise_for_status()
    return resp


@lru_cache(maxsize=128)
def _get_soup(url: str) -> BeautifulSoup:
    """Hent URL og returnér BeautifulSoup-objekt (med cache)."""
    html = _get(url).text
    return BeautifulSoup(html, "lxml")


MONTH_MAP = {
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


def _resolve_year(base: datetime, month: int) -> int:
    """
    Cinematekets tekster har normalt ikke årstal (kun dag + måned).
    Vi antager at visningerne ligger tæt på base-datoen (typisk samme
    år eller omkring årsskifte).
    """
    year = base.year
    # Simpel heuristik ved årsskifte:
    if base.month == 12 and month == 1:
        return year + 1
    if base.month == 1 and month == 12:
        return year - 1
    return year


def parse_danish_date(date_str: str, current_year: Optional[int] = None) -> Optional[datetime]:
    """
    Bevarer en "gammel" signatur, men bruges ikke direkte til visninger.
    Vi forsøger at finde mønster: '13. dec' eller '13. december'.
    Hvis current_year ikke er angivet, bruges nuværende år.
    """
    if not date_str:
        return None

    if current_year is None:
        current_year = datetime.now().year

    # Find noget der ligner '13. dec' eller '13. december'
    m = re.search(r"(\d{1,2})\.\s*([A-Za-zæøåÆØÅ]+)", date_str)
    if not m:
        return None

    day = int(m.group(1))
    month_txt = m.group(2).lower().rstrip(".")
    month = MONTH_MAP.get(month_txt)
    if not month:
        return None

    try:
        return datetime(current_year, month, day)
    except ValueError:
        return None


def parse_danish_datetime_from_text(text: str, base_date: datetime) -> Optional[datetime]:
    """
    Parser en linje med dato + tid, fx:
        'Himlen over Berlin Søndag 4. januar 16:15 Bestil billet'
        '4. januar kl. 16:15 – Køb billet'
    Vi trækker kun dato + tid ud. Årstal afledes fra base_date.
    """
    if not text:
        return None

    cleaned = (
        text.replace("Bestil billet", "")
        .replace("Køb billet", "")
        .replace("Køb billetter", "")
    )
    cleaned = " ".join(cleaned.split())

    # Ugedage er valgfrie; vi matcher kun dag/måned/tid (HH:MM)
    weekday_pattern = r"(?:Mandag|Tirsdag|Onsdag|Torsdag|Fredag|Lørdag|Søndag)\s+"

    # Capture: (valgfri ugedag), dag, måned, tid (HH:MM) med evt. 'kl.'
    pattern = (
        rf"(?:{weekday_pattern})?(\d{{1,2}})\.?\s+([A-Za-zæøåÆØÅ]+)\s+(?:kl\.?\s*)?(\d{{1,2}}:\d{{2}})"
    )

    m = re.search(pattern, cleaned, flags=re.IGNORECASE)
    if not m:
        return None

    day = int(m.group(1))
    month_txt = m.group(2).lower().rstrip(".")
    time_str = m.group(3)

    month = MONTH_MAP.get(month_txt)
    if not month:
        return None

    year = _resolve_year(base_date, month)

    try:
        hour, minute = map(int, time_str.split(":"))
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


# -------------------- Scrape af "Alle film"-oversigt --------------------


def _iter_all_films_index_pages() -> List[BeautifulSoup]:
    """
    Returnerer alle sider for 'Alle film' inkl. evt. 'Næste'-sider.
    """
    soups: List[BeautifulSoup] = []
    url = urljoin(BASE_URL, "/cinemateket/biograf/alle-film")
    seen: set[str] = set()

    while url and url not in seen:
        seen.add(url)
        soup = _get_soup(url)
        soups.append(soup)

        # Find 'Næste'-link, hvis det findes
        next_link = soup.find("a", string=lambda s: s and "Næste" in s)
        if next_link and next_link.get("href"):
            url = urljoin(BASE_URL, next_link["href"])
        else:
            url = None

    return soups


def scrape_all_films_index() -> List[Dict]:
    """
    Scraper listen 'Alle film' og returnerer en liste med:
    {
        "title": str,
        "url": str,
        "raw_text": str,  # hele linkteksten, inkl. dato-resumé
    }
    """
    films_map: Dict[str, Dict] = {}

    for soup in _iter_all_films_index_pages():
        for a in soup.select('a[href^="/cinemateket/biograf/alle-film/film/"]'):
            href = a.get("href")
            if not href:
                continue
            full_url = urljoin(BASE_URL, href)
            text = " ".join(a.stripped_strings).strip()
            if not text:
                continue

            # Gem kun én entry pr. URL (eller den længste tekst)
            existing = films_map.get(full_url)
            if not existing or len(text) > len(existing.get("raw_text", "")):
                films_map[full_url] = {
                    "url": full_url,
                    "raw_text": text,
                }

    # Udled titel (alt før første dato-lignende mønster)
    for film in films_map.values():
        raw = film["raw_text"]
        m = re.search(r"\b\d{1,2}\.\s*[A-Za-zæøåÆØÅ]+", raw)
        if m:
            title = raw[: m.start()].strip(" –-—\u2013\u2014")
        else:
            title = raw.strip()
        film["title"] = title

    return list(films_map.values())


# -------------------- Scrape af enkel film-side --------------------


def _extract_description(soup: BeautifulSoup) -> str:
    """
    Vi tager et par første tekst-paragraffer efter titel som beskrivelse.
    Strukturen kan variere lidt, så vi gør det robust frem for perfekt.
    """
    # Find titel-h2/h1
    title_tag = None
    for h in soup.find_all(["h1", "h2"]):
        if h.get_text(strip=True):
            title_tag = h
            break

    if not title_tag:
        # fallback: bare tag nogle <p>-tags
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return "\n\n".join(paragraphs[:2]).strip()

    # Saml tekst fra de næste få søskende <p>-elementer
    desc_parts: List[str] = []
    for sibling in title_tag.find_all_next():
        # stop når vi når næste store sektion
        if sibling.name in {"h2", "h3"}:
            break
        if sibling.name == "p":
            txt = sibling.get_text(" ", strip=True)
            if txt:
                desc_parts.append(txt)
        # begræns længden lidt
        if len(desc_parts) >= 3:
            break

    if not desc_parts:
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return "\n\n".join(paragraphs[:2]).strip()

    return "\n\n".join(desc_parts).strip()


def _extract_image_url(soup: BeautifulSoup) -> Optional[str]:
    """
    Finder et fornuftigt billede til filmen/serien.
    """
    img = soup.select_one("img.picture__image")
    if not img:
        img = soup.find("img")
    if img and img.get("src"):
        return urljoin(BASE_URL, img["src"])
    return None


def scrape_film(
    film_url: str,
    start_dt: datetime,
    end_dt: datetime,
) -> Optional[Dict]:
    """
    Scraper en filmside og returnerer:
    {
        "title": str,
        "url": str,
        "description": str,
        "image_url": str | None,
        "is_event": bool,
        "series_title": str | None,
        "series_url": str | None,
        "screenings": [ { "date": datetime, "link": str }, ... ],
    }
    Kun visninger mellem start_dt og end_dt medtages.
    """
    soup = _get_soup(film_url)

    # Titel
    title_tag = None
    for h in soup.find_all(["h1", "h2"]):
        text = h.get_text(strip=True)
        if text and text not in {"Cinemateket", "Film"}:
            title_tag = h
            break
    title = title_tag.get_text(strip=True) if title_tag else film_url

    # Er det et event eller en film?
    is_event = False
    header = soup.find("h3")
    if header and "event" in header.get_text(strip=True).lower():
        is_event = True

    # Serietitel + link
    series_title = None
    series_url = None
    series_heading = soup.find(
        lambda tag: tag.name in {"h2", "h3"} and "Film i serien" in tag.get_text()
    )
    if series_heading:
        txt = series_heading.get_text(" ", strip=True)
        # Typisk: "Film i serien – Europa - kontinentet kalder"
        parts = txt.split("–", 1)
        if len(parts) == 2:
            series_title = parts[1].strip()
        # Find "Se alle"-linket
        se_alle = series_heading.find_next(
            "a", string=lambda s: s and "Se alle" in s
        )
        if se_alle and se_alle.get("href"):
            series_url = urljoin(BASE_URL, se_alle["href"])

    description = _extract_description(soup)
    image_url = _extract_image_url(soup)

    # Find alle billetlinks – teksten varierer ("Bestil billet", "Køb billet" m.m.)
    screenings: List[Dict] = []
    for a in soup.find_all("a", href=True):
        link_text = " ".join(a.stripped_strings)
        aria = a.get("aria-label") or ""
        combined_text = " ".join([link_text, aria]).strip()

        if "billet" not in combined_text.lower():
            continue

        href = a["href"]
        if not href:
            continue
        ticket_url = urljoin(BASE_URL, href)
        dt = parse_danish_datetime_from_text(combined_text, base_date=start_dt)
        if not dt:
            continue
        if not (start_dt <= dt <= end_dt):
            continue
        screenings.append(
            {
                "date": dt,
                "link": ticket_url,
            }
        )

    if not screenings:
        return None

    screenings.sort(key=lambda s: s["date"])

    return {
        "title": title,
        "url": film_url,
        "description": description,
        "image_url": image_url,
        "is_event": is_event,
        "series_title": series_title,
        "series_url": series_url,
        "screenings": screenings,
    }


# -------------------- Scrape af seriesider (kun tekst/billede) --------------------


def scrape_series_page(series_url: str) -> Optional[Dict]:
    """
    Henter titel, beskrivelse og billede for en serie.
    Selve visningerne hentes via film-siderne, så vi ignorerer 'Køb billetter'
    her – det undgår dobbeltarbejde.
    """
    soup = _get_soup(series_url)

    # Titel
    title_tag = None
    for h in soup.find_all(["h1", "h2"]):
        text = h.get_text(strip=True)
        if text and text not in {"Cinemateket", "Filmserier"}:
            title_tag = h
            break
    title = title_tag.get_text(strip=True) if title_tag else series_url

    description = _extract_description(soup)
    image_url = _extract_image_url(soup)

    return {
        "title": title,
        "description": description,
        "image_url": image_url,
        "url": series_url,
    }


# -------------------- Samlet programfunktion --------------------


def get_program_data(start_dt: datetime, end_dt: datetime) -> Dict[str, List[Dict]]:
    """
    Hovedfunktion som bruges fra app.py.

    - Finder alle film via 'Alle film'-siderne
    - Scraper hver film-side for billetlinks i perioden
    - Grupperer resultaterne på:
        * Serier (via 'Film i serien …' på filmsiderne)
        * Enkelt-film (alt)

    Returnerer en dict med "series" og "films" som beskrevet i toppen af filen.
    """
    # 1) Find alle aktuelle film i indekset
    films_index = scrape_all_films_index()

    films: List[Dict] = []
    series_map: Dict[str, Dict] = {}

    # 2) Scrape hver film-side for visninger
    for entry in films_index:
        film_url = entry["url"]
        try:
            film_data = scrape_film(film_url, start_dt=start_dt, end_dt=end_dt)
        except Exception:
            # Robusthed: hvis en enkelt side fejler, fortsætter vi
            film_data = None

        if not film_data:
            continue

        films.append(film_data)

        # Opdater serie-opsamling
        s_title = film_data.get("series_title")
        s_url = film_data.get("series_url")
        if s_title:
            if s_title not in series_map:
                series_map[s_title] = {
                    "title": s_title,
                    "url": s_url,
                    "description": "",
                    "image_url": None,
                    "screenings": [],
                }

            for s in film_data["screenings"]:
                series_map[s_title]["screenings"].append(
                    {
                        "film": film_data["title"],
                        "film_url": film_data["url"],
                        "date": s["date"],
                        "link": s["link"],
                        "event": film_data["is_event"],
                    }
                )

    # 3) Hent seriebeskrivelse/billede for serier vi har fundet
    for s_title, s_data in list(series_map.items()):
        url = s_data.get("url")
        if not url:
            continue
        try:
            details = scrape_series_page(url)
        except Exception:
            details = None
        if details:
            if details.get("description"):
                s_data["description"] = details["description"]
            if details.get("image_url"):
                s_data["image_url"] = details["image_url"]

    # 4) Sorter listerne pænt
    for s in series_map.values():
        s["screenings"].sort(key=lambda x: x["date"])
    series_list = sorted(series_map.values(), key=lambda x: x["title"].lower())

    for f in films:
        f["screenings"].sort(key=lambda x: x["date"])
    films.sort(key=lambda f: f["screenings"][0]["date"])

    return {
        "series": series_list,
        "films": films,
    }
