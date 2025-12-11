import streamlit as st
from datetime import date, datetime, time
from scraper import get_program_data

# ---------------------------------------------------------
# Konfiguration og CSS
# ---------------------------------------------------------
st.set_page_config(page_title="Cinemateket Program", layout="wide")

st.markdown("""
<style>
    /* UI Tweaks */
    .block-container { padding-top: 2rem; }
    
    /* Filmkort Design */
    .film-card {
        background-color: white;
        border: 1px solid #ddd;
        border-radius: 6px;
        padding: 10px;
        height: 100%;
        font-family: sans-serif;
    }
    .film-img {
        width: 100%;
        height: 150px;
        object-fit: cover;
        border-radius: 4px;
        margin-bottom: 8px;
    }
    .event-badge {
        background-color: #d9534f;
        color: white;
        padding: 2px 6px;
        font-size: 0.75rem;
        border-radius: 3px;
        text-transform: uppercase;
        font-weight: bold;
        display: inline-block;
        margin-bottom: 5px;
    }
    .ticket-link {
        display: block;
        margin-top: 5px;
        color: #0275d8;
        text-decoration: none;
        font-size: 0.85rem;
    }

    /* PRINT STYLES - Det vigtigste! */
    @media print {
        @page { size: A4; margin: 1cm; }
        
        /* Skjul Streamlit UI */
        header, footer, .stButton, .stDateInput, [data-testid="stSidebar"], .stProgress {
            display: none !important;
        }
        
        /* Nulstil layout til print */
        .block-container { 
            padding: 0 !important; 
            margin: 0 !important; 
            max-width: 100% !important;
        }
        
        body { 
            font-size: 10pt; 
            color: black; 
            background: white; 
        }

        h1 { font-size: 18pt; border-bottom: 2px solid #000; margin-bottom: 20px; }
        h2 { font-size: 14pt; margin-top: 20px; background-color: #f0f0f0; padding: 5px; break-after: avoid; }
        h3 { font-size: 12pt; break-after: avoid; }
        
        /* Tving billeder til at vises i print */
        img { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

        /* Grid hacks til print */
        .film-card { border: 1px solid #ccc; break-inside: avoid; margin-bottom: 10px; }
        
        a { text-decoration: none; color: black; }
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# Appens Logik
# ---------------------------------------------------------
st.title("🎬 Cinemateket: Program Generator")
st.write("Vælg datoer og hent programmet. Brug derefter **Ctrl+P** for at printe til PDF.")

col1, col2, col3 = st.columns([1,1,2])
start_d = col1.date_input("Start Dato", date.today())
end_d = col2.date_input("Slut Dato", date.today())

go_btn = col3.button("Hent Program (Scrape DFI)", type="primary")

if go_btn:
    if start_d > end_d:
        st.error("Slut dato skal være efter start dato.")
    else:
        # Konverter datoer
        dt_start = datetime.combine(start_d, time.min)
        dt_end = datetime.combine(end_d, time.max)
        
        # Progress bar
        p_bar = st.progress(0, text="Forbinder...")
        
        try:
            # Kør scraperen
            data = get_program_data(dt_start, dt_end, progress_callback=p_bar)
            p_bar.empty() # Fjern bar når færdig
            
            series_list = data.get("series", [])
            film_list = data.get("films", [])
            
            # Resultat
            if not series_list and not film_list:
                st.warning("Ingen visninger fundet i denne periode.")
            else:
                st.success(f"Fandt {len(series_list)} serier og {len(film_list)} film/events.")
                st.markdown("---")
                
                # Header til printet
                st.markdown(f"<h1>Program: {start_d.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}</h1>", unsafe_allow_html=True)
                
                # 1. SERIER
                if series_list:
                    for serie in series_list:
                        st.markdown(f"<h2>SERIE: {serie['title']}</h2>", unsafe_allow_html=True)
                        
                        # Info om serien
                        c1, c2 = st.columns([1, 4])
                        with c1:
                            if serie.get('image_url'):
                                st.image(serie['image_url'], use_column_width=True)
                        with c2:
                            desc = serie.get('description', '')
                            # Trunkér tekst
                            if len(desc) > 600: desc = desc[:600] + "..."
                            st.markdown(f"*{desc}*")
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        # Film Grid (3 kolonner)
                        films = serie['films']
                        for i in range(0, len(films), 3):
                            cols = st.columns(3)
                            batch = films[i:i+3]
                            
                            for idx, film in enumerate(batch):
                                with cols[idx]:
                                    img_html = f"<img src='{film['image_url']}' class='film-img'>" if film['image_url'] else ""
                                    evt_html = "<div class='event-badge'>Event</div>" if film['is_event'] else ""
                                    
                                    dates_html = ""
                                    for s in film['screenings']:
                                        link_txt = f"📅 {s['display_date']}"
                                        if s.get('is_sold_out'): link_txt += " (Udsolgt)"
                                        dates_html += f"<a href='{s['link']}' class='ticket-link'>{link_txt}</a>"

                                    st.markdown(f"""
                                    <div class="film-card">
                                        {img_html}
                                        {evt_html}
                                        <b>{film['title']}</b><br>
                                        <div style="font-size:0.8em; margin-bottom:5px;">{film['description'][:100]}...</div>
                                        {dates_html}
                                    </div>
                                    """, unsafe_allow_html=True)
                        
                        st.markdown("<hr style='break-after: page;'>", unsafe_allow_html=True)

                # 2. ENKELTFILM
                if film_list:
                    st.markdown("<h2>ØVRIGE FILM & EVENTS</h2>", unsafe_allow_html=True)
                    for i in range(0, len(film_list), 3):
                        cols = st.columns(3)
                        batch = film_list[i:i+3]
                        for idx, film in enumerate(batch):
                            with cols[idx]:
                                img_html = f"<img src='{film['image_url']}' class='film-img'>" if film['image_url'] else ""
                                evt_html = "<div class='event-badge'>Event</div>" if film['is_event'] else ""
                                
                                dates_html = ""
                                for s in film['screenings']:
                                    dates_html += f"<a href='{s['link']}' class='ticket-link'>📅 {s['display_date']}</a>"

                                st.markdown(f"""
                                <div class="film-card">
                                    {img_html}
                                    {evt_html}
                                    <b>{film['title']}</b><br>
                                    <div style="font-size:0.8em; margin-bottom:5px;">{film['description'][:100]}...</div>
                                    {dates_html}
                                </div>
                                """, unsafe_allow_html=True)
        
        except Exception as e:
            st.error(f"Der skete en fejl: {e}")
