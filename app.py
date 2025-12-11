import os
import re
import sys
import time
import json
from datetime import datetime, date
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, Response, send_from_directory

# ---------------- Konfiguration ----------------
BASE = "https://www.dfi.dk"
CALENDAR_PRIMARY = f"{BASE}/cinemateket/biograf/alle-film"
SERIES_INDEX_URL = f"{BASE}/cinemateket/biograf/filmserier"
EVENTS_INDEX_URL = f"{BASE}/cinemateket/biograf/events"

ALLOWED_HOSTS = {"www.dfi.dk", "dfi.dk"}
# Øget timeout for at undgå fejl ved langsom DFI svar
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "30"))
SLEEP_BETWEEN = float(os.environ.get("SCRAPE_SLEEP", "0.1"))
UA = "Mozilla/5.0 (compatible; CinemateketPrint/3.5; +https://www.dfi.dk/)"

app = Flask(__name__, static_folder=".", static_url_path="")

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
})

# ---------------- Utilities ----------------
MONTHS_DA = {
    "jan":1,"januar":1,"feb":2,"februar":2,"mar":3,"marts":3,"apr":4,"april":4,"maj":5,
    "jun":6,"juni":6,"jul":7,"juli":7,"aug":8,"august":8,"sep":9,"september":9,"okt":10,"oktober":10,
    "nov":11,"november":11,"dec":12,"december":12
}
DAY_RE = re.compile(r"^(Mandag|Tirsdag|Onsdag|Torsdag|Fredag|Lørdag|Søndag)\s+(\d{1,2})\.\s*(\w+)", re.I)

def log(*args):
    print("[APP]", *args, file=sys.stdout, flush=True)

def abs_url(href: str) -> str:
    try:
        return urljoin(BASE, href)
    except Exception:
        return href

