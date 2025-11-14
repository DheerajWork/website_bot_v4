from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from website_bot import scrape_website

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
        # Scrape the website using latest website_bot.py
        result = scrape_website(site_url)

        # Ensure all key fields exist (fallback)
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
            if k not in result or not result[k]:
                result[k] = v

        return {
            "success": True,
            "message": "Scraping Successful",
            "data": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping site: {str(e)}")
