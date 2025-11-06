#!/usr/bin/env python3
"""
website_bot.py — Core website scraper module (Async, main pages deep scrape)
"""

import os, re, json, random, asyncio
from typing import Dict, List
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urljoin

# ---------------- Config ----------------
load_dotenv(override=True)

USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30

# ---------------- Helper functions ----------------
def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i + size]
        chunks.append(" ".join(chunk))
        i += size - overlap
    return chunks

def extract_email(text: str) -> str:
    m = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m[0] if m else ""

def extract_phone(text: str) -> str:
    m = re.findall(r"(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4})", text)
    return m[0] if m else ""

def extract_address(text: str) -> str:
    lines = text.splitlines()
    for line in lines:
        if any(ch.isdigit() for ch in line) and len(line.split()) > 3:
            return line.strip()
    return ""

# ---------------- Async Playwright ----------------
from playwright.async_api import async_playwright

async def fetch_page(url: str, headless: bool = USE_HEADLESS) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        html = ""
        try:
            await page.goto(url, timeout=45000)
            await asyncio.sleep(2 + random.random() * 2)
            html = await page.content()
        except Exception:
            html = ""
        finally:
            await page.close()
            await context.close()
            await browser.close()
    return html

async def fetch_main_pages(base_url: str) -> List[str]:
    """Return list of main pages URLs (home, about, contact)"""
    base_url = base_url.rstrip("/")
    return [
        base_url + "/", 
        urljoin(base_url, "/about"), 
        urljoin(base_url, "/contact")
    ]

# ---------------- RAG / AI Extraction (Optional) ----------------
try:
    import chromadb
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except Exception:
    chromadb = None
    OpenAI = None
    embedding_functions = None

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
chroma_client = chromadb.Client() if chromadb else None
openai_client = OpenAI(api_key=OPENAI_KEY) if OpenAI and OPENAI_KEY else None
openai_ef = (
    embedding_functions.OpenAIEmbeddingFunction(api_key=OPENAI_KEY, model_name="text-embedding-3-small")
    if embedding_functions and OPENAI_KEY else None
)

def rag_extract(chunks, url):
    if not openai_client or not openai_ef:
        return None
    coll = chroma_client.get_or_create_collection(
        "main_pages_rag_collection", embedding_function=openai_ef
    )
    for i, ch in enumerate(chunks):
        coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])
    query = "Extract Business Name, About Us, Main Services, Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL"
    res = coll.query(query_texts=[query], n_results=3)
    context_text = " ".join(res.get("documents", [[]])[0]) if res else " ".join(chunks[:3])
    prompt = f"""
You are a data extraction assistant. Extract clean JSON with:
Business Name, About Us, Main Services (list), Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL.
URL: {url}
Text: {context_text}
"""
    resp = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json","").replace("```","")
    try:
        return json.loads(raw)
    except:
        return {"raw_ai": raw}

# ---------------- Public Async Scrape ----------------
async def scrape_website(site_url: str) -> Dict:
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    main_pages = await fetch_main_pages(site_url)

    # Parallel fetch of all main pages
    tasks = [fetch_page(url) for url in main_pages]
    pages_html = await asyncio.gather(*tasks)

    all_text = ""
    for html in pages_html:
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script","style","noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        all_text += " " + text

    all_text = clean_text(all_text)
    chunks = chunk_text(all_text)

    data = rag_extract(chunks, site_url)
    if not data:
        data = {
            "Business Name": "",
            "About Us": "",
            "Main Services": [],
            "Email": extract_email(all_text),
            "Phone": extract_phone(all_text),
            "Address": extract_address(all_text),
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter / X": "",
            "Description": "",
            "URL": site_url,
        }

    print("✅ Scraping complete for:", site_url)
    return data
