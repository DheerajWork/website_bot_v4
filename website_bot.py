#!/usr/bin/env python3
"""
website_bot.py — Secure & Env-Safe Version

Flow:
1) Input site URL
2) Crawl internal links (depth-limited) -> print site structure
3) Auto-select Home, Contact, About pages
4) Deep scrape those 3 pages (Playwright)
5) Chunk scraped text with chunk_size=180 words and overlap=30
6) Store chunks in ChromaDB using OpenAI embeddings
7) Run a RAG extraction: retrieve top chunks and call LLM (gpt-3.5-turbo)
8) Return clean JSON output

Notes:
- API key is loaded from .env
- Hardcoded key removed (safe for Git/GitHub)
"""

import os, re, time, json, random, urllib.parse
from typing import List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv()  # Load .env automatically
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30

# ChromaDB + OpenAI
try:
    import chromadb
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except Exception:
    raise SystemExit("Install required packages: pip install playwright beautifulsoup4 chromadb openai tiktoken python-dotenv")

# Initialize clients
chroma_client = chromadb.Client()
openai_client = OpenAI(api_key=OPENAI_KEY)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_KEY,
    model_name="text-embedding-3-small"
)

# ---------------- Helper functions ----------------
def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def fetch_page(url: str, headless: bool = USE_HEADLESS) -> str:
    """Fetch page content using Playwright"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width":1280,"height":800})
        page = context.new_page()
        try:
            page.goto(url, timeout=45000)
            time.sleep(2 + random.random()*2)
            html = page.content()
        except:
            html = ""
        page.close(); context.close(); browser.close()
    return html

def extract_links(base_url: str, html_text: str) -> List[str]:
    """Extract internal links from a page"""
    soup = BeautifulSoup(html_text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        if href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full_url = urllib.parse.urljoin(base_url, href.split("#")[0])
        if full_url.startswith(base_url):
            links.add(full_url.rstrip("/"))
    return list(links)

def crawl_site(base_url: str, max_pages: int = 100) -> List[str]:
    """Crawl site to get all internal URLs (depth-limited)"""
    visited, queue = set(), [base_url.rstrip("/")]
    site_structure = []
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        print(f"Visiting: {url}")
        html = fetch_page(url)
        site_structure.append(url)
        links = extract_links(base_url, html)
        for l in links:
            if l not in visited and l not in queue and len(visited)+len(queue) < max_pages:
                queue.append(l)
        visited.add(url)
    return site_structure

def select_main_pages(urls: List[str]) -> List[str]:
    """Auto-select Home, About, Contact pages"""
    home = urls[0] if urls else ""
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    return list(filter(None, [home, about, contact]))

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into chunks"""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i+size]
        chunks.append(" ".join(chunk))
        i += size - overlap
    return chunks

# ---------------- Fallback extraction ----------------
def extract_email(text: str) -> str:
    m = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m[0] if m else ""

def extract_phone(text: str) -> str:
    m = re.findall(r"(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4})", text)
    return m[0] if m else ""

def extract_address(text: str) -> str:
    lines = text.splitlines()
    for line in lines:
        if any(ch.isdigit() for ch in line) and len(line.split())>3:
            return line.strip()
    return ""

# ---------------- RAG extraction ----------------
def rag_extract(chunks: List[str], url: str) -> dict:
    coll = chroma_client.get_or_create_collection(
        "three_page_rag_collection",
        embedding_function=openai_ef
    )
    for i, ch in enumerate(chunks):
        coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])

    query = ("Extract Business Name, About Us, Main Services, Email, Phone, Address, "
             "Facebook, Instagram, LinkedIn, Twitter / X, Description, URL")
    res = coll.query(query_texts=[query], n_results=3)
    context_text = " ".join(res["documents"][0]) if res and "documents" in res else " ".join(chunks[:3])

    prompt = f"""
You are a data extraction assistant. Extract clean JSON from the following text with fields:
Business Name, About Us, Main Services (list), Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL.
URL: {url}
Text: {context_text}
"""
    resp = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    raw = resp.choices[0].message.content
    raw = re.sub(r"^```json", "", raw.strip())
    raw = re.sub(r"```$", "", raw.strip())
    try:
        return json.loads(raw)
    except:
        return {"raw_ai": raw}

# ---------------- Main Flow ----------------
def scrape_website(site_url: str) -> dict:
    """Main scraping function"""
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    print("🔍 Crawling site structure...")
    all_urls = crawl_site(site_url, max_pages=100)

    main_pages = select_main_pages(all_urls)
    print("Selected main pages for deep scraping:", main_pages)

    all_text = ""
    for page_url in main_pages:
        print(f"Scraping page: {page_url}")
        html = fetch_page(page_url)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script","style","noscript"])]
        text = clean_text(soup.get_text(" ",strip=True))
        all_text += " " + text

    all_text = clean_text(all_text)
    chunks = chunk_text(all_text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

    print("Storing chunks in ChromaDB and running RAG extraction...")
    final_data = rag_extract(chunks, site_url)

    # Fallback extractions if LLM fails
    if not final_data:
        final_data = {
            "Business Name":"",
            "About Us":"",
            "Main Services":"",
            "Email": extract_email(all_text),
            "Phone": extract_phone(all_text),
            "Address": extract_address(all_text),
            "Facebook":"",
            "Instagram":"",
            "LinkedIn":"",
            "Twitter / X":"",
            "Description":"",
            "URL": site_url
        }

    return final_data

# ---------------- CLI usage ----------------
if __name__=="__main__":
    url = input("Enter website URL: ").strip()
    data = scrape_website(url)
    print(json.dumps(data, indent=2, ensure_ascii=False))
