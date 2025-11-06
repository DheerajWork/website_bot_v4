#!/usr/bin/env python3
"""
website_bot.py — Robust async scraper optimized for Railway.

Features:
- Async Playwright fetch with realistic UA and headful fallback.
- Semaphore to limit concurrent browsers (good for Railway).
- Targeted extraction from home/about/contact (main content).
- Chunking + optional ChromaDB + OpenAI embeddings + GPT (RAG) if OPENAI_API_KEY present.
- Safe fallbacks (regex + DOM heuristics) so you always get structured output.
"""

import os
import re
import json
import time
import random
import asyncio
import urllib.parse
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(override=True)

# ----------- Config (tweak via env) -----------
USE_HEADLESS = True
FORCE_HEADFUL = os.getenv("FORCE_HEADFUL", "false").lower() in ("1", "true", "yes")
MAX_PAGES = int(os.getenv("MAX_PAGES", "5"))  # how many pages to consider when discovering (keeps flexible)
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "45000"))
FETCH_RETRIES = int(os.getenv("FETCH_RETRIES", "1"))
BROWSER_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "1"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "300"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))

# ----------- Helpers -----------
def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i:i + size]))
        i += size - overlap
    return chunks

def extract_email(text: str) -> str:
    m = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return m[0] if m else ""

def extract_phone(text: str) -> str:
    # broad capture for international/local formats
    m = re.findall(r"(\+?\d[\d\s\-\(\)]{6,}\d)", text)
    return m[0].strip() if m else ""

