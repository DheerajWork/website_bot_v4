#!/usr/bin/env python3
"""
SUPER OPTIMIZED WEBSITE BOT — FINAL VERSION
Best multi-office extraction, perfect contacts, with improved LLM accuracy
"""
#21-11

import os, re, time, json, urllib.parse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests
import concurrent.futures

# ---------------- Config ----------------
load_dotenv(override=True)
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY")

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
    raise SystemExit("Install required packages: pip install beautifulsoup4 chromadb openai lxml")

chroma_client = chromadb.Client()
openai_client = OpenAI(api_key=OPENAI_KEY)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_KEY, 
    model_name="text-embedding-3-large"
)

# ---------------- Helper Functions ----------------
def clean_text(t):
    return re.sub(r"\s+", " ", t).strip()

# Fast Playwright Fetch
def fetch_page(url: str) -> str:
    """
    First try Requests.
    If blocked, try Firecrawl HTML extraction (if API key exists).
    """
    # 1. Normal fetch
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200 and len(r.text) > 200:
            return r.text
    except:
        pass

    # 2. Firecrawl Fallback (if available)
    if FIRECRAWL_KEY:
        try:
            fc_url = "https://api.firecrawl.dev/v2/scrape"
            headers = {"Authorization": f"Bearer {FIRECRAWL_KEY}"}
            payload = {"url": url, "formats": ["html"]}

            fc = requests.post(fc_url, json=payload, headers=headers, timeout=20)
            html = fc.json().get("html", "")
            return html
        except:
            pass

    return ""

# ---------------- Social Links Extraction ----------------
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

# ---------------- Contact Extraction (Multi) ----------------
def extract_all_emails(text):
    return list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)))

def extract_all_phones(text):
    return list(set(re.findall(r"\+?\d[\d\-\s()]{8,15}", text)))

def extract_all_addresses(text):
    pattern = r"\d{1,4}\s+[A-Za-z0-9\s,.-]{5,100}"
    return list(set(re.findall(pattern, text)))

# ---------------- Smart Chunking ----------------
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

# ---------------- Sitemap (Improved) ----------------
def get_urls_from_sitemap(url):
    try:
        sitemap_list = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml"
        ]
        urls = []

        for s in sitemap_list:
            sm = urllib.parse.urljoin(url, s)
            r = requests.get(sm, timeout=10)
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "xml")

            # sitemap index support
            for sub in soup.find_all("sitemap"):
                loc = sub.find("loc")
                if loc:
                    sub_url = loc.get_text().strip()
                    try:
                        sub_r = requests.get(sub_url, timeout=10)
                        sub_soup = BeautifulSoup(sub_r.text, "xml")
                        urls += [x.get_text().strip() for x in sub_soup.find_all("loc")]
                    except:
                        pass

            # normal URLs
            urls += [x.get_text().strip() for x in soup.find_all("loc")]

        return list(set(urls))
    except:
        return []

def get_urls_from_firecrawl(base_url):
    if not FIRECRAWL_KEY:
        return []
    url = "https://api.firecrawl.dev/v2/map"
    headers = {"Authorization": f"Bearer {FIRECRAWL_KEY}"}
    payload = {"url": base_url}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        return [x["url"] for x in r.json().get("links", [])]
    except:
        return []

def get_site_urls(base):
    s = get_urls_from_sitemap(base)
    if s:
        print(f"✅ Sitemap URLs: {len(s)}")
        return s

    print("⚠️ Sitemap not found — trying Firecrawl…")
    f = get_urls_from_firecrawl(base)
    if f:
        print(f"🔥 Firecrawl URLs: {len(f)}")
        return f

    return [base]

# ---------------- Main Page Selection ----------------
def select_main_pages(urls, base):
    pages = []
    base = base.rstrip("/")

    for u in urls:
        ul = u.lower()
        if "about" in ul: pages.append(u)
        if "contact" in ul: pages.append(u)

    if base not in pages:
        pages.insert(0, base)

    return pages[:3]

# ---------------- RAG Extraction ----------------
def sanitize_collection_name(url):
    # Replace invalid characters
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", url)

    # Remove leading invalid chars
    name = re.sub(r"^[^a-zA-Z0-9]+", "", name)

    # Remove trailing invalid chars
    name = re.sub(r"[^a-zA-Z0-9]+$", "", name)

    if not name:
        name = "default"

    return f"collection_{name}"


def rag_extract(chunks, site_url):
    cname = sanitize_collection_name(site_url)
    coll = chroma_client.get_or_create_collection(name=cname, embedding_function=openai_ef)

    for i, ch in enumerate(chunks):
        coll.add(documents=[ch], metadatas=[{"chunk": i}], ids=[f"{site_url}_{i}"])

    res = coll.query(query_texts=["Extract company details and all office locations."], n_results=4)
    context = " ".join(res.get("documents", [[]])[0])

    prompt = f"""
You are a world-class business data extractor.

Extract ALL fields with multiple values where available:
- Business Name
- About Us
- Main Services (LIST, never string)
- Email (LIST, return ALL emails)
- Phone (LIST)
- Address (LIST of full addresses)
- Facebook
- Instagram
- LinkedIn
- Twitter / X
- Description
- URL: {site_url}

Return clean JSON ONLY.
Use ONLY the following text:

{context}
"""

    r = openai_client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )

    out = r.choices[0].message.content
    out = re.sub(r"```json|```", "", out)

    try:
        return json.loads(out)
    except:
        return {"raw": out}

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

    # ---------------- Parallel Scrape ----------------
    def scrape_single_page(page):
        html = fetch_page(page)
        social = extract_social_links_from_html(html)
        soup = BeautifulSoup(html, "lxml")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        return text, social

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as exe:
        results = list(exe.map(scrape_single_page, main_pages))

    for text, social in results:
        all_text += " " + text
        for k, v in social.items():
            if v and not all_social[k]:
                all_social[k] = v

    all_text = clean_text(all_text)

    # Prevent hallucination by removing duplicates
    all_text = " ".join(dict.fromkeys(all_text.split()))

    chunks = chunk_text(all_text)

    print("\n🧠 Running RAG…")
    data = rag_extract(chunks, site_url)

    # fallback extraction — MULTIPLE
    data["Email"] = data.get("Email") or extract_all_emails(all_text)
    data["Phone"] = data.get("Phone") or extract_all_phones(all_text)
    data["Address"] = data.get("Address") or extract_all_addresses(all_text)

    # social links
    for k, v in all_social.items():
        if v:
            data[k] = v

    data["URL"] = site_url

    print("\n\n✅ Final Extracted Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
