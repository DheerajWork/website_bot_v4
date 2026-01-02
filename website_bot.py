#!/usr/bin/env python3
"""
SUPER OPTIMIZED WEBSITE BOT — FINAL VERSION
Best multi-office extraction, perfect contacts, with improved LLM accuracy
Includes: Cloudflare email protection decoder, duplicate removal
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
    if not t:
        return ""
    try:
        return re.sub(r"\s+", " ", str(t)).strip()
    except Exception:
        return str(t).strip()


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
        encoded_string = re.sub(r'[^a-fA-F0-9]', '', str(encoded_string))
        
        if len(encoded_string) < 4:
            return ""
            
        r = int(encoded_string[:2], 16)
        email = ''.join([
            chr(int(encoded_string[i:i+2], 16) ^ r) 
            for i in range(2, len(encoded_string), 2)
        ])
        return email
    except Exception:
        return ""


def extract_cloudflare_emails(html: str) -> list:
    """Extract emails protected by Cloudflare's email protection."""
    emails = []
    
    if not html:
        return emails
    
    try:
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
                try:
                    match = re.search(r'email-protection[#?]([a-fA-F0-9]+)', href)
                    if match:
                        decoded = decode_cloudflare_email(match.group(1))
                        if decoded and "@" in decoded and is_valid_email(decoded):
                            emails.append(decoded)
                except Exception:
                    pass
        
        # Method 4: Look in script tags for encoded patterns
        for script in soup.find_all("script"):
            try:
                script_text = script.get_text()
                cf_matches = re.findall(r'data-cfemail=["\']([a-fA-F0-9]+)["\']', script_text)
                for match in cf_matches:
                    decoded = decode_cloudflare_email(match)
                    if decoded and "@" in decoded and is_valid_email(decoded):
                        emails.append(decoded)
            except Exception:
                pass
    except Exception:
        pass
    
    return list(set(emails))


def is_valid_email(email: str) -> bool:
    """Check if email is valid and not a protected placeholder."""
    if not email:
        return False
    
    try:
        email_lower = str(email).lower().strip()
        
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
            "noreply",
            "no-reply",
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
        
        # Basic email validation regex - fixed pattern
        email_pattern = r'^[a-zA-Z0-9._+%-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
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
    except Exception:
        return False


def clean_email_list(emails: list) -> list:
    """Clean and validate a list of emails, removing invalid and duplicate ones (case-insensitive)."""
    if not emails:
        return []
    
    cleaned = []
    seen_lower = set()
    
    for email in emails:
        try:
            if isinstance(email, str):
                email = email.strip()
                email_lower = email.lower()
                
                if email_lower in seen_lower:
                    continue
                    
                if is_valid_email(email):
                    cleaned.append(email_lower)
                    seen_lower.add(email_lower)
        except Exception:
            continue
    
    return cleaned


def clean_phone_list(phones: list) -> list:
    """Clean and deduplicate phone numbers."""
    if not phones:
        return []
    
    cleaned = []
    seen_digits = set()
    
    for phone in phones:
        try:
            if isinstance(phone, str):
                phone = phone.strip()
                digits = re.sub(r'\D', '', phone)
                
                if len(digits) >= 10 and len(digits) <= 15 and digits not in seen_digits:
                    cleaned.append(phone)
                    seen_digits.add(digits)
        except Exception:
            continue
    
    return cleaned


def clean_address_list(addresses: list) -> list:
    """Clean and deduplicate addresses (case-insensitive, normalized)."""
    if not addresses:
        return []
    
    cleaned = []
    seen_normalized = set()
    
    for addr in addresses:
        try:
            if isinstance(addr, str):
                addr = addr.strip()
                # Normalize: lowercase, remove extra spaces, remove punctuation for comparison
                normalized = re.sub(r'[^\w\s]', '', addr.lower())
                normalized = re.sub(r'\s+', ' ', normalized).strip()
                
                if normalized and normalized not in seen_normalized:
                    cleaned.append(addr)
                    seen_normalized.add(normalized)
        except Exception:
            continue
    
    return cleaned


# ---------------- Fast Requests + Firecrawl Fetch ----------------
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
    except Exception:
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
        except Exception:
            pass

    return ""