def extract_address(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        if any(ch.isdigit() for ch in line) and len(line.split()) > 3:
            return line
    return ""

def extract_social_links(soup: BeautifulSoup) -> Dict[str, str]:
    out = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "facebook.com" in href and not out["Facebook"]:
            out["Facebook"] = href
        if "instagram.com" in href and not out["Instagram"]:
            out["Instagram"] = href
        if "linkedin.com" in href and not out["LinkedIn"]:
            out["LinkedIn"] = href
        if "twitter.com" in href or "x.com" in href and not out["Twitter / X"]:
            out["Twitter / X"] = href
    return out

def extract_services_from_soup(soup: BeautifulSoup) -> List[str]:
    services = []
    # Gather bullets from lists
    for ul in soup.find_all("ul"):
        for li in ul.find_all("li"):
            text = clean_text(li.get_text(" ", strip=True))
            if 2 <= len(text.split()) <= 12:
                services.append(text)
    # Look for headings mentioning services
    for h in soup.find_all(["h2","h3","h4"]):
        htxt = clean_text(h.get_text(" ", strip=True)).lower()
        if any(k in htxt for k in ("service","what we","offer","solutions","products")):
            # collect next sibling paragraphs / lists (up to 3 siblings)
            sib = h.find_next_sibling()
            steps = 0
            while sib and steps < 3:
                if sib.name == "ul":
                    services += [clean_text(li.get_text(" ", strip=True)) for li in sib.find_all("li")]
                else:
                    txt = clean_text(sib.get_text(" ", strip=True))
                    if 3 <= len(txt.split()) <= 12:
                        services.append(txt)
                sib = sib.find_next_sibling()
                steps += 1
    # dedupe while preserving order
    seen = set()
    out = []
    for s in services:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out

# ----------- Playwright fetching with anti-blocking strategies -----------
from playwright.async_api import async_playwright

# realistic UA
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_browser_sema = asyncio.Semaphore(BROWSER_CONCURRENCY)

async def _fetch_once(url: str, headless: bool, ua: str) -> str:
    html = ""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox"])
            context = await browser.new_context(viewport={"width":1280,"height":800}, user_agent=ua)
            # reduce webdriver fingerprint
            try:
                await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            except Exception:
                pass
            page = await context.new_page()
            try:
                await page.goto(url, timeout=PAGE_TIMEOUT_MS)
                # wait a bit for JS-rendered content
                await asyncio.sleep(2 + random.random()*2)
                html = await page.content()
            finally:
                await page.close()
                await context.close()
                await browser.close()
    except Exception as e:
        html = ""
    return html

async def fetch_page(url: str) -> str:
    """
    Fetch with retries. If CloudFront-like response (403 / "request could not be satisfied")
    detected, retry with headful + same UA.
    """
    ua = DEFAULT_UA
    headless_pref = USE_HEADLESS and not FORCE_HEADFUL
    last_html = ""
    for attempt in range(FETCH_RETRIES + 1):
        async with _browser_sema:
            html = await _fetch_once(url, headless=headless_pref, ua=ua)
        if not html:
            last_html = ""
        else:
            last_html = html
            # crude anti-block detection
            lower = html.lower()
            if "request could not be satisfied" in lower or "access denied" in lower or "blocked" in lower or "cloudfront" in lower:
                # try headful once
                if headless_pref:
                    headless_pref = False
                    # small delay before retrying headful
                    await asyncio.sleep(1 + random.random()*1.5)
                    continue
            # otherwise successful-ish
            break
        # slight backoff
        await asyncio.sleep(1 + random.random()*1.5)
    return last_html

# ----------- Crawl / main page selection -----------
async def crawl_site(base_url: str, max_pages: int = MAX_PAGES) -> List[str]:
    """
    Collect up to `max_pages` URLs from the site (home + about + contact preferred).
    """
    base = base_url.rstrip("/")
    urls = [base]
    html = await fetch_page(base)
    if not html:
        return urls
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:")):
            continue
        full = urllib.parse.urljoin(base, href.split("#")[0]).rstrip("/")
        if full.startswith(base) and full not in urls:
            urls.append(full)
        if len(urls) >= max_pages:
            break
    return urls

def select_main_pages(urls: List[str]) -> List[str]:
    home = urls[0] if urls else ""
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    chosen = []
    for u in (home, about, contact):
        if u and u not in chosen:
            chosen.append(u)
    return chosen

# ----------- RAG / OpenAI integration (optional) -----------
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
USE_RAG = bool(OPENAI_KEY)

if USE_RAG:
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        from openai import OpenAI
        chroma_client = chromadb.Client()
        openai_client = OpenAI(api_key=OPENAI_KEY)
        openai_ef = embedding_functions.OpenAIEmbeddingFunction(api_key=OPENAI_KEY, model_name="text-embedding-3-small")
    except Exception as e:
        # If imports fail, disable RAG gracefully
        USE_RAG = False
        chroma_client = None
        openai_client = None
        openai_ef = None

async def rag_extract(chunks: List[str], url: str) -> Optional[Dict]:
    """
    Use ChromaDB + OpenAI to run RAG and ask GPT to return structured JSON.
    Returns dict if successful, else None.
    """
    if not USE_RAG or not chroma_client or not openai_client or not openai_ef:
        return None
    try:
        coll = chroma_client.get_or_create_collection("website_scraper_collection", embedding_function=openai_ef)
        # add (overwrite safe for this demo)
        for i, ch in enumerate(chunks):
            try:
                coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])
            except Exception:
                pass
        # query top docs
        res = coll.query(query_texts=["Extract the most relevant content for company info."], n_results=RAG_TOP_K)
        docs = res.get("documents", [[]])[0]
        context_text = " ".join(docs) if docs else " ".join(chunks[:min(len(chunks),3)])
        prompt = f"""
You are a data extraction assistant. Return STRICT JSON with the keys:
Business Name, About Us, Main Services (list), Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL.

URL: {url}
Text: {context_text}
Return only valid JSON (no explanations).
"""
        resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            temperature=0,
            request_timeout=30
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json", "", raw)
        raw = re.sub(r"```$", "", raw)
        out = json.loads(raw)
        return out
    except Exception:
        return None

