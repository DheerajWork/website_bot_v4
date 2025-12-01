#!/usr/bin/env python3
"""
SUPER OPTIMIZED WEBSITE BOT — FINAL VERSION
Best multi-office extraction, perfect contacts, with improved LLM accuracy
"""

import os
import re
import time
import json
import urllib.parse
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
    from chromadb import PersistentClient
    from chromadb.utils import embedding_functions
    from openai import OpenAI
except Exception as e:
    print("Import error:", e)
    raise SystemExit(f"Error importing modules: {e}")

# Initialize NEW persistent Chroma client
try:
    chroma_client = PersistentClient(path="./chroma")
    print("✅ Chroma client initialized at ./chroma")
except Exception as err:
    print("⚠️ Could not initialize Chroma client.")
    print("Chroma error:", str(err))
    chroma_client = None


openai_client = OpenAI(api_key=OPENAI_KEY)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_KEY,
    model_name="text-embedding-3-large"
)

# ---------------- Helper Functions ----------------
def clean_text(t):
    return re.sub(r"\s+", " ", t).strip()

# Fast Requests + Firecrawl Fetch
def fetch_page(url: str) -> str:
    """
    First try Requests.
    If blocked, try Firecrawl HTML extraction (if API key exists).
    """
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

    # Firecrawl fallback
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
    soup = BeautifulSoup(html or "", "html.parser")
    social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}

    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if "facebook.com" in href and not social["Facebook"]:
            social["Facebook"] = href
        if "instagram.com" in href and not social["Instagram"]:
            social["Instagram"] = href
        if "linkedin.com" in href and not social["LinkedIn"]:
            social["LinkedIn"] = href
        if ("twitter.com" in href or "x.com" in href) and not social["Twitter / X"]:
            social["Twitter / X"] = href

    return social

# ---------------- Contact Extraction (Multi) ----------------
def extract_all_emails(text):
    return list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text or "")))

def extract_all_phones(text):
    return list(set(re.findall(r"\+?\d[\d\-\s()]{8,15}", text or "")))

def extract_all_addresses(text):
    """
    Strict regex fallback for addresses - only extracts if it contains address keywords.
    """
    if not text:
        return []
    
    # Pattern: starts with 1-4 digits, followed by address-like text
    pattern = r"\d{1,4}[,\s]+[A-Za-z0-9\s,.-]{20,200}"
    potential_addresses = re.findall(pattern, text)
    
    # Only keep addresses with proper keywords
    valid_addresses = []
    for addr in potential_addresses:
        addr = addr.strip()
        
        # Must contain address keywords
        if re.search(r'\b(street|st|road|rd|avenue|ave|lane|ln|drive|dr|complex|building|floor|suite|office|near|opposite|highway|hwy|mall|square|circle|nagar|society)\b', addr, re.IGNORECASE):
            # Skip if it has dates/years
            if not re.search(r'\b(19|20)\d{2}\b', addr):
                # Skip if too many digits (phone numbers)
                digit_ratio = sum(c.isdigit() for c in addr) / len(addr)
                if digit_ratio < 0.3:
                    valid_addresses.append(addr)
    
    return list(set(valid_addresses))

# ---------------- Smart Chunking ----------------
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = clean_text(text)
    if not text:
        return []
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
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", url)
    name = re.sub(r"^[^a-zA-Z0-9]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+$", "", name)
    if not name:
        name = "default"
    return f"collection_{name}"