def allowed(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and p.netloc in ALLOWED_HOSTS and p.path.startswith("/cinemateket/")
    except Exception:
        return False

def _bs(html_text: str) -> BeautifulSoup:
    return BeautifulSoup(html_text or "", "html.parser")

def get_soup(url: str) -> BeautifulSoup:
    for i in range(2): # Færre retries for hastighed
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return _bs(r.text)
            time.sleep(0.2)
        except requests.RequestException:
            time.sleep(0.2)
    return _bs("")

def today_iso() -> str:
    return date.today().isoformat()

def iso_from_label(label: str, year: int) -> str | None:
    m = DAY_RE.search(label.strip())
    if not m: return None
    day = int(m.group(2))
    mon = MONTHS_DA.get(m.group(3).lower())
    if not mon: return None
    try: return date(year, mon, day).isoformat()
    except ValueError: return None

def extract_title(doc: BeautifulSoup, url: str) -> str:
    h1 = doc.find("h1")
    if h1: return h1.get_text(strip=True)
    return "Titel"

def extract_body_block(doc: BeautifulSoup):
    for sel in [".field--name-field-body", ".field--name-body", "article", "main"]:
        node = doc.select_one(sel)
        if node: return node
    return doc

def extract_image(doc: BeautifulSoup) -> str | None:
    try:
        wrap = extract_body_block(doc)
        img = wrap.select_one("img") if wrap else None
        if not img: img = doc.select_one("article img, main img, img")
        if img and img.get("src"): return abs_url(img["src"])
    except Exception: pass
    return None

def split_description_and_credits(text: str) -> tuple[str, str]:
    """
    Avanceret splitter der flytter tekniske linjer til credits.
    """
    if not text: return "", ""
    
    # Markører der indikerer start på teknik-blok
    tech_starts = [
        "Instruktør:", "Medvirkende:", "Original titel:", "USA,", "Danmark,", 
        "Frankrig,", "Storbritannien,", "Sverige,", "Tyskland,", "min.", 
        "Dansk tale", "Tilladt for", "Stemmer:", "Manuskript:"
    ]
    
    lines = text.split('\n')
    synopsis_lines = []
    credits_lines = []
    is_credits = False

    for line in lines:
        l = line.strip()
        if not l: continue
        
        # Hvis vi allerede er i credits sektionen, fortsæt
        if is_credits:
            credits_lines.append(l)
            continue

        # Tjek om denne linje ligner starten på credits
        # 1. Starter med nøgleord
        if any(l.lower().startswith(kw.lower()) for kw in tech_starts):
            is_credits = True
            credits_lines.append(l)
            continue
            
        # 2. Indeholder årstal og land (typisk DFI format "USA, 1950")
        if re.search(r"[A-ZÆØÅ][a-zæøå]+,\s*(19|20)\d{2}", l):
            is_credits = True
            credits_lines.append(l)
            continue

        # 3. Hvis linjen er meget kort og ligner navne (risikabelt, men nødvendigt for "Wilfred Jackson...")
        # Vi antager at synopsis er sætninger. Credits er lister.
        # Hvis linjen ikke har verber eller punktum, og vi er langt nede? 
        # For nu holder vi os til de sikre markører for ikke at ødelægge synopsis.
        
        synopsis_lines.append(l)

    # Filtrer støj fra synopsis
    clean_synopsis = []
    blacklist = ["Gør dit lærred lidt bredere", "Læs mere", "Bestil billetter", "Køb billet"]
    for sl in synopsis_lines:
        if not any(b.lower() in sl.lower() for b in blacklist):
            clean_synopsis.append(sl)

    return "\n".join(clean_synopsis), ", ".join(credits_lines)

def canonical_title(raw: str) -> str:
    if not raw: return ""
    return re.sub(r"\s+", " ", re.sub(r"\s*\([^)]*\)\s*$", "", raw)).strip().lower()

def merge_dates(existing: list[str], incoming: list[str]) -> list[str]:
    s = set(existing or [])
    for dt in incoming or []:
        if dt: s.add(dt)
    return sorted(s)

def weekday_label_from_iso(iso_date: str) -> str:
    WEEKDAYS = ["Mandag","Tirsdag","Onsdag","Torsdag","Fredag","Lørdag","Søndag"]
    MONTHS_FULL = ['januar','februar','marts','april','maj','juni','juli','august','september','oktober','november','december']
    y, m, d = map(int, iso_date.split("-"))
    wd = WEEKDAYS[date(y, m, d).weekday()]
    return f"{wd} {d}. {MONTHS_FULL[m-1]}"

# ---------------- Core Logic ----------------

def build_series_registry() -> tuple[dict, dict]:
    """Henter serier for at få pæne overskrifter."""
    by_href, meta = {}, {}
    idx = get_soup(SERIES_INDEX_URL)
    
    # 1. Find alle serier
    anchors = idx.select('a[href*="/cinemateket/biograf/filmserier/serie/"]') or []
    seen = set()
    
    for a in anchors:
        s_url = abs_url(a.get("href", ""))
        if not s_url or s_url in seen: continue
        seen.add(s_url)
        
        # Hent serien
        try:
            sdoc = get_soup(s_url)
            sname = extract_title(sdoc, s_url).strip() or "Serie"
            
            # Hent info
            wrap = extract_body_block(sdoc)
            ps = [p.get_text(" ", strip=True) for p in (wrap.select("p") if wrap else [])]
            intro = "\n".join(ps[:3]) if ps else ""
            banner = extract_image(sdoc)
            
            meta[sname] = {"intro": intro, "banner": banner}
            
            # Find film i serien
            # Vi kigger efter links inde i seriens tekst/lister
            for it in sdoc.select('a[href*="/cinemateket/biograf/alle-film/film/"], a[href*="/cinemateket/biograf/events/event/"]'):
                ih = abs_url(it.get("href", ""))
                if allowed(ih): by_href[ih] = sname
                
        except Exception: pass
        time.sleep(SLEEP_BETWEEN) # Skån serveren
    
    return by_href, meta

def parse_calendar() -> list[dict]:
    """Scraper kalendervisningen for at få dato-strukturen."""
    doc = get_soup(CALENDAR_PRIMARY)
    # Find links til film/events
    cards = doc.select('a[href*="/cinemateket/biograf/alle-film/film/"], a[href*="/cinemateket/biograf/events/event/"]') or []
    
    day_map = {}
    cur_y = datetime.now().year

    # Helper til at parse dato-klumper som "4. - 10. januar" eller "Søndag 4. jan"
    def parse_chunk(text):
        out = []
        # Split ved bindestreg eller komma
        parts = [p.strip() for p in re.split(r"[,\u2013\-]+", text) if p.strip()]
        for p in parts:
            m = re.search(r"(\d{1,2})\.\s*([A-Za-zæøåÆØÅ]+)", p)
            if not m: continue
            d, mon_s = int(m.group(1)), m.group(2).lower()
            mon = MONTHS_DA.get(mon_s) or MONTHS_DA.get(mon_s[:3])
            if mon:
                try: out.append(date(cur_y, mon, d).isoformat())
                except: pass
        return out

    for a in cards:
        href = abs_url(a.get("href", ""))
        if not allowed(href): continue
        title = a.get_text(strip=True)
        
        # Find datoen i elementet ovenover (DFI struktur)
        date_text = ""
        el = a.parent
        hops = 0
        while el and hops < 5 and not date_text:
            txt = el.get_text(" ", strip=True)
            # Leder efter mønster "12. dec"
            if re.search(r"\d{1,2}\.\s*[A-Za-zæøåÆØÅ]+", txt): 
                date_text = txt
                break
            el = el.parent; hops += 1
        
        # Tilføj film til alle fundne datoer
        for iso in parse_chunk(date_text):
            day_map.setdefault(iso, []).append({"time":"00:00", "title":title, "href":href})

    return [{"label": weekday_label_from_iso(k), "entries": v} for k,v in sorted(day_map.items())]

def fetch_item_details(url: str) -> dict:
    """Henter detaljer fra en enkelt film/event side."""
    doc = get_soup(url)
    title = extract_title(doc, url)
    wrap = extract_body_block(doc)
    image = extract_image(doc)

    full_text = wrap.get_text("\n", strip=True) if wrap else ""
    synopsis, credits = split_description_and_credits(full_text)

    # 1. Hent ALLE specifikke datoer+tidspunkter fra siden
    # Vi leder efter mønsteret "13. dec 14:15"
    text_all = doc.get_text(" ", strip=True)
    datetimes = []
    cy = datetime.now().year
    
    # Regex: (Dag).(Måned) (Tid) -> "13. dec 14:15" eller "13. december kl. 14:15"
    patt = re.compile(r"(\d{1,2})\.\s*([A-Za-zæøåÆØÅ]+)(?:\s*(?:kl\.?|KL\.?)\s*)?(\d{1,2}:\d{2})", re.I)
    
    for g in patt.finditer(text_all):
        d, ms, tm = int(g.group(1)), g.group(2).lower(), g.group(3)
        mon = MONTHS_DA.get(ms) or MONTHS_DA.get(ms[:3])
        if mon:
            try: 
                # Håndter årsskifte: Hvis vi er i Nov/Dec og dato er Jan/Feb -> Næste år
                year = cy
                now_m = datetime.now().month
                if now_m >= 11 and mon <= 2:
                    year += 1
                elif now_m <= 2 and mon >= 11:
                    year -= 1 # Burde ikke ske for kommende program
                
                datetimes.append(f"{date(year, mon, d).isoformat()} {tm}")
            except: pass
    
    return {
        "title": title, 
        "synopsis": synopsis, 
        "credits": credits,
        "image": image, 
        "datetimes": sorted(set(datetimes)) # KUN dato+tid kombinationer, ingen løse tider
    }

# ---------------- Routes ----------------
@app.after_request
def add_headers(resp: Response):
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp

@app.get("/")
def index():
    return send_from_directory(".", "index.html")

@app.get("/program")
def program():
    try:
        mode = request.args.get("mode", "all")
        # Default til i dag hvis ingen startdato
        d_from = request.args.get("from", today_iso())
        d_to = request.args.get("to")

        by_href, meta = build_series_registry()
        days = parse_calendar()
        series_map = {}

        # Cache til detail-opslag så vi ikke henter samme side 2 gange
        detail_cache = {}

        for d in days:
            iso = iso_from_label(d["label"], datetime.now().year)
            if not iso: continue
            
            # Tjek datofilter
            if d_to: # Range mode
                if not (d_from <= iso <= d_to): continue
            else: # "All" mode / fremtid
                if iso < today_iso(): continue

            for e in d["entries"]:
                href = e["href"]
                sname = by_href.get(href, "Uden for serie")
                
                # Init serie container
                if sname not in series_map:
                    series_map[sname] = {
                        "intro": meta.get(sname,{}).get("intro",""),
                        "banner": meta.get(sname,{}).get("banner"),
                        "items": {}
                    }
                
                # Hent detaljer (med cache)
                if href in detail_cache:
                    det = detail_cache[href]
                else:
                    try: 
                        det = fetch_item_details(href)
                        detail_cache[href] = det
                    except: 
                        det = {"title":e.get("title"), "synopsis":"", "credits":"", "image":None, "datetimes":[]}
                
                title_eff = det.get("title") or e.get("title") or "Titel"
                canon = canonical_title(title_eff)

                # Find eksisterende item i denne serie
                existing_key = None
                for k,v in series_map[sname]["items"].items():
                    if v["canon"] == canon: existing_key = k; break
                
                # --- KRITISK RETTELSE HER ---
                # Vi skal finde ud af, hvornår filmen vises PÅ DENNE DAG (iso).
                # Vi kigger i det['datetimes'] som indeholder ALLE visninger (f.eks. "2025-12-13 14:15", "2025-12-21 16:00")
                # Vi tager KUN dem, der starter med dagens dato (iso).
                
                valid_times_for_today = []
                
                # Metode 1: Match præcis dato fra detail-siden
                for dt_full in det["datetimes"]:
                    if dt_full.startswith(iso):
                        valid_times_for_today.append(dt_full)
                
                # Metode 2: Hvis detail-siden fejlede med at parse datoer, men kalenderen sagde den var i dag...
                # Så indsætter vi datoen uden tid ("00:00") som fallback, så den i det mindste kommer med.
                # Men kun hvis vi SLET ingen tider fandt for dagen.
                if not valid_times_for_today and not det["datetimes"]:
                     valid_times_for_today.append(f"{iso} (Tid ukendt)")

                # Opdater item
                if existing_key:
                    it = series_map[sname]["items"][existing_key]
                    if not it["image"] and det["image"]: it["image"] = det["image"]
                    if not it["synopsis"] and det["synopsis"]: it["synopsis"] = det["synopsis"]
                    if not it["credits"] and det["credits"]: it["credits"] = det["credits"]
                    it["dates"] = merge_dates(it["dates"], valid_times_for_today)
                else:
                    if valid_times_for_today: # Kun opret hvis der er visninger
                        series_map[sname]["items"][href] = {
                            "canon": canon,
                            "url": href,
                            "title": title_eff,
                            "image": det.get("image"),
                            "synopsis": det.get("synopsis", ""),
                            "credits": det.get("credits", ""),
                            "dates": sorted(set(valid_times_for_today))
                        }
                
                time.sleep(SLEEP_BETWEEN)

        # Output generering
        out_series = []
        for name, data in series_map.items():
            its = list(data["items"].values())
            # Sorter datoer internt i hver film
            for i in its: i["dates"].sort()
            
            # Fjern film uden datoer (burde ikke ske pga logikken ovenfor, men for en sikkerheds skyld)
            its = [i for i in its if i["dates"]]
            
            if not its: continue
            
            # Sorter film i serien efter første visningsdato
            its.sort(key=lambda x: x["dates"][0])
            
            out_series.append({
                "name":name, 
                "intro":data["intro"], 
                "banner":data["banner"], 
                "items":its
            })
        
        # Sorter serier efter hvornår den første film i serien vises
        out_series.sort(key=lambda s: (s["items"][0]["dates"][0] if s["items"] else "9999"))
        
        return jsonify({
            "generated_at": datetime.utcnow().isoformat(),
            "scope": {"from":d_from, "to":d_to},
            "series": out_series
        })

    except Exception as e:
        log("ERROR:", e)
        return jsonify({"error":str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
