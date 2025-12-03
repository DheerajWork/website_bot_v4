from fastapi import FastAPI, HTTPException, APIRouter
from pydantic import BaseModel
from bs4 import BeautifulSoup
import importlib
import website_bot

importlib.reload(website_bot)

app = FastAPI(title="Website Info Extractor API")
router = APIRouter(prefix="/api")

class URLRequest(BaseModel):
    url: str

@router.post("/scrape")
def scrape(request: URLRequest):
    site_url = request.url.strip()
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url'")
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        all_urls = website_bot.get_site_urls(site_url)
        main_pages = website_bot.select_main_pages(all_urls, site_url)

        all_text = ""
        all_social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}
        logo_url_found = None

        for page in main_pages:
            html = website_bot.fetch_page(page)

            if not logo_url_found:
                logo = website_bot.extract_logo_url(html, page)
                if logo:
                    logo_url_found = logo

            page_social = website_bot.extract_social_links_from_html(html)
            for k, v in page_social.items():
                if v and not all_social[k]:
                    all_social[k] = v

            soup = BeautifulSoup(html, "html.parser")
            [s.extract() for s in soup(["script", "style", "noscript"])]
            all_text += " " + website_bot.clean_text(soup.get_text(" ", strip=True))

        all_text = website_bot.clean_text(all_text)
        chunks = website_bot.chunk_text(all_text)
        data = website_bot.rag_extract(chunks, site_url)

        data["Logo"] = logo_url_found or ""

        if not data.get("Email"):
            data["Email"] = website_bot.extract_all_emails(all_text)

        if not data.get("Phone"):
            data["Phone"] = website_bot.extract_all_phones(all_text)

        if not data.get("Address"):
            data["Address"] = website_bot.extract_all_addresses(all_text)

        for k, v in all_social.items():
            if v:
                data[k] = v

        defaults = {
            "Business Name": "",
            "About Us": "",
            "Main Services": [],
            "Description": "",
            "Email": [],
            "Phone": [],
            "Address": [],
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter / X": "",
            "Logo": "",
            "URL": site_url
        }
        for k, v in defaults.items():
            if k not in data or not data[k]:
                data[k] = v

        return {"success": True, "message": "Scraping Successful", "data": data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping site: {str(e)}")

app.include_router(router)
