#!/usr/bin/env python3
"""
SUPER OPTIMIZED WEBSITE BOT — FINAL VERSION
Best multi-office extraction, perfect contacts, with improved LLM accuracy
"""
#21-11

import os, re, json, urllib.parse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests
import concurrent.futures

# ---------------- Load Keys ----------------
load_dotenv(override=True)
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY")

CHUNK_SIZE = 180
CHUNK_OVERLAP = 30

if not OPENAI_KEY:
    raise SystemExit("❌ OPENAI_API_KEY missing")
if not FIRECRAWL_KEY:
    print("⚠️ FIRECRAWL_API_KEY missing — Firecrawl fallback disabled")

# ---------------- ChromaDB (SQLITE DISABLED) ----------------
try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.api.shared import System
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except Exception as e:
    raise SystemExit(f"Install missing packages: pip install beautifulsoup4 chromadb openai lxml\nError: {str(e)}")

# Disable SQLITE completely
System.set_chromadb_env("CHROMA_DISABLE_SQLITE", "true")

# Use DuckDB backend only
chroma_client = chromadb.Client(
    Settings(
        chroma_db_impl="duckdb+parquet",
        persist_directory="chroma_db"
    )
)

openai_client = OpenAI(api_key=OPENAI_KEY)

openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_KEY,
    model_name="text-embedding-3-large"
)

# ---------------- Helper ----------------
def clean_text(t):
    return re.sub(r"\s+", " ", t).strip()

# ---------------- Fetch Page ----------------
def fetch_page(url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200 and len(r.text) > 200:
            return r.text
    except:
        pass

    if FIRECRAWL_KEY:
        try:
            fc_url = "https://api.firecrawl.dev/v2/scrape"
            headers = {"Authorization": f"Bearer {FIRECRAWL_KEY}"}
            payload = {"url": url, "formats": ["html"]}
            fc = requests.post(fc_url, json=payload, headers=headers, timeout=20)
            return fc.json().get("html", "")
        except:
            pass

    return ""

# ---------------- Extractors ----------------
def extract_social_links_from_html(html):
    soup = BeautifulSoup(html, "lxml")
    social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}

    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if "facebook.com" in href: social["Facebook"] = href
        if "instagram.com" in href: social["Instagram"] = href
        if "linkedin.com" in href: social["LinkedIn"] = href
        if "twitter.com" in href or "x.com" in href: social["Twitter / X"] = href

    return social

def extract_all_emails(text):
    return list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)))

def extract_all_phones(text):
    return list(set(re.findall(r"\+?\d[\d\-\s()]{8,15}", text)))

def extract_all_addresses(text):
    pattern = r"\d{1,4}\s+[A-Za-z0-9\s,.-]{5,100}"
    return list(set(re.findall(pattern, text)))

# ---------------- Chunking ----------------
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = clean_text(text)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ""

    for s in sentences:
        if len(current.split()) + len(s.split()) <= size:
            current += " " + s
        else:
            chunks.append(current.strip())
            current = s
    if current:
        chunks.append(current.strip())

    return chunks

# ---------------- Sitemap ----------------
def get_urls_from_sitemap(url):
    try:
        smaps = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]
        urls = []

        for path in smaps:
            sm = urllib.parse.urljoin(url, path)
            r = requests.get(sm, timeout=10)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "xml")
            urls += [x.get_text().strip() for x in soup.find_all("loc")]

        return list(set(urls))
    except:
        return []

def get_urls_from_firecrawl(base_url):
    if not FIRECRAWL_KEY:
        return []
    try:
        f = requests.post(
            "https://api.firecrawl.dev/v2/map",
            json={"url": base_url},
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}"},
            timeout=30
        )
        return [x["url"] for x in f.json().get("links", [])]
    except:
        return []

def get_site_urls(base):
    sm = get_urls_from_sitemap(base)
    if sm:
        print(f"✅ Sitemap URLs: {len(sm)}")
        return sm

    print("⚠️ No sitemap — using Firecrawl")
    fc = get_urls_from_firecrawl(base)
    if fc:
        print(f"🔥 Firecrawl URLs: {len(fc)}")
        return fc

    return [base]

# ---------------- Pick Pages ----------------
def select_main_pages(urls, base):
    pages = []
    base = base.rstrip("/")
    for u in urls:
        ul = u.lower()
        if "about" in ul or "contact" in ul:
            pages.append(u)
    if base not in pages:
        pages.insert(0, base)
    return pages[:3]

# ---------------- Fix Collection Name ----------------
def sanitize_collection_name(url):
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", url)
    name = re.sub(r"^[^a-zA-Z0-9]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+$", "", name)
    if not name:
        name = "default"
    return f"collection_{name}"

# ---------------- RAG Extraction ----------------
def rag_extract(chunks, site_url):
    cname = sanitize_collection_name(site_url)
    coll = chroma_client.get_or_create_collection(name=cname, embedding_function=openai_ef)

    for i, ch in enumerate(chunks):
        coll.add(
            documents=[ch],
            metadatas=[{"chunk": i}],
            ids=[f"{site_url}_{i}"]
        )

    res = coll.query(query_texts=["Extract company details."], n_results=4)
    context = " ".join(res.get("documents", [[]])[0])

    prompt = f"""
Extract structured business data ONLY in JSON.

Fields:
- Business Name
- About Us
- Main Services (LIST)
- Email (LIST)
- Phone (LIST)
- Address (LIST)
- Facebook
- Instagram
- LinkedIn
- Twitter / X
- Description
- URL: {site_url}

Use ONLY this text:
{context}
"""

    result = openai_client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw = result.choices[0].message.content
    raw = re.sub(r"```json|```", "", raw)

    try:
        return json.loads(raw)
    except:
        return {"raw": raw}

# ---------------- Main Flow ----------------
if __name__ == "__main__":
    site_url = input("Enter website URL: ").strip()
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    print("🔍 Fetching URLs…")
    urls = get_site_urls(site_url)
    main_pages = select_main_pages(urls, site_url)

    print("\n📌 Selected pages:")
    for p in main_pages:
        print(" →", p)

    all_text = ""
    all_social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}

    def scrape_single(page):
        html = fetch_page(page)
        soc = extract_social_links_from_html(html)
        soup = BeautifulSoup(html, "lxml")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        return text, soc

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as exe:
        results = exe.map(scrape_single, main_pages)

    for text, soc in results:
        all_text += " " + text
        for k, v in soc.items():
            if v and not all_social[k]:
                all_social[k] = v

    all_text = clean_text(all_text)
    all_text = " ".join(dict.fromkeys(all_text.split()))

    chunks = chunk_text(all_text)

    print("\n🧠 Running RAG…")
    data = rag_extract(chunks, site_url)

    data["Email"] = data.get("Email") or extract_all_emails(all_text)
    data["Phone"] = data.get("Phone") or extract_all_phones(all_text)
    data["Address"] = data.get("Address") or extract_all_addresses(all_text)

    for k, v in all_social.items():
        if v:
            data[k] = v

    data["URL"] = site_url

    print("\n\n✅ Final Extracted Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