# ----------- Public scrape function -----------
async def scrape_website(site_url: str) -> Dict:
    """
    Main entry. Returns structured dict. Uses RAG if OPENAI_API_KEY is set, else falls back to heuristics.
    """
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    # discover pages and select main ones
    discovered = await crawl_site(site_url, max_pages=MAX_PAGES)
    main_pages = select_main_pages(discovered)

    combined_text = ""
    about_text = ""
    contact_text = ""
    home_text = ""
    combined_soup = None

    for page_url in main_pages:
        html = await fetch_page(page_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        # remove noisy elements
        for el in soup(["script","style","noscript","header","footer","nav"]):
            el.extract()
        main_block = soup.find("main") or soup.find("section") or soup.find("div", {"id":"content"}) or soup
        text = clean_text(main_block.get_text(" ", strip=True))
        combined_text += " " + text
        # save per-page
        if "about" in page_url.lower():
            about_text = text
            about_soup = main_block
        elif "contact" in page_url.lower():
            contact_text = text
            contact_soup = main_block
        else:
            home_text = text
            combined_soup = main_block

    combined_text = clean_text(combined_text or home_text or about_text or contact_text)

    # chunk for RAG
    chunks = chunk_text(combined_text)

    # Try RAG first (if available)
    rag_result = None
    if USE_RAG:
        rag_result = await rag_extract(chunks, site_url)

    if rag_result and isinstance(rag_result, dict):
        # ensure minimal fields exist and fallback to local heuristics if missing
        out = {k: rag_result.get(k, "") for k in ["Business Name","About Us","Main Services","Email","Phone","Address","Facebook","Instagram","LinkedIn","Twitter / X","Description"]}
        out["URL"] = site_url
        # fallback per-field
        if not out["Email"]:
            out["Email"] = extract_email(combined_text)
        if not out["Phone"]:
            out["Phone"] = extract_phone(combined_text)
        if not out["Address"]:
            out["Address"] = extract_address(combined_text)
        if not out["Main Services"]:
            out["Main Services"] = extract_services_from_soup(combined_soup if combined_soup else BeautifulSoup(home_text, "html.parser"))
        # social fallback
        social = extract_social_links(combined_soup if combined_soup else BeautifulSoup(combined_text, "html.parser"))
        for k,v in social.items():
            if not out.get(k):
                out[k] = v
        return out

    # If RAG not used or failed -> fallback heuristics
    soup_for_services = combined_soup if combined_soup else BeautifulSoup(combined_text, "html.parser")
    services = extract_services_from_soup(soup_for_services)
    # Business Name: try title -> h1
    biz = ""
    try:
        # try fetching title from home page if available
        # we can attempt to fetch <title> from the first page in discovered
        hhtml = ""
        if discovered:
            hhtml = await fetch_page(discovered[0])
        if hhtml:
            hsoup = BeautifulSoup(hhtml, "html.parser")
            if hsoup.title and hsoup.title.string:
                biz = clean_text(hsoup.title.string)
            else:
                h1 = hsoup.find("h1")
                biz = clean_text(h1.get_text(" ", strip=True)) if h1 else ""
    except Exception:
        biz = ""

    email = extract_email(contact_text or combined_text)
    phone = extract_phone(contact_text or combined_text)
    address = extract_address(contact_text or combined_text)
    socials = extract_social_links(combined_soup if combined_soup else BeautifulSoup(combined_text, "html.parser"))

    result = {
        "Business Name": biz,
        "About Us": about_text or combined_text[:800],
        "Main Services": services,
        "Email": email,
        "Phone": phone,
        "Address": address,
        "Facebook": socials.get("Facebook",""),
        "Instagram": socials.get("Instagram",""),
        "LinkedIn": socials.get("LinkedIn",""),
        "Twitter / X": socials.get("Twitter / X",""),
        "Description": (home_text or combined_text)[:400],
        "URL": site_url
    }
    return result
