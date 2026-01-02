#!/usr/bin/env python3
"""
SUPER OPTIMIZED WEBSITE BOT — FINAL VERSION
Best multi-office extraction, perfect contacts, with improved LLM accuracy
Includes: Cloudflare email protection decoder
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
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

# ---------------- Cloudflare Email Protection Decoder ----------------
def decode_cloudflare_email(encoded_string: str) -> str:
    """
    Decode Cloudflare protected email addresses.
    Cloudflare encodes emails using XOR cipher with first 2 hex chars as key.
    """
    try:
        if not encoded_string:
            return ""
        
        # Remove any non-hex characters
        encoded_string = re.sub(r'[^a-fA-F0-9]', '', encoded_string)
        
        if len(encoded_string) < 4:
            return ""
            
        r = int(encoded_string[:2], 16)
        email = ''.join([
            chr(int(encoded_string[i:i+2], 16) ^ r) 
            for i in range(2, len(encoded_string), 2)
        ])
        return email
    except Exception as e:
        return ""

def extract_cloudflare_emails(html: str) -> list:
    """Extract emails protected by Cloudflare's email protection."""
    emails = []
    
    if not html:
        return emails
        
    soup = BeautifulSoup(html, "html.parser")
    
    # Method 1: Look for Cloudflare protected email spans
    for span in soup.find_all("span", class_="__cf_email__"):
        encoded = span.get("data-cfemail")
        if encoded:
            decoded = decode_cloudflare_email(encoded)
            if decoded and "@" in decoded and is_valid_email(decoded):
                emails.append(decoded)
    
    # Method 2: Look for <a> tags with data-cfemail attribute
    for a in soup.find_all("a", attrs={"data-cfemail": True}):
        encoded = a.get("data-cfemail")
        if encoded:
            decoded = decode_cloudflare_email(encoded)
            if decoded and "@" in decoded and is_valid_email(decoded):
                emails.append(decoded)
    
    # Method 3: Look for href="/cdn-cgi/l/email-protection#..."
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/cdn-cgi/l/email-protection#" in href:
            encoded = href.split("#")[-1]
            decoded = decode_cloudflare_email(encoded)
            if decoded and "@" in decoded and is_valid_email(decoded):
                emails.append(decoded)
        elif "/cdn-cgi/l/email-protection" in href:
            # Sometimes it's in query params
            match = re.search(r'email-protection[#?]([a-fA-F0-9]+)', href)
            if match:
                decoded = decode_cloudflare_email(match.group(1))
                if decoded and "@" in decoded and is_valid_email(decoded):
                    emails.append(decoded)
    
    # Method 4: Look in script tags for encoded patterns
    for script in soup.find_all("script"):
        script_text = script.get_text()
        # Find patterns like data-cfemail="..." in inline scripts
        cf_matches = re.findall(r'data-cfemail=["\']([a-fA-F0-9]+)["\']', script_text)
        for match in cf_matches:
            decoded = decode_cloudflare_email(match)
            if decoded and "@" in decoded and is_valid_email(decoded):
                emails.append(decoded)
    
    return list(set(emails))

def is_valid_email(email: str) -> bool:
    """Check if email is valid and not a protected placeholder."""
    if not email:
        return False
    
    email_lower = email.lower().strip()
    
    # Filter out protected/placeholder/invalid emails
    invalid_patterns = [
        "[email protected]",
        "[email\xa0protected]",
        "[email protected]",
        "email protected",
        "protected",
        "emailprotected",
        "example.com",
        "example@",
        "@example",
        "test@test",
        "your@email",
        "youremail@",
        "info@your",
        "your@domain",
        "email@email",
        "name@domain",
        "user@domain",
        "sample@",
        "@sample",
        "dummy@",
        "fake@",
        "placeholder",
        "xxxxx",
        "yyyyy",
        "zzzzz",
    ]
    
    for pattern in invalid_patterns:
        if pattern in email_lower:
            return False
    
    # Check for "[email" pattern (common protected indicator)
    if "[email" in email_lower or "email]" in email_lower:
        return False
    
    # Check for excessive special characters
    if email.count('@') != 1:
        return False
    
    # Basic email validation regex
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False
    
    # Check domain part has at least one dot
    domain = email.split('@')[1]
    if '.' not in domain:
        return False
    
    # Check TLD is reasonable length
    tld = domain.split('.')[-1]
    if len(tld) < 2 or len(tld) > 10:
        return False
    
    return True

