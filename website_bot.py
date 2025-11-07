#!/usr/bin/env python3
"""
website_bot.py — Async scraping + RAG extraction using OpenAI
"""

import re
import json
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import os
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


async def fetch_page_content(url: str) -> str:
    """Render page and return HTML content"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        content = await page.content()
        await browser.close()
        return content


def clean_text(text: str) -> str:
    """Clean unnecessary whitespace"""
    return re.sub(r"\s+", " ", text).strip()


def extract_text_by_tag(soup, tags: list):
    """Extract text from multiple HTML tags"""
    results = []
    for tag in tags:
        for element in soup.find_all(tag):
            text = clean_text(element.get_text())
            if text:
                results.append(text)
    return results


def generate_prompt(html_content: str, url: str) -> str:
    """
    Strong prompt to OpenAI GPT model to extract:
    Business Name, About Us, Main Services, Email, Phone, Address, Socials, Description, URL
    """
    prompt = f"""
You are an expert web data extractor. Extract all business info from the website HTML.
Website URL: {url}

HTML Content:
{html_content[:5000]}

Return ONLY a valid JSON object with these keys:
- Business Name
- About Us
- Main Services (list)
- Email
- Phone
- Address (dictionary with city/location keys)
- Facebook
- Instagram
- LinkedIn
- Twitter / X
- Description
- URL

Make it clean, avoid repetition, avoid HTML tags, and provide human-readable content.
"""
    return prompt


async def call_openai(prompt: str) -> dict:
    """Call OpenAI GPT API with RAG prompt"""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    json_data = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=json_data
        )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    return json.loads(text)


async def scrape_website(url: str) -> dict:
    """
    Main function: scrape website + extract structured data via GPT
    """
    if not url.startswith("http"):
        url = "https://" + url

    html_content = await fetch_page_content(url)
    soup = BeautifulSoup(html_content, "html.parser")

    # Optional: pre-extract emails / phones / socials as fallback
    emails = extract_text_by_tag(soup, ["a"])
    phones = extract_text_by_tag(soup, ["p", "span", "a"])
    
    prompt = generate_prompt(html_content, url)
    result = await call_openai(prompt)
    return result
