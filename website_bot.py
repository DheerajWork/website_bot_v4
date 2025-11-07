#!/usr/bin/env python3
"""
website_bot.py — Scraping + ChromaDB + RAG Extraction (Railway-safe + Background-friendly)
"""

import os, re, time, json, random, urllib.parse
from typing import List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------------- Load Environment ----------------
if os.path.exists(".env"):
    from dotenv import load_dotenv
    load_dotenv(override=True)

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    print("⚠️ OPENAI_API_KEY not found. Set it in Railway Variables.")
else:
    print("✅ OPENAI_API_KEY detected successfully.")
os.environ["OPENAI_API_KEY"] = OPENAI_KEY or ""

# ---------------- Config ----------------
USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30
MAX_CRAWL_PAGES = 5  # Railway-friendly limit
FETCH_TIMEOUT = 30000  # 30 sec per page

# ---------------- Imports ----------------
try:
    import chromadb
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except Exception:
    raise SystemExit("Install dependencies: pip install playwright beautifulsoup4 chromadb openai tiktoken")

# ---------------- Clients ----------------
chroma_client = chromadb.Client()
openai_client = OpenAI(api_key=OPENAI_KEY)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_KEY, model_name="text-embedding-3-small"
)

# ---------------- Helpers ----------------
def clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def fetch_page(url: str, headless=True) -> str:
    print(f"[INFO] Fetching: {url}")
    html = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width":1280,"height":800})
            page = context.new_page()
            try:
                page.goto(url, timeout=FETCH_TIMEOUT)
                time.sleep(1 + random.random()*2)
                html = page.content()
            except PlaywrightTimeoutError:
                print(f"[WARN] Timeout loading {url}")
            except Exception as e:
                print(f"[ERROR] Failed to fetch {url}: {e}")
            page.close(); context.close(); browser.close()
    except Exception as e:
        print(f"[ERROR] Browser launch failed: {e}")
    return html

def extract_links(base_url, html_text) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        if href.startswith(("mailto:", "tel:")):
            continue
        full_url = urllib.parse.urljoin(base_url, href.split("#")[0])
        if full_url.startswith(base_url):
            links.add(full_url.rstrip("/"))
    return list(links)

def crawl_site(base_url, max_pages=MAX_CRAWL_PAGES):
    visited, queue = set(), [base_url.rstrip("/")]
    site_structure = []
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        print(f"[CRAWL] Visiting ({len(visited)+1}/{max_pages}): {url}")
        html = fetch_page(url)
        site_structure.append(url)
        links = extract_links(base_url, html)
        for l in links:
            if l not in visited and l not in queue and len(visited)+len(queue) < max_pages:
                queue.append(l)
        visited.add(url)
    return site_structure

def select_main_pages(urls: List[str]):
    home = urls[0] if urls else ""
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    return list(filter(None, [home, about, contact]))

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    words, chunks, i = text.split(), [], 0
    while i < len(words):
        chunks.append(" ".join(words[i:i+size]))
        i += size - overlap
    return chunks

def extract_email(text):
    m = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m[0] if m else ""

def extract_phone(text):
    m = re.findall(r"(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4})", text)
    return m[0] if m else ""

def extract_address(text):
    for line in text.splitlines():
        if any(ch.isdigit() for ch in line) and len(line.split()) > 3:
            return line.strip()
    return ""

# ---------------- RAG Extraction ----------------
def rag_extract(chunks, url):
    print(f"[INFO] Running RAG extraction for {url}")
    coll = chroma_client.get_or_create_collection(
        "rag_extract_collection", embedding_function=openai_ef
    )
    for i, ch in enumerate(chunks):
        coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])
    query = "Extract Business Name, About Us, Main Services, Email, Phone, Address, Social Links, Description, URL"
    try:
        res = coll.query(query_texts=[query], n_results=3)
        context_text = " ".join(res.get("documents", [[""]])[0]) or " ".join(chunks[:3])
        prompt = f"""
You are a data extraction assistant. Return JSON with:
Business Name, About Us, Main Services (list), Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter, Description, URL.
Website: {url}
Text: {context_text}
"""
        resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```json|```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        print(f"[WARN] RAG/AI failed: {e}")
        return {"raw_ai": "Failed to extract"}

# ---------------- Main Scraping Function ----------------
def scrape_website(site_url: str) -> dict:
    if not site_url.startswith("http"):
        site_url = "https://" + site_url
    print(f"[INFO] Starting crawl for {site_url}")
    urls = crawl_site(site_url, MAX_CRAWL_PAGES)
    main_pages = select_main_pages(urls)
    print(f"[INFO] Main pages: {main_pages}")

    text_all = ""
    for u in main_pages:
        html = fetch_page(u)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text_all += " " + clean_text(soup.get_text(" ", strip=True))

    chunks = chunk_text(clean_text(text_all))
    data = rag_extract(chunks, site_url)
    if not data:
        data = {
            "Business Name": "",
            "About Us": "",
            "Main Services": "",
            "Email": extract_email(text_all),
            "Phone": extract_phone(text_all),
            "Address": extract_address(text_all),
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter": "",
            "Description": "",
            "URL": site_url,
        }
    return data

if __name__ == "__main__":
    url = input("Enter website URL: ").strip()
    result = scrape_website(url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
