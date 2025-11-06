#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for website_bot.scrape_website (async)
Includes timeout and simple validation.
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv
from website_bot import scrape_website

load_dotenv()

app = FastAPI(title="Website Scraper API (RAG-capable)")

# limit maximum scraping time (Railway may enforce its own limits)
MAX_SCRAPE_TIMEOUT = int(os.getenv("MAX_SCRAPE_TIMEOUT", "65"))  # seconds

class ScrapeRequest(BaseModel):
    url: str  # using plain string to allow non-HttpUrl values; you can change to HttpUrl for stricter validation

@app.post("/scrape")
async def scrape_endpoint(request: ScrapeRequest):
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Missing url")
    if not url.startswith("http"):
        url = "https://" + url
    try:
        # enforce timeout using asyncio.wait_for
        data = await asyncio.wait_for(scrape_website(url), timeout=MAX_SCRAPE_TIMEOUT)
        return {"status":"success", "data": data}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scraping timed out (increase MAX_SCRAPE_TIMEOUT or reduce load).")
    except Exception as e:
        # return error for debugging; you might want to hide full exception in production
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.get("/")
async def root():
    return {"message":"✅ Website Scraper API is running!"}

# run locally with: uvicorn api:app --host 0.0.0.0 --port 8000 --reload
