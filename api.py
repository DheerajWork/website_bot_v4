from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from website_bot import (
    get_site_urls,
    select_main_pages,
    fetch_page,
    clean_text,
    chunk_text,
    rag_extract,
    extract_email,
    extract_phone,
    extract_address,
    extract_social_links_from_html
)
from bs4 import BeautifulSoup
import json

app = FastAPI(title="Website Info Extractor API")

# ---------------- Request Model ----------------
class URLRequest(BaseModel):
    url: str

# ---------------- Root ----------------
@app.get("/")
def root():
    return {"message": "Website Info Extractor API is running 🚀"}

# ---------------- Scrape Endpoint ----------------
@app.post("/scrape")
def scrape(request: URLRequest):
    site_url = request.url.strip()
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' in request body")

    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        print(f"🔍 Fetching URLs for: {site_url}")
        all_urls = get_site_urls(site_url)
        main_pages = select_main_pages(all_urls, site_url)

        all_text = ""
        all_social = {
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter / X": ""
        }

        for page in main_pages:
            html = fetch_page(page)

            # Extract social media links
            page_social = extract_social_links_from_html(html)
            for k, v in page_social.items():
                if v and not all_social[k]:
                    all_social[k] = v

            # Clean text
            soup = BeautifulSoup(html, "html.parser")
            [s.extract() for s in soup(["script", "style", "noscript"])]
            all_text += " " + clean_text(soup.get_text(" ", strip=True))

        all_text = clean_text(all_text)
        chunks = chunk_text(all_text)

        # RAG extraction
        data = rag_extract(chunks, site_url)

        # Fallbacks for missing data
        data["Email"] = data.get("Email") or extract_email(all_text)
        data["Phone"] = data.get("Phone") or extract_phone(all_text)
        data["Address"] = data.get("Address") or extract_address(all_text)

        # Merge social media links
        for k, v in all_social.items():
            if v:
                data[k] = v

        # Ensure all keys exist
        defaults = {
            "Business Name": "",
            "About Us": "",
            "Main Services": [],
            "Description": "",
            "Email": "",
            "Phone": "",
            "Address": "",
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter / X": "",
            "URL": site_url
        }
        for k, v in defaults.items():
            if k not in data or not data[k]:
                data[k] = v

        return {
            "success": True,
            "message": "Scraping Successful",
            "data": data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping site: {str(e)}")
