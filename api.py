#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for async website_bot.py
(Playwright Async compatible, await used for scraping)
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from website_bot import scrape_website  # async function

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
        # 🔹 Call async scrape_website with await
        data = await scrape_website(url)
        return {"status": "success", "data": data}
    except Exception as e:
        # Return full error for debugging if something goes wrong
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "✅ Website Scraper API is running fine!"}
