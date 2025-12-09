# Cinemateket Program Scraper

En Streamlit-app til at scrape og vise Cinemateket's filmprogram for en given periode, med printvenlig visning.

## Installation og Kørsel
- Denne app kører på Streamlit og scraper data fra dfi.dk.
- For at teste: Deploy til Render.com (se nedenfor).

## Deployment til Render.com
1. Opret konto på render.com.
2. Opret ny "Web Service" og vælg dette GitHub-repo.
3. Vælg runtime: Python.
4. Build command: `pip install -r requirements.txt`
5. Start command: `streamlit run app.py --server.port 10000`
6. Deploy!

Bemærk: Scraping er til internt brug – kontakt DFI for tilladelse.
