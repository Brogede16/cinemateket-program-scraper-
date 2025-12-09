import streamlit as st
from datetime import date, datetime
import pandas as pd
from scraper import get_program_data

# Side-opsætning
st.set_page_config(page_title="Cinemateket programudtræk", layout="wide")
st.title("Cinemateket – programudtræk")

st.write(
    "Vælg en periode, så henter vi serier og visninger i Cinematekets program "
    "for kun de datoer, du har valgt. Udtrækket er tænkt som et printvenligt overblik."
)

# Dato-input
col1, col2 = st.columns(2)
start_date = col1.date_input("Startdato", value=date.today())
end_date = col2.date_input("Slutdato", value=date.today())

if start_date > end_date:
    st.error("Startdato kan ikke være efter slutdato. Ret datoerne.")
else:
    if st.button("Hent program"):
        with st.spinner("Henter program og genererer udtræk..."):
            data = get_program_data(
                datetime.combine(start_date, datetime.min.time()),
                datetime.combine(end_date, datetime.max.time()),
            )

        # --- SERIER ---
        st.header("Serier")

        series_list = data.get("series", [])
        if not series_list:
            st.info("Ingen serier fundet i den valgte periode.")
        else:
            for serie in series_list:
                title = serie.get("title", "Ukendt serie")
                description = serie.get("description", "")

                with st.expander(title, expanded=False):
                    # Beskrivelse – hvis din scraper returnerer HTML, brug unsafe_allow_html=True
                    if description:
                        st.markdown(description, unsafe_allow_html=True)
                    else:
                        st.write("Ingen beskrivelse tilgængelig.")

                    tickets = serie.get("tickets", []) or []
                    if not tickets:
                        st.write("Ingen visninger i den valgte periode.")
                    else:
                        films_df = pd.DataFrame(tickets)

                        # Sørg for at 'date' er datetime-objekter
                        if "date" in films_df.columns:
                            films_df["date"] = pd.to_datetime(films_df["date"])

                        # Vis i 3-kolonne grid
                        for i in range(0, len(films_df), 3):
                            cols = st.columns(3)
                            for j in range(3):
                                if i + j < len(films_df):
                                    row = films_df.iloc[i + j]
                                    with cols[j]:
                                        film_title = row.get("film", "Ukendt film")
                                        dt = row.get("date", None)
                                        link = row.get("link", "")
                                        is_event = bool(row.get("event", False))

                                        st.subheader(film_title)

                                        if isinstance(dt, (datetime, pd.Timestamp)):
                                            st.write(dt.strftime("%d.%m.%Y kl. %H:%M"))
                                        elif isinstance(dt, str):
                                            st.write(dt)
                                        else:
                                            st.write("Ukendt tidspunkt")

                                        if link:
                                            st.markdown(f"[Køb billet]({link})")

                                        if is_event:
                                            st.markdown(
                                                "<span class='event-pill'>EVENT</span>",
                                                unsafe_allow_html=True,
                                            )

        # --- ENKELTFILM / ØVRIGE VISNINGER ---
        st.header("Enkeltfilm og øvrige visninger")

        films_data = data.get("films", [])
        all_screenings = []

        # Forventet struktur: hvert element i data['films'] er fx:
        # {'title': ..., 'description': ..., 'screenings': [ { 'date': ..., 'link': ..., 'event': ... }, ... ]}
        for film in films_data:
            screenings = film.get("screenings", []) or []
            for sc in screenings:
                sc_copy = sc.copy()
                sc_copy.setdefault("title", film.get("title", "Ukendt film"))
                sc_copy.setdefault("description", film.get("description", ""))
                all_screenings.append(sc_copy)

        if not all_screenings:
            st.info("Ingen enkeltfilm/øvrige visninger fundet i den valgte periode.")
        else:
            films_df = pd.DataFrame(all_screenings)

            if "date" in films_df.columns:
                films_df["date"] = pd.to_datetime(films_df["date"])

            for i in range(0, len(films_df), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(films_df):
                        row = films_df.iloc[i + j]
                        with cols[j]:
                            title = row.get("title", "Ukendt film")
                            desc = row.get("description", "")
                            dt = row.get("date", None)
                            link = row.get("link", "")
                            is_event = bool(row.get("event", False))

                            st.subheader(title)

                            if desc:
                                # Vis kun kort preview
                                preview = desc[:200] + ("..." if len(desc) > 200 else "")
                                st.write(preview)

                            if isinstance(dt, (datetime, pd.Timestamp)):
                                st.write(dt.strftime("%d.%m.%Y kl. %H:%M"))
                            elif isinstance(dt, str):
                                st.write(dt)
                            else:
                                st.write("Ukendt tidspunkt")

                            if link:
                                st.markdown(f"[Køb billet]({link})")

                            if is_event:
                                st.markdown(
                                    "<span class='event-pill'>EVENT</span>",
                                    unsafe_allow_html=True,
                                )

# Printvenlig CSS
st.markdown(
    """
    <style>
    /* Lille pill til EVENT */
    .event-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid #444;
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 4px;
    }

    @media print {
        /* Skjul interaktive elementer */
        button, .stButton, .stDateInput, header, footer {
            display: none !important;
        }
        body {
            color: black !important;
            background: white !important;
        }
        .stExpander {
            border: none !important;
        }
        .css-18ni7ap, .css-1avcm0n {  /* nogle af Streamlits margin-klasser kan fjernes */
            margin: 0 !important;
            padding: 0 !important;
        }
    }
    </style>
""",
    unsafe_allow_html=True,
)
