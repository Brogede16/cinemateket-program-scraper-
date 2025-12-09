import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pandas as pd

def parse_danish_date(date_str, current_year=2025):
    day_map = {'man.': 'Monday', 'tirs.': 'Tuesday', 'ons.': 'Wednesday', 'tors.': 'Thursday', 
               'fre.': 'Friday', 'lør.': 'Saturday', 'søn.': 'Sunday'}
    month_map = {'jan.': 1, 'feb.': 2, 'mar.': 3, 'apr.': 4, 'maj': 5, 'jun.': 6, 
                 'jul.': 7, 'aug.': 8, 'sep.': 9, 'okt.': 10, 'nov.': 11, 'dec.': 12}
    
    parts = date_str.split()
    if len(parts) < 3:
        return None
    day_abbr = parts[0].lower()
    day_num = int(parts[1])
    month_abbr = parts[2].lower()
    time_str = parts[3] if len(parts) > 3 else '00:00'
    
    month = month_map.get(month_abbr, 12)
    dt = datetime(current_year, month, day_num)
    hour, minute = map(int, time_str.split(':'))
    return dt.replace(hour=hour, minute=minute)

def scrape_biograf(url='https://www.dfi.dk/cinemateket/biograf'):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    listings = []
    # Tilpas baseret på faktisk HTML (brug browser-inspect til classes)
    program_items = soup.find_all('div', class_='program-item')  # Hypotetisk; tilpas
    for item in program_items:
        date_time_str = item.find('p', class_='date-time').text or ''
        title = item.find('a').text or ''
        link = item.find('a', string='Køb billet')['href'] or ''
        series = item.find('span', class_='series').text or ''
        event_note = True if 'm.' in title or 'Event' in item.text else False
        dt = parse_danish_date(date_time_str)
        if dt and dt >= datetime.now():
            listings.append({'date': dt, 'film': title, 'series': series, 'link': link, 'event': event_note})
    return pd.DataFrame(listings)

def scrape_series(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.find('h1').text or 'Ukendt serie'
    description = soup.find('div', class_='series-description').get_text(separator='\n') if soup.find('div', class_='series-description') else ''
    tickets = []
    for item in soup.find_all('li', class_='ticket-item'):
        film_title = item.find('span', class_='film-title').text or ''
        date_time_str = item.find('span', class_='date-time').text or ''
        link = item.find('a', class_='ticket-link')['href'] or ''
        dt = parse_danish_date(date_time_str)
        event_note = True if 'm.' in film_title else False
        if dt and dt >= datetime.now():
            tickets.append({'film': film_title, 'date': dt, 'link': link, 'event': event_note})
    return {'title': title, 'description': description, 'tickets': tickets, 'films': []}  # Udvid med film-liste

def scrape_film(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    title = soup.find('h1').text or 'Ukendt film'
    description = '\n'.join([p.text for p in soup.find_all('p')[:2]]) or ''
    screenings = []
    for div in soup.find_all('div', class_='screening'):
        date_time_str = div.find('p', class_='date-time').text or ''
        link = div.find('a')['href'] or ''
        dt = parse_danish_date(date_time_str)
        event_note = True if 'Event' in div.text else False
        if dt and dt >= datetime.now():
            screenings.append({'title': title, 'date': dt, 'link': link, 'description': description, 'event': event_note})
    return [{'title': title, 'description': description, 'screenings': screenings}]

def get_program_data(start_date, end_date):
    df_biograf = scrape_biograf()
    series_urls = ['https://www.dfi.dk/cinemateket/biograf/filmserier/serie/europa-kontinentet-kalder']  # Tilføj flere via scraping af /filmserier
    series_data = [scrape_series(url) for url in series_urls]
    film_urls = ['https://www.dfi.dk/cinemateket/biograf/alle-film/film/cykeltyven-0', 'https://www.dfi.dk/cinemateket/biograf/alle-film/film/himlen-over-berlin']  # Tilføj flere
    film_data = [scrape_film(url) for url in film_urls]
    all_data = pd.concat([df_biograf] + [pd.DataFrame(s['tickets']) for s in series_data])
    filtered = all_data[(all_data['date'] >= start_date) & (all_data['date'] <= end_date)]
    return {'series': series_data, 'films': film_data, 'filtered': filtered}
