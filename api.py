#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for async website_bot.py
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from website_bot import scrape_website
import asyncio

load_dotenv()

app = FastAPI(title="Website Scraper API")

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
async def scrape_endpoint(request: ScrapeRequest):
    url = request.url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        # Timeout-safe async scraping
        data = await asyncio.wait_for(scrape_website(url), timeout=90)
        return {"status": "success", "data": data}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Scraping timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.get("/")
async def root():
    return {"message": "✅ Website Scraper API is running fine!"}
