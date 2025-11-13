#!/usr/bin/env python3
"""
website_bot.py — Fast multi-website scraper with lazy browser load and robust fallback
"""

import os, re, time, json, urllib.parse
from typing import List
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv(override=True)
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    raise SystemExit("❌ OPENAI_API_KEY missing in .env")
os.environ["OPENAI_API_KEY"] = OPENAI_KEY

USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30

# ---------------- Imports (lazy load supported) ----------------
def lazy_imports():
    global chromadb, embedding_functions, OpenAI, sync_playwright
    import chromadb
    from chromadb.utils import embedding_functions
    from openai import OpenAI
    from playwright.sync_api import sync_playwright

# ---------------- Helper functions ----------------
def clean_text(t):
    return re.sub(r"\s+", " ", t).strip()

def fetch_page(url: str, headless: bool = USE_HEADLESS) -> str:
    """Fetch page with Playwright"""
    from playwright.sync_api import sync_playwright  # lazy import
    html = ""
    try:
        with sync_playwright() as p:
            # ✅ Chromium launch with sandbox flags for Docker/Railway
            browser = p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.goto(url, timeout=50000, wait_until="networkidle")
            # scroll for lazy-load content
            for _ in range(2):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                time.sleep(1)
            html = page.content()
            # iframe content
            for frame in page.frames:
                try:
                    html += frame.content()
                except:
                    pass
            page.close()
            context.close()
            browser.close()
    except Exception as e:
        print(f"⚠️ Page fetch failed for {url}: {e}")
    return html

def extract_links(base_url, html_text) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full_url = urllib.parse.urljoin(base_url, href.split("#")[0])
        if full_url.startswith(base_url):
            links.add(full_url.rstrip("/"))
    return list(links)

def crawl_site(base_url, max_pages=20):
    visited, queue = set(), [base_url.rstrip("/")]
    structure = []
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        html = fetch_page(url)
        structure.append(url)
        for link in extract_links(base_url, html):
            if link not in visited and len(visited) < max_pages:
                queue.append(link)
        visited.add(url)
    return structure

def select_main_pages(urls: List[str]):
    home = urls[0] if urls else ""
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    return list(filter(None, [home, about, contact]))

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i : i + size]
        chunks.append(" ".join(chunk))
        i += size - overlap
    return chunks

# ---------------- RAG Extraction ----------------
def rag_extract(chunks, url):
    try:
        lazy_imports()
        chroma_client = chromadb.Client()
        openai_client = OpenAI(api_key=OPENAI_KEY)
        openai_ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_KEY, model_name="text-embedding-3-small"
        )

        coll = chroma_client.get_or_create_collection(
            "multi_website_rag_collection", embedding_function=openai_ef
        )
        for i, ch in enumerate(chunks[:10]):
            coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])

        query = (
            "Extract clean JSON with these fields: "
            "Business Name, About Us, Main Services (list), Email (list), Phone (list), "
            "Address (dictionary), Facebook, Instagram, LinkedIn, Twitter/X, Description, URL. "
            "Only real company/service info, no headings like Pricing/Features."
        )

        res = coll.query(query_texts=[query], n_results=3)
        context = " ".join(res["documents"][0]) if res and "documents" in res else " ".join(chunks[:3])

        prompt = f"""
You are a structured data extraction AI.
From the following website content, return JSON with fields:
Business Name, About Us, Main Services (list), Email (list),
Phone (list), Address (dictionary), Facebook, Instagram, LinkedIn,
Twitter/X, Description, URL.

Be accurate, ignore marketing fluff, and produce valid JSON.

URL: {url}
Text: {context}
"""
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json|```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        print("⚠️ RAG Extraction Error:", e)
        return {}

# ---------------- Fallback Extraction ----------------
def fallback_extract(text, site_url):
    return {
        "Business Name": "",
        "About Us": "",
        "Main Services": [],
        "Email": re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text),
        "Phone": re.findall(r"\+?\d[\d\s\-]{7,}", text),
        "Address": {},  # Could improve with regex for street/city/postal if needed
        "Facebook": "",
        "Instagram": "",
        "LinkedIn": "",
        "Twitter/X": "",
        "Description": "",
        "URL": site_url,
    }

# ---------------- Main Function ----------------
def scrape_website(site_url: str):
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    urls = crawl_site(site_url, max_pages=20)
    main_pages = select_main_pages(urls)

    full_text = ""
    for page in main_pages:
        html = fetch_page(page)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        full_text += " " + text
        if soup.title:
            full_text += " " + soup.title.string

    chunks = chunk_text(clean_text(full_text))
    data = rag_extract(chunks, site_url)
    if not data or not any(data.values()):
        data = fallback_extract(full_text, site_url)

    # Ensure no null values
    for key in ["Business Name", "About Us", "Facebook", "Instagram", "LinkedIn", "Twitter/X", "Description"]:
        if key not in data or data[key] is None:
            data[key] = ""
    for key in ["Main Services", "Email", "Phone"]:
        if key not in data or not isinstance(data[key], list):
            data[key] = []
    if "Address" not in data or not isinstance(data["Address"], dict):
        data["Address"] = {}
    if "URL" not in data:
        data["URL"] = site_url

    return data

# ---------------- CLI Run ----------------
if __name__ == "__main__":
    url = input("Enter website URL: ").strip()
    result = scrape_website(url)
    print("\n=== FULL RAG RESULT ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))
