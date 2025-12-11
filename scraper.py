"""
Scraper til Cinematekets program.

Strategi (v2 – kun film-sider, ingen PDF):
- Hent listen "Alle film" inkl. pagination.
- For hver film-side:
    * Find kommende visninger via sektionen "Køb billetter"
    * Ekstrahér dato/tid og billet-link fra tekst som
      "Himlen over Berlin Søndag 4. januar 16:15 Bestil billet"
- Filtrer visninger på den ønskede periode (start_dt–end_dt).
- Forsøg at koble film til en serie via "Film i serien"-sektionen på filmsiden.

Resultatstrukturen er tilpasset app.py:

get_program_data(...) -> {
    "series": [
        {
            "title": str,
            "description": str,
            "image_url": str | None,
            "url": str | None,
            "tickets": [
                {
                    "film": str,
                    "film_url": str,
                    "series_title": str | None,
                    "series_url": str | None,
                    "date": datetime,
                    "link": str,
                    "event": bool,
                    "image_url": str | None,
                },
                ...
            ]
        },
        ...
    ],
    "films": [
        {
            "title": str,
            "description": str,
            "image_url": str | None,
            "url": str,
            "is_event": bool,
            "series_title": str | None,
            "series_url": str | None,
            "screenings": [
                {
                    "date": datetime,
                    "link": str,
                    "event": bool,
                    "series_title": str | None,
                    "series_url": str | None,
                },
                ...
            ]
        },
        ...
    ]
}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


BASE_URL = "https://www.dfi.dk"
ALL_FILMS_URL = f"{BASE_URL}/cinemateket/biograf/alle-film"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Safari/537.36"
)

HEADERS = {"User-Agent": USER_AGENT}

# ---------- Hjælpefunktioner til dato/tid ----------

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

WEEKDAY_PATTERN = r"(Mandag|Tirsdag|Onsdag|Torsdag|Fredag|Lørdag|Søndag)"


def _resolve_year(base_date: datetime, month: int) -> int:
    """
    Fastsæt år ud fra base_date + måned.
    Håndter overgang dec -> jan og jan -> dec, så vi ikke får 'forkerte' år.
    """
    year = base_date.year
    if base_date.month == 12 and month == 1:
        return year + 1
    if base_date.month == 1 and month == 12:
        return year - 1
    return year


def parse_danish_datetime_from_text(text: str, base_date: datetime) -> Optional[datetime]:
    """
    Find 'Søndag 4. januar 16:15' i en tekst og returnér datetime.
    """
    # Ryd op i tekst
    cleaned = text.replace("Bestil billet", "")
    cleaned = " ".join(cleaned.split())

    pattern = rf"{WEEKDAY_PATTERN}\s+(\d{{1,2}})\.?\s+([A-Za-zæøåÆØÅ]+)\s+(\d{{1,2}}:\d{{2}})"
    m = re.search(pattern, cleaned, flags=re.IGNORECASE)
    if not m:
        return None

    day = int(m.group(2))
    month_txt = m.group(3).lower().rstrip(".")
    time_str = m.group(4)

    month = MONTH_MAP.get(month_txt)
    if not month:
        return None

    year = _resolve_year(base_date, month)
    hour, minute = map(int, time_str.split(":"))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


# ---------- Hjælpefunktioner til HTTP / HTML ----------


def _get_soup(url: str) -> BeautifulSoup:
    """
    Hent en side og returnér BeautifulSoup-objekt.
    """
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    # Brug lxml hvis det er installeret, ellers fallback til html.parser
    try:
        return BeautifulSoup(resp.text, "lxml")
    except Exception:
        return BeautifulSoup(resp.text, "html.parser")


# ---------- Dataklasser ----------


@dataclass
class Screening:
    film_title: str
    film_url: str
    dt: datetime
    ticket_url: str
    is_event: bool
    series_title: Optional[str] = None
    series_url: Optional[str] = None
    image_url: Optional[str] = None


@dataclass
class FilmInfo:
    title: str
    url: str
    description: str = ""
    image_url: Optional[str] = None
    is_event: bool = False
    series_title: Optional[str] = None
    series_url: Optional[str] = None
    screenings: List[Screening] = field(default_factory=list)


@dataclass
class SeriesInfo:
    title: str
    url: Optional[str] = None
    description: str = ""
    image_url: Optional[str] = None
    tickets: List[Screening] = field(default_factory=list)


# ---------- Scrape "Alle film"-listen ----------


@lru_cache(maxsize=1)
def _get_all_film_links() -> Dict[str, str]:
    """
    Returnér dict {film_url: film_titel} fra 'Alle film' inkl. pagination.
    """
    film_links: Dict[str, str] = {}

    next_url = ALL_FILMS_URL
    seen_pages = set()
    max_pages = 30  # safety

    for _ in range(max_pages):
        if not next_url or next_url in seen_pages:
            break
        seen_pages.add(next_url)

        soup = _get_soup(next_url)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("/cinemateket/biograf/alle-film/film/"):
                continue

            url = urljoin(BASE_URL, href)
            title = a.get_text(strip=True)
            # Fjern evt. datoer efter titlen (" / 27. jan" etc.)
            title = re.split(r"\s+/\s+", title)[0].strip()
            film_links.setdefault(url, title)

        # Find link til næste side (tekst "Næste")
        next_a = None
        for a in soup.find_all("a", href=True):
            if re.search(r"\bNæste\b", a.get_text(strip=True), flags=re.IGNORECASE):
                next_a = a
                break

        if next_a:
            next_url = urljoin(BASE_URL, next_a["href"])
        else:
            break

    return film_links


# ---------- Scrape enkelt film-side ----------


def _extract_film_description_and_image(soup: BeautifulSoup) -> Tuple[str, Optional[str]]:
    """
    Forsøger at udtrække filmens beskrivelse og billede fra filmsiden.
    Beskrivelse = tekst efter filmens titel og før '***' / 'Medvirkende' / 'Køb billetter' osv.
    """
    # Find sektion "Film"
    film_h3 = None
    for h3 in soup.find_all("h3"):
        txt = h3.get_text(strip=True)
        if "Film" in txt:
            film_h3 = h3
            break

    title_h2 = None
    if film_h3:
        title_h2 = film_h3.find_next("h2")
    if not title_h2:
        # fallback: første h2 på siden, som ikke er "Cinemateket" o.l.
        for h2 in soup.find_all("h2"):
            txt = h2.get_text(strip=True)
            if txt and "Cinemateket" not in txt:
                title_h2 = h2
                break

    description = ""
    if title_h2:
        parts: List[str] = []
        stop_markers = {"medvirkende", "køb billetter", "film i serien", "se mere"}

        for sib in title_h2.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h2", "h3"):
                break

            if hasattr(sib, "get_text"):
                text = sib.get_text(" ", strip=True)
            else:
                text = str(sib).strip()

            if not text:
                continue

            low = text.lower()
            if low == "* * *":
                break
            if any(marker in low for marker in stop_markers):
                break

            parts.append(text)

        description = "\n\n".join(parts).strip()

    # Billede: prøv først img.picture__image, ellers første img efter film_h3
    img_url: Optional[str] = None

    img = soup.select_one("img.picture__image")
    if not img and film_h3:
        img = film_h3.find_next("img")

    if img and img.get("src"):
        img_url = urljoin(BASE_URL, img["src"])

    return description, img_url


def _extract_series_from_film_page(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    """
    Find 'Film i serien – XXX' + 'Se alle'-linket, så vi både har titel og URL.
    """
    for h3 in soup.find_all("h3"):
        txt = h3.get_text(strip=True)
        if "Film i serien" in txt:
            # Næste h2 indeholder titlen på serien
            title_h2 = h3.find_next("h2")
            title = title_h2.get_text(strip=True) if title_h2 else None

            # 'Se alle'-linket peger til serie-siden
            series_url = None
            for a in h3.find_all_next("a", href=True):
                if "Se alle" in a.get_text(strip=True):
                    series_url = urljoin(BASE_URL, a["href"])
                    break

            return title, series_url

    return None, None


def _extract_screenings_from_film_page(
    soup: BeautifulSoup,
    film_title: str,
    film_url: str,
    base_start: datetime,
    base_end: datetime,
    image_url: Optional[str],
) -> Tuple[List[Screening], bool]:
    """
    Find alle 'Bestil billet'-links i sektionen 'Køb billetter' og returnér Screening-objekter
    inden for det ønskede datointerval.
    Returnerer (screenings, is_event_flag_for_any_screening).
    """
    screenings: List[Screening] = []

    # Find "Køb billetter"-sektion
    buy_h3 = None
    for h3 in soup.find_all("h3"):
        if "Køb billetter" in h3.get_text(strip=True):
            buy_h3 = h3
            break

    if not buy_h3:
        return screenings, False

    # Vi stopper, når vi rammer næste h3 efter buy_h3
    is_event_overall = False
    current = buy_h3
    while current is not None:
        current = current.next_sibling
        if current is None:
            break

        if getattr(current, "name", None) == "h3":
            # Ny sektion -> stop
            break

        if not hasattr(current, "find_all"):
            continue

        for a in current.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if "Bestil billet" not in text:
                continue

            dt = parse_danish_datetime_from_text(text, base_start)
            if not dt:
                continue

            if not (base_start <= dt <= base_end):
                continue

            ticket_url = a["href"]
            # ekstern ebillet-link kan være absolut eller relativ
            ticket_url = urljoin(BASE_URL, ticket_url)

            is_event = "event" in text.lower()
            is_event_overall = is_event_overall or is_event

            screenings.append(
                Screening(
                    film_title=film_title,
                    film_url=film_url,
                    dt=dt,
                    ticket_url=ticket_url,
                    is_event=is_event,
                    image_url=image_url,
                )
            )

    return screenings, is_event_overall


def scrape_film(
    film_url: str,
    start_dt: datetime,
    end_dt: datetime,
    fallback_title: Optional[str] = None,
) -> Optional[FilmInfo]:
    """
    Scraper én film-/eventside og returnerer FilmInfo eller None, hvis der
    ingen relevante visninger er i perioden.
    """
    try:
        soup = _get_soup(film_url)
    except Exception:
        return None

    # Titel – brug fallback fra "Alle film" hvis vi ikke finder noget bedre
    title = fallback_title
    if not title:
        h2 = None
        for candidate in soup.find_all("h2"):
            txt = candidate.get_text(strip=True)
            if txt and "Cinemateket" not in txt:
                h2 = candidate
                break
        if h2:
            title = h2.get_text(strip=True)
    if not title:
        title = film_url.rsplit("/", 1)[-1].replace("-", " ").title()

    description, img_url = _extract_film_description_and_image(soup)
    series_title, series_url = _extract_series_from_film_page(soup)

    screenings, is_event_flag = _extract_screenings_from_film_page(
        soup,
        film_title=title,
        film_url=film_url,
        base_start=start_dt,
        base_end=end_dt,
        image_url=img_url,
    )

    if not screenings:
        return None

    film_info = FilmInfo(
        title=title,
        url=film_url,
        description=description,
        image_url=img_url,
        is_event=is_event_flag,
        series_title=series_title,
        series_url=series_url,
        screenings=screenings,
    )

    return film_info


# ---------- Scrape serie-sider (kun til beskrivelse/billede) ----------


@lru_cache(maxsize=128)
def scrape_series(series_url: str) -> SeriesInfo:
    """
    Hent serien (titel, beskrivelse, billede) – brugt til at pynte serie-bokse
    i UI'et. Billetter håndteres pr. film.
    """
    try:
        soup = _get_soup(series_url)
    except Exception:
        # Minimal fallback
        return SeriesInfo(title=series_url.rsplit("/", 1)[-1].replace("-", " ").title(), url=series_url)

    # Titel (første h2 efter 'Serie')
    title = None
    series_h3 = None
    for h3 in soup.find_all("h3"):
        if "Serie" in h3.get_text(strip=True):
            series_h3 = h3
            break

    if series_h3:
        h2 = series_h3.find_next("h2")
        if h2:
            title = h2.get_text(strip=True)

    if not title:
        h2 = soup.find("h2")
        if h2:
            title = h2.get_text(strip=True)
    if not title:
        title = series_url.rsplit("/", 1)[-1].replace("-", " ").title()

    # Beskrivelse = tekst efter serie-h2 til 'Se mere' / 'Køb billetter'
    description = ""
    if series_h3:
        series_title_h2 = series_h3.find_next("h2")
    else:
        series_title_h2 = soup.find("h2")

    if series_title_h2:
        parts: List[str] = []
        stop_markers = {"se mere", "køb billetter", "film i serien"}
        for sib in series_title_h2.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h2", "h3"):
                break
            if hasattr(sib, "get_text"):
                text = sib.get_text(" ", strip=True)
            else:
                text = str(sib).strip()
            if not text:
                continue
            low = text.lower()
            if any(marker in low for marker in stop_markers):
                break
            parts.append(text)
        description = "\n\n".join(parts).strip()

    # Billede
    img = soup.select_one("img.picture__image")
    img_url = urljoin(BASE_URL, img["src"]) if img and img.get("src") else None

    return SeriesInfo(
        title=title,
        url=series_url,
        description=description,
        image_url=img_url,
        tickets=[],
    )


# ---------- Hovedfunktion til Streamlit ----------


def get_program_data(start_dt: datetime, end_dt: datetime) -> Dict:
    """
    Hoved-funktion som bruges af Streamlit-appen.
    Returnerer et dict med nøglerne "series" og "films" (se modul-docstring).
    """
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt

    film_links = _get_all_film_links()

    films: List[FilmInfo] = []
    series_map: Dict[str, SeriesInfo] = {}

    for film_url, fallback_title in film_links.items():
        film_info = scrape_film(film_url, start_dt, end_dt, fallback_title=fallback_title)
        if not film_info:
            continue

        films.append(film_info)

        # Hvis filmen er i en serie, så tilføj visningerne til serien
        if film_info.series_title and film_info.series_url:
            if film_info.series_url not in series_map:
                series_map[film_info.series_url] = scrape_series(film_info.series_url)
            serie = series_map[film_info.series_url]
            for s in film_info.screenings:
                serie.tickets.append(s)

    # Konverter dataklasser til almindelige dicts, som er nemme at bruge i Streamlit
    series_payload: List[Dict] = []
    for serie in series_map.values():
