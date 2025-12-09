import streamlit as st
from datetime import date, datetime
import pandas as pd
from scraper import parse_danish_date, scrape_biograf, scrape_series, scrape_film, get_program_data

st.title('Cinemateket Program Udtræk')

# Dato-input
col1, col2 = st.columns(2)
start_date = col1.date_input('Start dato', value=date.today())
end_date = col2.date_input('Slut dato', value=date.today())

if st.button('Hent program'):
    data = get_program_data(datetime.combine(start_date, datetime.min.time()), 
                            datetime.combine(end_date, datetime.max.time()))
    
    # Vis serier
    st.header('Serier')
    for serie in data['series']:
        with st.expander(serie['title']):
            st.write(serie['description'])
            # Grid for film i serie (2-3 kolonner)
            films_df = pd.DataFrame(serie['tickets'])
            if not films_df.empty:
                for i in range(0, len(films_df), 3):
                    cols = st.columns(3)
                    for j in range(3):
                        if i + j < len(films_df):
                            row = films_df.iloc[i + j]
                            with cols[j]:
                                st.subheader(row['film'])
                                st.write(row['date'].strftime('%d %b %Y %H:%M'))
                                st.markdown(f"[Køb billet]({row['link']})")
                                if row.get('event'): st.badge('Event', 'secondary')

    # Vis enkeltfilm
    st.header('Enkeltfilm')
    films_df = pd.DataFrame([f for film in data['films'] for f in film['screenings']])  # Flad ud
    if not films_df.empty:
        for i in range(0, len(films_df), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(films_df):
                    row = films_df.iloc[i + j]
                    with cols[j]:
                        st.subheader(row.get('title', 'Ukendt'))
                        st.write(row.get('description', '')[:100] + '...')
                        st.write(row['date'].strftime('%d %b %Y %H:%M'))
                        st.markdown(f"[Køb billet]({row['link']})")
                        if row.get('event'): st.badge('Event', 'secondary')

# Printvenlig CSS
st.markdown("""
    <style>
    @media print {
        .stButton, .stDateInput { display: none; }
        body { color: black; background: white; }
        .stExpander { border: none; }
    }
    </style>
""", unsafe_allow_html=True)
