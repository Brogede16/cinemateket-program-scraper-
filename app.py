import streamlit as st
from datetime import date, datetime, time
from scraper import get_program_data

# ---------------------------------------------------------
# Page Config & CSS for Printing
# ---------------------------------------------------------
st.set_page_config(page_title="Cinemateket Program", layout="wide")

st.markdown("""
<style>
    @media print {
        /* Skjul UI elementer ved print */
        header, footer, .stButton, .stDateInput, [data-testid="stSidebar"], .block-container {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        button, .stAppDeployButton { display: none !important; }
        
        /* Typography for print */
        body { font-size: 11pt; color: black; font-family: sans-serif; }
        h1 { font-size: 20pt; margin-bottom: 10px; }
        h2 { font-size: 16pt; margin-top: 20px; border-bottom: 1px solid #ccc; }
        h3 { font-size: 14pt; margin-top: 10px; break-after: avoid; }
        p { font-size: 10pt; line-height: 1.4; }
        a { text-decoration: none; color: black; font-weight: bold; }
        
        /* Layout */
        .series-container { break-inside: avoid; page-break-inside: avoid; margin-bottom: 30px; }
        .film-grid { display: flex; flex-wrap: wrap; gap: 15px; }
        .film-card {
            width: 30%; /* 3 per row */
            border: 1px solid #eee;
            padding: 8px;
            break-inside: avoid;
        }
        .film-img {
            width: 100%;
            height: 120px;
            object-fit: cover;
            margin-bottom: 5px;
        }
    }
    
    /* Screen styling */
    .film-card {
        border: 1px solid #ddd;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 15px;
        height: 100%;
        background: white;
    }
    .film-img {
        width: 100%;
        height: 150px;
        object-fit: cover;
        border-radius: 3px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# UI Logic
# ---------------------------------------------------------

st.title("Cinemateket: Print-selv Program")
st.info("💡 Tip: Vælg en periode og tryk 'Hent Program'. Brug derefter browserens 'Print' funktion (Ctrl+P) og vælg 'Gem som PDF' for det bedste resultat.")

# Inputs
col1, col2 = st.columns(2)
start_d = col1.date_input("Start Dato", date.today())
end_d = col2.date_input("Slut Dato", date.today())

if st.button("Hent Program (Scrape DFI)"):
    if start_d > end_d:
        st.error("Start dato skal være før slut dato.")
    else:
        dt_start = datetime.combine(start_d, time.min)
        dt_end = datetime.combine(end_d, time.max)
        
        # Progress bar setup
        progress_text = "Forbinder til DFI..."
        my_bar = st.progress(0, text=progress_text)
        
        try:
            data = get_program_data(dt_start, dt_end, progress_callback=my_bar)
            my_bar.empty() # Clear progress bar when done
            
            series_list = data.get("series", [])
            film_list = data.get("films", [])
            
            st.success(f"Fandt {len(series_list)} serier og {len(film_list)} enkeltfilm.")
            
            # --- START PRINT LAYOUT ---
            
            if not series_list and not film_list:
                st.warning("Ingen visninger fundet i denne periode.")
            else:
                st.markdown(f"# Program: {start_d.strftime('%d.%m.%Y')} - {end_d.strftime('%d.%m.%Y')}")
                
                # 1. VIS SERIER
                if series_list:
                    for serie in series_list:
                        st.markdown("<div class='series-container'>", unsafe_allow_html=True)
                        st.header(serie['title'])
                        
                        # Layout: Image left, Text right
                        c1, c2 = st.columns([1, 4])
                        with c1:
                            if serie.get('image_url'):
                                st.image(serie['image_url'], use_column_width=True)
                        with c2:
                            desc = serie.get('description', '')
                            # Limit text length for print
                            st.markdown(f"*{desc[:600]}...*" if len(desc) > 600 else desc)
                        
                        st.subheader("Film i denne serie:")
                        
                        # Grid loop for films
                        films_in_series = serie['films']
                        cols_per_row = 3
                        
                        # Custom Grid Logic
                        for i in range(0, len(films_in_series), cols_per_row):
                            row_films = films_in_series[i:i+cols_per_row]
                            cols = st.columns(cols_per_row)
                            
                            for idx, film in enumerate(row_films):
                                with cols[idx]:
                                    img_html = f'<img src="{film["image_url"]}" class="film-img"/>' if film.get("image_url") else ""
                                    
                                    # Create screening links list
                                    dates_html = ""
                                    for s in film['screenings']:
                                        dates_html += f"<div>📅 <a href='{s['link']}'>{s['display_date']}</a></div>"

                                    st.markdown(f"""
                                    <div class="film-card">
                                        {img_html}
                                        <b>{film['title']}</b><br>
                                        <div style="font-size:0.9em; margin-bottom:5px;">{film['description'][:100]}...</div>
                                        {dates_html}
                                    </div>
                                    """, unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
                        st.divider()

                # 2. VIS ENKELTSTÅENDE FILM
                if film_list:
                    st.header("Øvrige Film & Events")
                    cols_per_row = 3
                    for i in range(0, len(film_list), cols_per_row):
                        row_films = film_list[i:i+cols_per_row]
                        cols = st.columns(cols_per_row)
                        
                        for idx, film in enumerate(row_films):
                            with cols[idx]:
                                img_html = f'<img src="{film["image_url"]}" class="film-img"/>' if film.get("image_url") else ""
                                dates_html = ""
                                for s in film['screenings']:
                                    dates_html += f"<div>📅 <a href='{s['link']}'>{s['display_date']}</a></div>"

                                st.markdown(f"""
                                <div class="film-card">
                                    {img_html}
                                    <b>{film['title']}</b><br>
                                    <div style="font-size:0.9em; margin-bottom:5px;">{film['description'][:100]}...</div>
                                    {dates_html}
                                </div>
                                """, unsafe_allow_html=True)
        
        except Exception as e:
            st.error(f"Der opstod en fejl: {e}")