def clean_email_list(emails: list) -> list:
    """Clean and validate a list of emails, removing invalid ones."""
    if not emails:
        return []
    
    cleaned = []
    for email in emails:
        if isinstance(email, str):
            email = email.strip()
            if is_valid_email(email):
                cleaned.append(email)
    
    return list(set(cleaned))

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
def extract_all_emails(text: str, html: str = None) -> list:
    """
    Extract all valid emails from text and HTML.
    Handles Cloudflare protection and filters invalid emails.
    """
    emails = []
    
    # Standard regex extraction from text
    if text:
        found = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
        emails.extend(found)
    
    # Extract Cloudflare protected emails from HTML
    if html:
        cf_emails = extract_cloudflare_emails(html)
        emails.extend(cf_emails)
        
        # Also try standard regex on HTML (might catch some in attributes)
        html_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)
        emails.extend(html_emails)
    
    # Clean and validate
    valid_emails = clean_email_list(emails)
    
    return valid_emails if valid_emails else []

def extract_all_phones(text):
    if not text:
        return []
    
    phones = []
    # Multiple patterns for different phone formats
    patterns = [
        r'\+?\d{1,4}[-.\s]?$?\d{1,4}$?[-.\s]?\d{1,4}[-.\s]?\d{1,9}',
        r'\+?\d[\d\-\s()]{8,15}',
        r'$\d{3}$\s*\d{3}[-.\s]?\d{4}',
        r'\d{3}[-.\s]\d{3}[-.\s]\d{4}',
    ]
    
    for pattern in patterns:
        found = re.findall(pattern, text)
        phones.extend(found)
    
    # Clean and deduplicate
    cleaned_phones = []
    for phone in phones:
        phone = phone.strip()
        # Must have at least 10 digits
        digits = re.sub(r'\D', '', phone)
        if len(digits) >= 10 and len(digits) <= 15:
            cleaned_phones.append(phone)
    
    return list(set(cleaned_phones))

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
            coll = chroma_client.get_or_create_collection(
                name=cname,
                embedding_function=openai_ef,
                metadata={"dimension": 3072}
            )
            
            def get_embeddings(texts):
                if isinstance(texts, str):
                    texts = [texts]
                if not isinstance(texts, list):
                    texts = [str(texts)]

                clean_texts = [str(t)[:8000] for t in texts]

                try:
                    resp = openai_client.embeddings.create(
                        model="text-embedding-3-large",
                        input=clean_texts
                    )
                    return [item.embedding for item in resp.data]
                except Exception as e:
                    print("❌ Embedding ERROR:", e)
                    raise

            print(f"✅ Using Chroma collection: {cname}")
            BATCH = 8

            chunks = [str(c).strip() for c in chunks if str(c).strip()]

            for b in range(0, len(chunks), BATCH):
                batch = chunks[b:b+BATCH]
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
            docs_list = res.get("documents", [])
            if docs_list and isinstance(docs_list, list):
                context = " ".join(docs_list[0]) if docs_list[0] else ""
            else:
                context = " ".join(chunks[:6])
        except Exception as e:
            print("⚠️ Chroma operation failed, falling back. Error:", str(e))
            context = " ".join(chunks[:6])
    else:
        context = " ".join(chunks[:6])

    prompt = f"""
You are a world-class business data extractor. Your job is to extract accurate business information from website content.

Extract the following fields:

1. **Business Name**: The official company/business name

2. **About Us**: A brief description of the company (2-3 sentences)

3. **Main Services**: List of services offered (as array)

4. **Email**: All business email addresses (as array)
   - ONLY include valid email addresses in format: name@domain.com
   - DO NOT include "[email protected]" or "[email protected]" - these are PROTECTED/INVALID
   - If you cannot find a valid email, return empty array []

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

7. **Facebook**: Facebook page URL (if found)

8. **Instagram**: Instagram profile URL (if found)

9. **LinkedIn**: LinkedIn company page URL (if found)

10. **Twitter / X**: Twitter/X profile URL (if found)

11. **Description**: A comprehensive 2-3 sentence description of what the business does

12. **URL**: {site_url}

IMPORTANT RULES:
- Return ONLY valid, complete information
- For emails: NEVER return "[email protected]" or protected emails - return [] instead
- For addresses, be VERY strict - only extract if it's a complete physical location
- If a field has no valid data, return empty array [] or empty string ""
- Return clean, properly formatted JSON ONLY (no markdown, no code blocks)

Website content to extract from:

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
        data = json.loads(out)
        
        # Post-process to clean emails
        if "Email" in data:
            data["Email"] = clean_email_list(data["Email"] if isinstance(data["Email"], list) else [data["Email"]])
        
        return data
    except:
        return {"raw": out}

# ---------------- Logo Extraction ----------------
def extract_logo_url(html, base_url):
    """Find logo URL from common locations."""
    soup = BeautifulSoup(html, "html.parser")

    logo_keywords = ["logo", "brand", "site-logo", "header-logo"]
    for img in soup.find_all("img", src=True):
        src = img["src"].lower()
        alt = (img.get("alt") or "").lower()

        if any(key in src for key in logo_keywords) or any(key in alt for key in logo_keywords):
            return urllib.parse.urljoin(base_url, img["src"])

    for link in soup.find_all("link", href=True):
        rel = (link.get("rel") or [""])[0]
        if "icon" in rel or "shortcut icon" in rel or "apple-touch-icon" in rel:
            return urllib.parse.urljoin(base_url, link["href"])

    return ""

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
    all_html = ""
    all_social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}

    # ---------------- Parallel Scrape ----------------
    def scrape_single_page(page):
        html = fetch_page(page)
        social = extract_social_links_from_html(html)
        soup = BeautifulSoup(html or "", "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = clean_text(soup.get_text(" ", strip=True))
        return text, social, html

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as exe:
        results = list(exe.map(scrape_single_page, main_pages))

    for text, social, html in results:
        all_text += " " + (text or "")
        all_html += " " + (html or "")
        for k, v in social.items():
            if v and not all_social[k]:
                all_social[k] = v

    all_text = clean_text(all_text)
    all_text = " ".join(dict.fromkeys(all_text.split()))

    chunks = chunk_text(all_text)

    print("\n🧠 Running RAG…")
    data = rag_extract(chunks, site_url)

    # fallback extraction — MULTIPLE (now with HTML for Cloudflare decoding)
    extracted_emails = extract_all_emails(all_text, all_html)
    if not data.get("Email") or not clean_email_list(data.get("Email", [])):
        data["Email"] = extracted_emails
    else:
        # Merge and clean
        existing = data.get("Email", [])
        if isinstance(existing, str):
            existing = [existing]
        all_emails = list(set(existing + extracted_emails))
        data["Email"] = clean_email_list(all_emails)
    
    data["Phone"] = data.get("Phone") or extract_all_phones(all_text)
    data["Address"] = data.get("Address") or extract_all_addresses(all_text)

    # social links
    for k, v in all_social.items():
        if v:
            data[k] = v

    data["URL"] = site_url

    # Final cleanup - ensure no protected emails slip through
    if "Email" in data:
        data["Email"] = clean_email_list(data["Email"] if isinstance(data["Email"], list) else [])

    print("\n\n✅ Final Extracted Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))