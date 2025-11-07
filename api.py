from fastapi import FastAPI, HTTPException, Request
from concurrent.futures import ThreadPoolExecutor
import asyncio
from website_bot import scrape_website

app = FastAPI(title="Website Data Scraper API")

executor = ThreadPoolExecutor(max_workers=1)

@app.get("/")
async def home():
    return {"message": "✅ Website Scraper API is running successfully."}

@app.post("/scrape")
async def scrape(request: Request):
    try:
        body = await request.json()
        url = body.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="Missing 'url' field in request body")

        # Run scrape_website in background thread to avoid blocking event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, scrape_website, url)

        return {"status": "success", "data": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
