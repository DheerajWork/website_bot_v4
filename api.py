from fastapi import FastAPI, HTTPException, APIRouter
from pydantic import BaseModel
from bs4 import BeautifulSoup
import importlib
import website_bot

# Reload to get latest changes
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
        all_html = ""
        all_social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}
        logo_url_found = None

        for page in main_pages:
            html = website_bot.fetch_page(page)
            all_html += " " + (html or "")

            if not logo_url_found:
                logo = website_bot.extract_logo_url(html, page)
                if logo:
                    logo_url_found = logo

            page_social = website_bot.extract_social_links_from_html(html)
            for k, v in page_social.items():
                if v and not all_social[k]:
                    all_social[k] = v

            soup = BeautifulSoup(html or "", "html.parser")
            [s.extract() for s in soup(["script", "style", "noscript"])]
            all_text += " " + website_bot.clean_text(soup.get_text(" ", strip=True))

        all_text = website_bot.clean_text(all_text)
        chunks = website_bot.chunk_text(all_text)
        data = website_bot.rag_extract(chunks, site_url)

        data["Logo"] = logo_url_found or ""

        # Extract and clean emails with deduplication
        extracted_emails = website_bot.extract_all_emails(all_text, all_html)
        existing_emails = data.get("Email", [])
        if isinstance(existing_emails, str):
            existing_emails = [existing_emails] if existing_emails else []
        all_emails = existing_emails + extracted_emails
        data["Email"] = website_bot.clean_email_list(all_emails)

        # Extract and clean phones with deduplication
        extracted_phones = website_bot.extract_all_phones(all_text)
        existing_phones = data.get("Phone", [])
        if isinstance(existing_phones, str):
            existing_phones = [existing_phones] if existing_phones else []
        all_phones = existing_phones + extracted_phones
        data["Phone"] = website_bot.clean_phone_list(all_phones)

        # Extract and clean addresses with deduplication
        extracted_addresses = website_bot.extract_all_addresses(all_text)
        existing_addresses = data.get("Address", [])
        if isinstance(existing_addresses, str):
            existing_addresses = [existing_addresses] if existing_addresses else []
        all_addresses = existing_addresses + extracted_addresses
        data["Address"] = website_bot.clean_address_list(all_addresses)

        # Add social links
        for k, v in all_social.items():
            if v:
                data[k] = v

        # Set defaults with proper empty values
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
            if k not in data:
                data[k] = v
            elif data[k] is None:
                data[k] = v
            elif k in ["Email", "Phone", "Address", "Main Services"]:
                # Ensure these are always lists
                if not isinstance(data[k], list):
                    data[k] = [data[k]] if data[k] else []

        return {"success": True, "message": "Scraping Successful", "data": data}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error scraping site: {str(e)}")


@router.get("/health")
def health_check():
    return {"status": "healthy", "message": "API is running"}


app.include_router(router)


# Run with: uvicorn api:app --reload --host 0.0.0.0 --port 8000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)