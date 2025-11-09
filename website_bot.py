#!/usr/bin/env python3
"""
website_bot.py — Website scraper + RAG extraction (with ChromaDB + OpenAI)
"""

import os, re, time, json, random, urllib.parse
from typing import List
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# ---------------- Config ----------------
load_dotenv(override=True)
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
os.environ["OPENAI_API_KEY"] = OPENAI_KEY

USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30

# ---------------- Import dependencies ----------------
try:
    import chromadb
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except Exception:
    raise SystemExit("Install required packages: pip install playwright beautifulsoup4 chromadb openai tiktoken")

# ---------------- Setup Clients ----------------
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
    """Playwright se page fetch karta hai"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, timeout=45000)
            time.sleep(2 + random.random() * 2)
            html = page.content()
        except Exception:
            html = ""
        page.close()
        context.close()
        browser.close()
    return html

def extract_links(base_url: str, html_text: str) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:")):
            continue
        full_url = urllib.parse.urljoin(base_url, href.split("#")[0])
        if full_url.startswith(base_url):
            links.add(full_url.rstrip("/"))
    return list(links)

def crawl_site(base_url: str, max_pages=100) -> List[str]:
    """Website ke andar ke links crawl karta hai"""
    visited, queue = set(), [base_url.rstrip("/")]
    site_structure = []
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        html = fetch_page(url)
        if not html:
            continue
        site_structure.append(url)
        links = extract_links(base_url, html)
        for l in links:
            if l not in visited and l not in queue:
                queue.append(l)
        visited.add(url)
    return site_structure

def select_main_pages(urls: List[str]) -> List[str]:
    """Home, About, Contact pages choose karta hai"""
    home = urls[0]
    about = next((u for u in urls if "about" in u.lower()), "")
    contact = next((u for u in urls if "contact" in u.lower()), "")
    return list(filter(None, [home, about, contact]))

def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    """Text ko chhote chunks me todta hai"""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i+size]
        chunks.append(" ".join(chunk))
        i += size - overlap
    return chunks

def extract_email(text):
    m = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m[0] if m else ""

def extract_phone(text):
    m = re.findall(r"(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4})", text)
    return m[0] if m else ""

def extract_address(text):
    lines = text.splitlines()
    for line in lines:
        if any(ch.isdigit() for ch in line) and len(line.split()) > 3:
            return line.strip()
    return ""

def rag_extract(chunks, url):
    """RAG (Retrieval Augmented Generation) se data extract karta hai"""
    coll = chroma_client.get_or_create_collection(
        "three_page_rag_collection", embedding_function=openai_ef
    )
    # Add chunks
    for i, ch in enumerate(chunks):
        coll.add(documents=[ch], metadatas=[{"url": url, "chunk": i}], ids=[f"{url}_chunk_{i}"])
    # Query
    query = "Extract Business Name, About Us, Main Services, Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL"
    res = coll.query(query_texts=[query], n_results=3)
    context_text = " ".join(res["documents"][0]) if res and "documents" in res else " ".join(chunks[:3])

    prompt = f"""
You are a professional data extraction assistant. From the given text, extract clean JSON with fields:
Business Name, About Us, Main Services (list), Email, Phone, Address, Facebook, Instagram, LinkedIn, Twitter / X, Description, URL.
URL: {url}
Text: {context_text}
"""
    resp = openai_client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    raw = resp.choices[0].message.content
    raw = re.sub(r"^```json", "", raw.strip())
    raw = re.sub(r"```$", "", raw.strip())
    try:
        return json.loads(raw)
    except:
        return {"raw_ai": raw}


# ---------------- SCRAPE FUNCTION (for API) ----------------
def scrape_website(site_url: str):
    """Main function jo API ke liye data return karta hai"""
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    all_urls = crawl_site(site_url, max_pages=50)
    main_pages = select_main_pages(all_urls)

    all_text = ""
    for page_url in main_pages:
        html = fetch_page(page_url)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        all_text += " " + text

    all_text = clean_text(all_text)
    chunks = chunk_text(all_text)

    final_data = rag_extract(chunks, site_url)
    if not final_data:
        final_data = {
            "Business Name": "",
            "About Us": "",
            "Main Services": "",
            "Email": extract_email(all_text),
            "Phone": extract_phone(all_text),
            "Address": extract_address(all_text),
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter / X": "",
            "Description": "",
            "URL": site_url
        }
    return final_data


# ---------------- Manual Run ----------------
if __name__ == "__main__":
    url = input("Enter website URL: ").strip()
    result = scrape_website(url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
