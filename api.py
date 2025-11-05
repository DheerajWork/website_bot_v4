#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for website_bot.py (Secure, Env-Safe)
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from website_bot import scrape_website
from dotenv import load_dotenv

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
        # Call scrape_website function (already returns JSON dict)
        data = scrape_website(url)
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """Health check route"""
    return {"message": "Website Scraper API is running."}
