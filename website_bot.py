#!/usr/bin/env python3
"""
website_bot.py — Core website scraper module (Async)
"""

import os, re, json, random, urllib.parse, asyncio
from typing import Dict
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv(override=True)

USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30
MAX_PAGES = 20
USE_RAG = True  # GPT + RAG extraction

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

def extract_addresses(text: str):
    """Extract multiple addresses from text"""
    lines = text.splitlines()
    addresses = {}
    for line in lines:
        if any(ch.isdigit() for ch in line) and len(line.split()) > 3:
            parts = [p.strip() for p in line.split(",")]
            city = parts[-2] if len(parts) >= 2 else "Main"
            addresses[city] = line.strip()
    return addresses if addresses else extract_address(text)

def select_main_pages(urls: list):
    home = urls[0] if urls else ""
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    return list(filter(None, [home, about, contact]))

def extract_services_from_soup(soup):
    services = []
    if not soup:
        return services
    for li in soup.find_all("li"):
        text = clean_text(li.get_text(" ", strip=True))
        if 3 < len(text.split()) < 12:
            services.append(text)
    return services

def extract_social_links(soup):
    socials = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}
    if not soup:
        return socials
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "facebook.com" in href:
            socials["Facebook"] = href
        elif "instagram.com" in href:
            socials["Instagram"] = href
        elif "linkedin.com" in href:
            socials["LinkedIn"] = href
        elif "twitter.com" in href or "x.com" in href:
            socials["Twitter / X"] = href
    return socials

# ---------------- Async Playwright ----------------
from playwright.async_api import async_playwright

async def fetch_page(url: str, headless: bool = USE_HEADLESS) -> str:
    """Load a webpage and return its HTML (Async)"""
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

async def crawl_site(base_url: str, max_pages=MAX_PAGES) -> list:
    visited, queue = set(), [base_url.rstrip("/")]
    site_structure = []
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        html = await fetch_page(url)
        site_structure.append(url)
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:")):
                continue
            full_url = urllib.parse.urljoin(base_url, href.split("#")[0])
            if full_url.startswith(base_url):
                links.add(full_url.rstrip("/"))
        for l in links:
            if l not in visited and l not in queue and len(visited) + len(queue) < max_pages:
                queue.append(l)
        visited.add(url)
    return site_structure

# ---------------- RAG / GPT ----------------
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

async def rag_extract(chunks, url):
    if not openai_client or not openai_ef:
        return None
    coll = chroma_client.get_or_create_collection(
        "three_page_rag_collection", embedding_function=openai_ef
    )
    for i, ch in enumerate(chunks):
        coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])
    query = "Extract structured company info as JSON with business name, about us, main services, emails, phones, multiple addresses, social links, description, URL"
    res = coll.query(query_texts=[query], n_results=3)
    context_text = " ".join(res.get("documents", [[]])[0]) if res else " ".join(chunks[:3])

    prompt = f"""
You are a professional data extraction assistant. 
Extract all company details from the following text and return STRICT JSON ONLY:

Keys: 
- Business Name
- About Us
- Main Services (list)
- Email
- Phone
- Address (if multiple locations, return as JSON with city names as keys)
- Facebook
- Instagram
- LinkedIn
- Twitter / X
- Description
- URL

Text: {context_text}
URL: {url}

Return ONLY valid JSON, no explanations.
"""
    resp = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```json", "", raw)
    raw = re.sub(r"```$", "", raw)
    try:
        return json.loads(raw)
    except:
        return {"raw_ai": raw}

# ---------------- Public Async Scrape ----------------
async def scrape_website(site_url: str) -> Dict:
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    all_urls = await crawl_site(site_url, max_pages=MAX_PAGES)
    main_pages = select_main_pages(all_urls)

    all_text = ""
    combined_soup = None
    for page_url in main_pages:
        html = await fetch_page(page_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for s in soup(["script","style","noscript","header","footer","nav"]):
            s.extract()
        main_block = soup.find("main") or soup.find("section") or soup.find("div", {"id":"content"}) or soup
        all_text += clean_text(main_block.get_text(" ", strip=True))
        combined_soup = main_block

    all_text = clean_text(all_text)
    chunks = chunk_text(all_text)

    data = await rag_extract(chunks, site_url)
    if data:
        return data

    # fallback
    services = extract_services_from_soup(combined_soup)
    socials = extract_social_links(combined_soup)
    return {
        "Business Name": "",
        "About Us": all_text[:500],
        "Main Services": services[:10], 
        "Email": extract_email(all_text),
        "Phone": extract_phone(all_text),
        "Address": extract_addresses(all_text),
        "Facebook": socials.get("Facebook",""),
        "Instagram": socials.get("Instagram",""),
        "LinkedIn": socials.get("LinkedIn",""),
        "Twitter / X": socials.get("Twitter / X",""),
        "Description": all_text[:300],
        "URL": site_url
    }