# ---------------- Social Links Extraction ----------------
def extract_social_links_from_html(html):
    social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}
    
    if not html:
        return social
    
    try:
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = str(a["href"]).lower()
            original_href = str(a["href"])
            
            if "facebook.com" in href and not social["Facebook"]:
                social["Facebook"] = original_href
            if "instagram.com" in href and not social["Instagram"]:
                social["Instagram"] = original_href
            if "linkedin.com" in href and not social["LinkedIn"]:
                social["LinkedIn"] = original_href
            if ("twitter.com" in href or "x.com" in href) and not social["Twitter / X"]:
                social["Twitter / X"] = original_href
    except Exception:
        pass

    return social


# ---------------- Contact Extraction (Multi) ----------------
def extract_all_emails(text: str, html: str = None) -> list:
    """
    Extract all valid emails from text and HTML.
    Handles Cloudflare protection and filters invalid emails.
    """
    emails = []
    
    try:
        # Standard regex extraction from text - FIXED PATTERN
        if text:
            # Using a simpler, safer pattern
            found = re.findall(r'[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(text))
            emails.extend(found)
    except Exception:
        pass
    
    # Extract Cloudflare protected emails from HTML
    if html:
        try:
            cf_emails = extract_cloudflare_emails(html)
            emails.extend(cf_emails)
        except Exception:
            pass
        
        try:
            # Also try standard regex on HTML
            html_emails = re.findall(r'[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', str(html))
            emails.extend(html_emails)
        except Exception:
            pass
    
    # Clean and validate
    valid_emails = clean_email_list(emails)
    
    return valid_emails if valid_emails else []


def extract_all_phones(text: str) -> list:
    """Extract all valid phone numbers, removing duplicates."""
    if not text:
        return []
    
    phones = []
    
    # Safe patterns for phone extraction
    patterns = [
        r'\+?\d{1,4}[\s.-]?$?\d{1,4}$?[\s.-]?\d{1,4}[\s.-]?\d{1,9}',
        r'\+?\d[\d\s()-]{8,15}',
        r'$\d{3}$\s*\d{3}[\s.-]?\d{4}',
        r'\d{3}[\s.-]\d{3}[\s.-]\d{4}',
    ]
    
    for pattern in patterns:
        try:
            found = re.findall(pattern, str(text))
            phones.extend(found)
        except Exception:
            continue
    
    # Clean and deduplicate
    cleaned_phones = []
    seen_digits = set()
    
    for phone in phones:
        try:
            phone = str(phone).strip()
            digits = re.sub(r'\D', '', phone)
            
            # Must have at least 10 digits and not seen before
            if len(digits) >= 10 and len(digits) <= 15 and digits not in seen_digits:
                cleaned_phones.append(phone)
                seen_digits.add(digits)
        except Exception:
            continue
    
    return cleaned_phones


def extract_all_addresses(text: str) -> list:
    """
    Strict regex fallback for addresses - only extracts if it contains address keywords.
    """
    if not text:
        return []
    
    valid_addresses = []
    
    try:
        # Pattern: starts with 1-4 digits, followed by address-like text
        pattern = r'\d{1,4}[\s,]+[A-Za-z0-9\s,.()-]{20,200}'
        potential_addresses = re.findall(pattern, str(text))
        
        # Address keywords
        address_keywords = r'\b(street|st|road|rd|avenue|ave|lane|ln|drive|dr|complex|building|floor|suite|office|near|opposite|highway|hwy|mall|square|circle|nagar|society|tower|plaza|block|sector|phase|colony|apartment|apt)\b'
        
        for addr in potential_addresses:
            try:
                addr = addr.strip()
                
                # Must contain address keywords
                if re.search(address_keywords, addr, re.IGNORECASE):
                    # Skip if it has dates/years
                    if not re.search(r'\b(19|20)\d{2}\b', addr):
                        # Skip if too many digits (phone numbers)
                        digit_ratio = sum(c.isdigit() for c in addr) / max(len(addr), 1)
                        if digit_ratio < 0.3:
                            valid_addresses.append(addr)
            except Exception:
                continue
    except Exception:
        pass
    
    return clean_address_list(valid_addresses)


# ---------------- Smart Chunking ----------------
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = clean_text(text)
    if not text:
        return []
    
    try:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks, current = [], ""

        for s in sentences:
            if len(current.split()) + len(s.split()) <= size:
                current += " " + s
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = s

        if current.strip():
            chunks.append(current.strip())

        return chunks
    except Exception:
        # Fallback: simple word-based chunking
        words = text.split()
        chunks = []
        for i in range(0, len(words), size - overlap):
            chunk = " ".join(words[i:i + size])
            if chunk:
                chunks.append(chunk)
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
            try:
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
                        except Exception:
                            pass

                urls += [x.get_text().strip() for x in soup.find_all("loc")]
            except Exception:
                continue

        return list(set(urls))
    except Exception:
        return []


def get_urls_from_firecrawl(base_url):
    if not FIRECRAWL_KEY:
        return []
    
    try:
        url = "https://api.firecrawl.dev/v2/map"
        headers = {"Authorization": f"Bearer {FIRECRAWL_KEY}"}
        payload = {"url": base_url}

        r = requests.post(url, json=payload, headers=headers, timeout=30)
        links = r.json().get("links", [])
        
        if isinstance(links, list):
            return [x.get("url", x) if isinstance(x, dict) else str(x) for x in links]
        return []
    except Exception:
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
        try:
            ul = str(u).lower()
            if "about" in ul: 
                pages.append(u)
            if "contact" in ul: 
                pages.append(u)
        except Exception:
            continue

    if base not in pages:
        pages.insert(0, base)

    # Remove duplicates, keep order, limit to 3
    seen = set()
    unique_pages = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            unique_pages.append(p)
    
    return unique_pages[:3]


# ---------------- RAG Extraction ----------------
def sanitize_collection_name(url):
    """Create a safe collection name from URL."""
    try:
        # Remove protocol
        name = re.sub(r'^https?://', '', str(url))
        # Remove www
        name = re.sub(r'^www\.', '', name)
        # Replace all non-alphanumeric with underscore
        name = re.sub(r'[^a-zA-Z0-9]', '_', name)
        # Remove leading/trailing underscores
        name = name.strip('_')
        # Collapse multiple underscores
        name = re.sub(r'_+', '_', name)
        # Ensure it starts with a letter
        if name and not name[0].isalpha():
            name = 'c_' + name
        if not name:
            name = "default_collection"
        # ChromaDB name limit is 63 characters
        return name[:63]
    except Exception:
        return "default_collection"


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
                
                # Create safe IDs
                ids = [f"chunk_{b+i}_{hash(site_url) % 10000}" for i in range(len(batch))]
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
   - DO NOT include duplicates (case-insensitive)
   - If you cannot find a valid email, return empty array []

5. **Phone**: All business phone numbers (as array)
   - DO NOT include duplicates

6. **Address**: ONLY complete physical office/business addresses (as array)
   - MUST include: Street number, street/building name, area/locality, city, state/region
   - MUST contain address keywords like: Street, Road, Complex, Building, Mall, Highway, Avenue, Lane, Square, Nagar, Society, Floor, Suite, Office, Tower, Plaza
   - DO NOT include:
     * Business hours
     * Timestamps or dates
     * Review counts
     * Social media text
     * Phone numbers appearing alone
     * Promotional text
     * Incomplete fragments
   - DO NOT include duplicates

7. **Facebook**: Facebook page URL (if found)

8. **Instagram**: Instagram profile URL (if found)

9. **LinkedIn**: LinkedIn company page URL (if found)

10. **Twitter / X**: Twitter/X profile URL (if found)

11. **Description**: A comprehensive 2-3 sentence description of what the business does

12. **URL**: {site_url}

IMPORTANT RULES:
- Return ONLY valid, complete information
- For emails: NEVER return "[email protected]" or protected emails - return [] instead
- Remove ALL duplicates (case-insensitive for emails)
- For addresses, be VERY strict - only extract if it's a complete physical location
- If a field has no valid data, return empty array [] or empty string ""
- Return clean, properly formatted JSON ONLY (no markdown, no code blocks)

Website content to extract from:

{context}
"""

    try:
        r = openai_client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )

        out = r.choices[0].message.content
        out = re.sub(r'```json|```', '', out).strip()

        try:
            data = json.loads(out)
            
            # Post-process to clean and deduplicate all fields
            if "Email" in data:
                emails = data["Email"] if isinstance(data["Email"], list) else [data["Email"]] if data["Email"] else []
                data["Email"] = clean_email_list(emails)
            
            if "Phone" in data:
                phones = data["Phone"] if isinstance(data["Phone"], list) else [data["Phone"]] if data["Phone"] else []
                data["Phone"] = clean_phone_list(phones)
                
            if "Address" in data:
                addresses = data["Address"] if isinstance(data["Address"], list) else [data["Address"]] if data["Address"] else []
                data["Address"] = clean_address_list(addresses)
            
            return data
        except json.JSONDecodeError:
            return {"raw": out}
    except Exception as e:
        print(f"❌ OpenAI API error: {e}")
        return {}


# ---------------- Logo Extraction ----------------
def extract_logo_url(html, base_url):
    """Find logo URL from common locations."""
    if not html:
        return ""
    
    try:
        soup = BeautifulSoup(html, "html.parser")

        logo_keywords = ["logo", "brand", "site-logo", "header-logo"]
        
        # Look for <img> with logo keywords
        for img in soup.find_all("img", src=True):
            try:
                src = str(img["src"]).lower()
                alt = str(img.get("alt") or "").lower()
                class_attr = " ".join(img.get("class", [])).lower() if img.get("class") else ""
                id_attr = str(img.get("id") or "").lower()

                if any(key in src for key in logo_keywords) or \
                   any(key in alt for key in logo_keywords) or \
                   any(key in class_attr for key in logo_keywords) or \
                   any(key in id_attr for key in logo_keywords):
                    return urllib.parse.urljoin(base_url, img["src"])
            except Exception:
                continue

        # Look inside <link rel="icon">
        for link in soup.find_all("link", href=True):
            try:
                rel = " ".join(link.get("rel", [])) if link.get("rel") else ""
                if "icon" in rel or "shortcut" in rel or "apple-touch-icon" in rel:
                    return urllib.parse.urljoin(base_url, link["href"])
            except Exception:
                continue
    except Exception:
        pass

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
        try:
            html = fetch_page(page)
            social = extract_social_links_from_html(html)
            soup = BeautifulSoup(html or "", "html.parser")
            [s.extract() for s in soup(["script", "style", "noscript"])]
            text = clean_text(soup.get_text(" ", strip=True))
            return text, social, html
        except Exception:
            return "", {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}, ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as exe:
        results = list(exe.map(scrape_single_page, main_pages))

    for text, social, html in results:
        all_text += " " + (text or "")
        all_html += " " + (html or "")
        for k, v in social.items():
            if v and not all_social[k]:
                all_social[k] = v

    all_text = clean_text(all_text)
    
    # Remove duplicate words while preserving order
    try:
        all_text = " ".join(dict.fromkeys(all_text.split()))
    except Exception:
        pass

    chunks = chunk_text(all_text)

    print("\n🧠 Running RAG…")
    data = rag_extract(chunks, site_url)

    # Fallback extraction with deduplication
    extracted_emails = extract_all_emails(all_text, all_html)
    existing_emails = data.get("Email", [])
    if isinstance(existing_emails, str):
        existing_emails = [existing_emails] if existing_emails else []
    if not isinstance(existing_emails, list):
        existing_emails = []
    all_emails = existing_emails + extracted_emails
    data["Email"] = clean_email_list(all_emails)

    # Clean phones
    extracted_phones = extract_all_phones(all_text)
    existing_phones = data.get("Phone", [])
    if isinstance(existing_phones, str):
        existing_phones = [existing_phones] if existing_phones else []
    if not isinstance(existing_phones, list):
        existing_phones = []
    all_phones = existing_phones + extracted_phones
    data["Phone"] = clean_phone_list(all_phones)

    # Clean addresses
    extracted_addresses = extract_all_addresses(all_text)
    existing_addresses = data.get("Address", [])
    if isinstance(existing_addresses, str):
        existing_addresses = [existing_addresses] if existing_addresses else []
    if not isinstance(existing_addresses, list):
        existing_addresses = []
    all_addresses = existing_addresses + extracted_addresses
    data["Address"] = clean_address_list(all_addresses)

    # Social links
    for k, v in all_social.items():
        if v:
            data[k] = v

    data["URL"] = site_url

    print("\n\n✅ Final Extracted Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))