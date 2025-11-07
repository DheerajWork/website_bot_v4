#!/usr/bin/env python3
"""
api.py — FastAPI wrapper for website_bot.py
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from website_bot import scrape_website

load_dotenv()
app = FastAPI(title="Website Scraper API with RAG")

class ScrapeRequest(BaseModel):
    url: str

@app.post("/scrape")
def scrape_endpoint(request: ScrapeRequest):
    url = request.url.strip()
    try:
        data = scrape_website(url)
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def root():
    return {"message": "✅ Website Scraper API is running fine!"}
