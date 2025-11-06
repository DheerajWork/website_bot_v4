#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for async website_bot.py
Updated for 3-pages deep scraping with Playwright Async
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from website_bot import scrape_website  # async 3-page deep scrape

# Load environment variables
load_dotenv()

app = FastAPI(title="Website Scraper API")

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape_endpoint(request: ScrapeRequest):
    """
    POST /scrape
    Body: {"url": "https://example.com"}
    """
    url = request.url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    try:
        # 🔹 Use asyncio.wait_for to prevent infinite hanging (timeout in seconds)
        data = await asyncio.wait_for(scrape_website(url), timeout=60)
        return {"status": "success", "data": data}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scraping timed out. Try again later.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "✅ Website Scraper API is running fine!"}
