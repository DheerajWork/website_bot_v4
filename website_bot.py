#!/usr/bin/env python3
"""
website_bot.py
Final Updated Version — Playwright + ChromaDB + Guaranteed Social Media Extraction + Parallel Scraping
"""

import os, re, time, json, urllib.parse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import requests
import concurrent.futures

# ---------------- Config ----------------
load_dotenv(override=True)
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY")
os.environ["OPENAI_API_KEY"] = OPENAI_KEY

USE_HEADLESS = True
CHUNK_SIZE = 180
CHUNK_OVERLAP = 30

if not OPENAI_KEY:
    raise SystemExit("❌ OPENAI_API_KEY not found in .env")
if not FIRECRAWL_KEY:
    print("⚠️ FIRECRAWL_API_KEY not found, Firecrawl fallback disabled")

# ---------------- ChromaDB & OpenAI ----------------
try:
    import chromadb
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except:
    raise SystemExit("Install required packages: pip install playwright beautifulsoup4 chromadb openai")

chroma_client = chromadb.Client()
openai_client = OpenAI(api_key=OPENAI_KEY)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_KEY, 
    model_name="text-embedding-3-small"
)

# ---------------- Helper functions ----------------
def clean_text(t):
    return re.sub(r"\s+", " ", t).strip()

def fetch_page(url: str, headless: bool = USE_HEADLESS) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context().new_page()
        try:
            page.goto(url, timeout=45000)
            time.sleep(2)
            html = page.content()
        except:
            html = ""
        browser.close()
    return html

# ---------------- Extract All Social Links ----------------
def extract_social_links_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "facebook.com" in href: social["Facebook"] = href
        if "instagram.com" in href: social["Instagram"] = href
        if "linkedin.com" in href: social["LinkedIn"] = href
        if "twitter.com" in href or "x.com" in href: social["Twitter / X"] = href

    for meta in soup.find_all("meta", attrs={"property": "og:url"}):
        content = meta.get("content", "")
        if "facebook.com" in content: social["Facebook"] = content

    for meta in soup.find_all("meta", attrs={"property": "og:see_also"}):
        content = meta.get("content", "")
        if "linkedin.com" in content: social["LinkedIn"] = content

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.text)
            same_as = data.get("sameAs", [])
            if isinstance(same_as, list):
                for link in same_as:
                    if "facebook.com" in link: social["Facebook"] = link
                    if "instagram.com" in link: social["Instagram"] = link
                    if "linkedin.com" in link: social["LinkedIn"] = link
                    if "twitter.com" in link or "x.com" in link: social["Twitter / X"] = link
        except:
            pass

    return social

# ---------------- Text Extraction Helpers ----------------
def extract_email(text):
    r = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return r[0] if r else ""

def extract_phone(text):
    r = re.findall(r"(\+?\d[\d\-\s()]{8,15})", text)
    return r[0] if r else ""

def extract_address(text):
    lines = text.split(".")
    for line in lines:
        if any(char.isdigit() for char in line) and len(line.split()) > 4:
            return clean_text(line)
    return ""

# ---------------- Chunking ----------------
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i:i+size]))
        i += size - overlap
    return chunks

# ---------------- Sitemap + Firecrawl ----------------
def get_urls_from_sitemap(url):
    try:
        u = urllib.parse.urljoin(url, "/sitemap.xml")
        r = requests.get(u, timeout=10)
        if r.status_code != 200: return []
        soup = BeautifulSoup(r.text, "xml")
        return [loc.get_text().strip() for loc in soup.find_all("loc")]
    except:
        return []

def get_urls_from_firecrawl(base_url):
    if not FIRECRAWL_KEY: return []
    url = "https://api.firecrawl.dev/v2/map"
    headers = {"Authorization": f"Bearer {FIRECRAWL_KEY}"}
    payload = {"url": base_url}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=25)
        data = r.json()
        return [x["url"] for x in data.get("links", [])]
    except:
        return []

def get_site_urls(base):
    u = get_urls_from_sitemap(base)
    if u: 
        print(f"✅ Found {len(u)} URLs from sitemap")
        return u
    print("⚠️ Sitemap not found → Firecrawl fallback")
    u = get_urls_from_firecrawl(base)
    if u:
        print(f"✅ Found {len(u)} URLs from Firecrawl")
        return u
    return [base]

# ---------------- Select Main Pages ----------------
def select_main_pages(urls, base):
    pages = []
    base = base.rstrip("/")
    for u in urls:
        u2 = u.lower()
        if ("about" in u2 and u not in pages): pages.append(u)
        if ("contact" in u2 and u not in pages): pages.append(u)
    if base not in pages: pages.insert(0, base)
    return pages[:3]

# ---------------- RAG Extraction ----------------
def sanitize_collection_name(url):
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", url)
    name = name.strip("._-")
    if len(name) < 3: name = f"col_{name}"
    return f"collection_{name}"

def rag_extract(chunks, site_url):
    cname = sanitize_collection_name(site_url)
    coll = chroma_client.get_or_create_collection(
        name=cname,
        embedding_function=openai_ef
    )

    for i, ch in enumerate(chunks):
        coll.add(
            documents=[ch],
            metadatas=[{"chunk": i}],
            ids=[f"{site_url}_{i}"]
        )

    q = "Extract company info, name, services, email, phone, address, social media accounts."
    res = coll.query(query_texts=[q], n_results=3)
    context = " ".join(res.get("documents", [[]])[0])

    prompt = f"""
Extract clean JSON with:
Business Name, About Us, Main Services (list), Email, Phone, Address,
Facebook, Instagram, LinkedIn, Twitter / X, Description, URL.
URL: {site_url}
Text: {context}
"""

    r = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    out = r.choices[0].message.content.strip()
    out = re.sub(r"```json|```", "", out)

    try:
        return json.loads(out)
    except:
        return {"raw": out}

# ---------------- Main Flow ----------------
if __name__ == "__main__":
    site_url = input("Enter website URL: ").strip()
    if not site_url.startswith("http"): site_url = "https://" + site_url

    print("🔍 Fetching site URLs...")
    urls = get_site_urls(site_url)
    main_pages = select_main_pages(urls, site_url)

    print("\nSelected main pages:")
    for p in main_pages: print(p)

    all_text = ""
    all_social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}

    # ---- PARALLEL SCRAPING ----
    def scrape_single_page(page):
        html = fetch_page(page)
        social = extract_social_links_from_html(html)
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        return text, social

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(scrape_single_page, main_pages))

    for text, social in results:
        all_text += " " + text
        for k, v in social.items():
            if v and not all_social[k]: all_social[k] = v

    all_text = clean_text(all_text)
    chunks = chunk_text(all_text)

    print("\nStoring chunks & running RAG...")
    data = rag_extract(chunks, site_url)

    data["Email"] = data.get("Email") or extract_email(all_text)
    data["Phone"] = data.get("Phone") or extract_phone(all_text)
    data["Address"] = data.get("Address") or extract_address(all_text)

    for k, v in all_social.items():
        if v: data[k] = v

    data["URL"] = site_url

    print("\n\n✅ Final Extracted Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
