import streamlit as st
from datetime import date, datetime
from scraper import get_program_data

# ---------------------------------------------------------
# Basis-opsætning af siden
# ---------------------------------------------------------
st.set_page_config(page_title="Cinemateket programudtræk", layout="wide")

st.title("Cinemateket – programudtræk")

st.write(
    "Vælg en periode, så henter vi serier og visninger i Cinematekets program "
    "for kun de datoer, du har valgt. Udtrækket er tænkt som et printvenligt overblik "
    "– både til intern brug og til fx at sende til samarbejdspartnere."
)

# ---------------------------------------------------------
# Dato-input
# ---------------------------------------------------------
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

        series_data = data.get("series", []) or []
        films_data = data.get("films", []) or []

        if not series_data and not films_data:
            st.info("Ingen visninger fundet i den valgte periode.")
        else:
            # -------------------------------------------------
            # Sektion: Serier
            # -------------------------------------------------
            if series_data:
                st.header("Serier med visninger i perioden")
                st.write(
                    "Herunder vises alle serier, der har visninger i den valgte periode. "
                    "Under hver serie kan du se de konkrete filmvisninger med tid og billetlink."
                )

                for serie in series_data:
                    title = serie.get("title", "Ukendt serie")
                    description = serie.get("description", "").strip()
                    image_url = serie.get("image_url")
                    tickets = serie.get("tickets", [])

                    # Sortér visninger efter dato
                    tickets = sorted(
                        tickets,
                        key=lambda t: t.get("date") or datetime(2100, 1, 1),
                    )

                    with st.expander(title, expanded=False):
                        # Serie-beskrivelse
                        if image_url:
                            img_col, txt_col = st.columns([1, 2])
                            with img_col:
                                st.image(image_url, use_column_width=True)
                            with txt_col:
                                if description:
                                    st.write(description)
                        else:
                            if description:
                                st.write(description)

                        if not tickets:
                            st.write("Ingen visninger i den valgte periode.")
                        else:
                            st.subheader("Visninger i perioden")

                            # Grid i rækker af 3 visninger
                            for i in range(0, len(tickets), 3):
                                cols = st.columns(3)
                                for j in range(3):
                                    idx = i + j
                                    if idx >= len(tickets):
                                        break
                                    t = tickets[idx]
                                    with cols[j]:
                                        film_title = t.get("film", "Ukendt film")
                                        dt = t.get("date")
                                        link = t.get("link")
                                        is_event = bool(t.get("event"))

                                        st.markdown(f"**{film_title}**")

                                        if isinstance(dt, datetime):
                                            st.write(dt.strftime("%d.%m.%Y kl. %H:%M"))

                                        if is_event:
                                            st.caption("Event")

                                        if link:
                                            st.markdown(f"[Køb billet]({link})")

            # -------------------------------------------------
            # Sektion: Enkeltfilm (alle film uanset serie)
            # -------------------------------------------------
            if films_data:
                st.header("Enkeltfilm i perioden")
                st.write(
                    "Herunder vises et samlet overblik over alle filmvisninger i perioden, "
                    "uanset om de er en del af en serie eller ej."
                )

                # Flad liste med screenings, så vi kan lave ét samlet grid
                flat_screenings = []
                for film in films_data:
                    film_title = film.get("title", "Ukendt film")
                    film_desc = (film.get("description") or "").strip()
                    film_image = film.get("image_url")
                    film_url = film.get("url")
                    for s in film.get("screenings", []):
                        dt = s.get("date")
                        link = s.get("link")
                        is_event = bool(s.get("event"))

                        flat_screenings.append(
                            {
                                "title": film_title,
                                "description": film_desc,
                                "image_url": film_image,
                                "film_url": film_url,
                                "date": dt,
                                "link": link,
                                "event": is_event,
                            }
                        )

                # Sortér efter dato
                flat_screenings = sorted(
                    flat_screenings,
                    key=lambda s: s.get("date") or datetime(2100, 1, 1),
                )

                if not flat_screenings:
                    st.write("Ingen enkeltfilm i perioden.")
                else:
                    # Grid i rækker af 3 film
                    for i in range(0, len(flat_screenings), 3):
                        cols = st.columns(3)
                        for j in range(3):
                            idx = i + j
                            if idx >= len(flat_screenings):
                                break
                            item = flat_screenings[idx]
                            with cols[j]:
                                title = item.get("title", "Ukendt film")
                                desc = item.get("description", "")
                                img = item.get("image_url")
                                dt = item.get("date")
                                link = item.get("link")
                                is_event = bool(item.get("event"))
                                film_url = item.get("film_url")

                                if img:
                                    st.image(img, use_column_width=True)

                                st.markdown(f"### {title}")

                                if dt and isinstance(dt, datetime):
                                    st.write(dt.strftime("%d.%m.%Y kl. %H:%M"))

                                if is_event:
                                    st.caption("Event")

                                # Kort tekst – så print ikke bliver alt for langt
                                if desc:
                                    kort = (desc[:280] + "…") if len(desc) > 280 else desc
                                    st.write(kort)

                                if link:
                                    st.markdown(f"[Køb billet]({link})")
                                elif film_url:
                                    st.markdown(f"[Læs mere]({film_url})")

# ---------------------------------------------------------
# Printvenlig CSS
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    /* Gør layout mere printvenligt */
    @media print {
        header, footer, .stButton, .stDateInput, .stSidebar {
            display: none !important;
        }
        .block-container {
            padding: 0 1rem !important;
        }
        body {
            color: black !important;
            background: white !important;
        }
        .stExpander {
            border: none !important;
            box-shadow: none !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
