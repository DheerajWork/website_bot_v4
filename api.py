#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for website_bot.py (Async + RAG + GPT)
"""

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from website_bot import scrape_website  # async

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
        data = await scrape_website(url)
        return {"status":"success","data":data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.get("/")
async def root():
    return {"message":"✅ Website Scraper API is running!"}
