import os, re, json, asyncio, urllib.parse, random
from typing import Dict
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

MAX_PAGES = 3
USE_HEADLESS = True
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50

# ---------------- Helpers ----------------
def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i:i+size]))
        i += size - overlap
    return chunks

def extract_email(text: str):
    m = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m[0] if m else ""

def extract_phone(text: str):
    m = re.findall(r"(\+?\d[\d\s\-()]{7,15})", text)
    return m[0] if m else ""

def extract_address(text: str):
    lines = text.splitlines()
    for line in lines:
        if any(ch.isdigit() for ch in line) and len(line.split()) > 3:
            return line.strip()
    return ""

def select_main_pages(urls: list):
    home = urls[0] if urls else ""
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    return list(filter(None, [home, about, contact]))

# ---------------- Playwright ----------------
from playwright.async_api import async_playwright

async def fetch_page(url: str, headless: bool = USE_HEADLESS) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width":1280,"height":800})
        page = await context.new_page()
        html = ""
        try:
            await page.goto(url, timeout=45000)
            await asyncio.sleep(2 + random.random()*2)
            html = await page.content()
        except Exception:
            html = ""
        finally:
            await page.close()
            await context.close()
            await browser.close()
    return html

async def crawl_site(base_url: str, max_pages: int = MAX_PAGES) -> list:
    visited, queue = set(), [base_url.rstrip("/")]
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        html = await fetch_page(url)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script","style","noscript"])]
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:")):
                continue
            full_url = urllib.parse.urljoin(base_url, href.split("#")[0])
            if full_url.startswith(base_url):
                links.add(full_url.rstrip("/"))
        for l in links:
            if l not in visited and l not in queue and len(visited)+len(queue) < max_pages:
                queue.append(l)
        visited.add(url)
    return list(visited)

# ---------------- OpenAI RAG ----------------
from openai import OpenAI
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_KEY)

async def rag_extract(chunks: list, url: str) -> dict:
    prompt = f"""
You are a professional assistant.
Extract a strict JSON from the following text.
Return only JSON with keys:
Business Name, About Us, Main Services (list), Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL.

URL: {url}
Text: {" ".join(chunks[:5])}
"""
    resp = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```json", "", raw)
    raw = re.sub(r"```$", "", raw)
    try:
        return json.loads(raw)
    except:
        return {"raw_ai": raw}

# ---------------- Public Scrape ----------------
async def scrape_website(site_url: str) -> Dict:
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    all_urls = await crawl_site(site_url, max_pages=MAX_PAGES)
    main_pages = select_main_pages(all_urls)

    all_text = ""
    for page_url in main_pages:
        html = await fetch_page(page_url)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script","style","noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        all_text += " " + text

    all_text = clean_text(all_text)
    chunks = chunk_text(all_text)

    data = await rag_extract(chunks, site_url)
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

    return data