def rag_extract(chunks, site_url):
    """
    If Chroma is available we index/query there.
    If not available, fall back to joining top chunks as context.
    """
    context = ""
    if chroma_client:
        try:
            cname = sanitize_collection_name(site_url)
            # coll = chroma_client.get_or_create_collection(
            #     name=cname,
            #     embedding_function=openai_ef
            # )
            coll = chroma_client.get_or_create_collection(
                name=cname,
                embedding_function=openai_ef,
                metadata={"dimension": 3072}
            )
            def get_embeddings(texts):
                # Ensure it's always a list of strings
                if isinstance(texts, str):
                    texts = [texts]
                if not isinstance(texts, list):
                    texts = [str(texts)]

                clean_texts = [str(t)[:8000] for t in texts]   # trim to 8k chars (OpenAI limit)

                try:
                    resp = openai_client.embeddings.create(
                        model="text-embedding-3-large",
                        input=clean_texts
                    )
                    return [item.embedding for item in resp.data]
                except Exception as e:
                    print("❌ Embedding ERROR:", e)
                    print("⚠ Texts passed to embed:", clean_texts[:3])
                    raise


            print(f"✅ Using Chroma collection: {cname}")
            # add chunks (upsert)
            BATCH = 8

            # Clean chunks
            chunks = [str(c).strip() for c in chunks if str(c).strip()]

            for b in range(0, len(chunks), BATCH):
                batch = chunks[b:b+BATCH]

                # Get embeddings using your new function
                emb = get_embeddings(batch)

                ids = [f"{site_url}_{b+i}" for i in range(len(batch))]
                metas = [{"chunk": b+i} for i in range(len(batch))]

                coll.add(
                    documents=batch,
                    metadatas=metas,
                    ids=ids,
                    embeddings=emb 
                )

            res = coll.query(
                query_texts=["company name, about us, services, contact information, email, phone, office address, location"],
                n_results=6
            )
            # attempt to get returned documents safely
            docs_list = res.get("documents", [])
            if docs_list and isinstance(docs_list, list):
                # docs_list is list of lists (one per query). join first set.
                context = " ".join(docs_list[0]) if docs_list[0] else ""
            else:
                context = " ".join(chunks[:6])
        except Exception as e:
            print("⚠️ Chroma operation failed, falling back. Error:", str(e))
            context = " ".join(chunks[:6])
    else:
        # simple fallback context if Chromadb not available
        context = " ".join(chunks[:6])

    prompt = f"""
You are a world-class business data extractor. Your job is to extract accurate business information from website content.

Extract the following fields:

1. **Business Name**: The official company/business name

2. **About Us**: A brief description of the company (2-3 sentences)

3. **Main Services**: List of services offered (as array)

4. **Email**: All business email addresses (as array)

5. **Phone**: All business phone numbers (as array)

6. **Address**: ONLY complete physical office/business addresses (as array)
   - MUST include: Street number, street/building name, area/locality, city, state/region
   - MUST contain address keywords like: Street, Road, Complex, Building, Mall, Highway, Avenue, Lane, Square, Nagar, Society, Floor, Suite, Office
   - DO NOT include:
     * Business hours (e.g., "10:00 AM - 7:00 PM", "Monday - Saturday")
     * Timestamps or dates (e.g., "2017", "2025", "15-January-2017")
     * Review counts (e.g., "267 reviews", "4.7 rating")
     * Social media text (e.g., "Follow Us", "Google Reviews")
     * Phone numbers appearing alone
     * Promotional text or website content
     * Incomplete fragments
   
   EXAMPLES OF VALID ADDRESSES:
   ✓ "306, Surmount Complex, Opposite Iscon Mega Mall, Sarkhej-Gandhinagar Highway, Near Baleshwar Square, Ahmedabad, Gujarat 380054"
   ✓ "1234 Main Street, Suite 500, Downtown, New York, NY 10001"
   
   EXAMPLES OF INVALID (DO NOT EXTRACT):
   ✗ "10:00 AM - 7:00 PM Monday - Saturday"
   ✗ "267 reviews Google Reviews"
   ✗ "+91 76002 16429"
   ✗ "Follow Us ARE InfoTech"
   ✗ "2017 Category Skin Care Clinical"

7. **Facebook**: Facebook page URL (if found)

8. **Instagram**: Instagram profile URL (if found)

9. **LinkedIn**: LinkedIn company page URL (if found)

10. **Twitter / X**: Twitter/X profile URL (if found)

11. **Description**: A comprehensive 2-3 sentence description of what the business does

12. **URL**: {site_url}

IMPORTANT RULES:
- Return ONLY valid, complete information
- For addresses, be VERY strict - only extract if it's a complete physical location
- If a field has no valid data, return empty array [] or empty string ""
- Return clean, properly formatted JSON ONLY (no markdown, no code blocks)

Website content to extract from:

{context}
"""

    # call OpenAI to extract structured JSON
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
        soup = BeautifulSoup(html or "", "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        return text, social

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as exe:
        results = list(exe.map(scrape_single_page, main_pages))

    for text, social in results:
        all_text += " " + (text or "")
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
