#!/usr/bin/env python3
"""
SUPER OPTIMIZED WEBSITE BOT — FINAL VERSION WITH THEME COLORS
Best multi-office extraction, perfect contacts, social links, and theme colors
Includes: Cloudflare email protection decoder, duplicate removal, color extraction
"""

import os
import re
import time
import json
import urllib.parse
import colorsys
from collections import Counter
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
    """Clean and normalize text by removing extra whitespace."""
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
        
        # Basic email validation regex
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


def normalize_social_url(url: str) -> str:
    """
    Normalize social URLs:
    - remove trailing \ and /
    - fix double slashes in path
    - preserve https://
    """
    if not url or not isinstance(url, str):
        return ""

    try:
        url = url.strip().rstrip("\\/ ")

        parsed = urllib.parse.urlparse(url)

        clean_path = re.sub(r'/+', '/', parsed.path)

        if clean_path != "/" and clean_path.endswith("/"):
            clean_path = clean_path.rstrip("/")

        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            clean_path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
    except Exception:
        return url


# ---------------- Fast Requests + Firecrawl Fetch ----------------
def fetch_page(url: str) -> str:
    """
    First try Requests.
    If content is too small or blocked, try Firecrawl with JS rendering.
    """
    html = ""
    
    # Try regular requests first
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            html = r.text
    except Exception:
        pass

    # Check if we got meaningful content
    # Next.js/React sites often have very little actual text content in initial HTML
    has_meaningful_content = False
    if html:
        # Check for common signs of JS-rendered content
        soup = BeautifulSoup(html, "html.parser")
        text_content = soup.get_text(" ", strip=True)
        
        # If text is too short OR contains Next.js indicators, content is likely JS-rendered
        is_nextjs = "__next" in html or "self.__next_f" in html or "_next/static" in html
        is_react = "react" in html.lower() and "__NEXT_DATA__" in html
        
        if len(text_content) > 1000 and not is_nextjs:
            has_meaningful_content = True
        
        # Also check if we found address/contact info
        if "380" in text_content or "ahmedabad" in text_content.lower():
            has_meaningful_content = True

    # Use Firecrawl if content seems JS-rendered or too small
    if not has_meaningful_content and FIRECRAWL_KEY:
        print(f"   🔥 Using Firecrawl for JS rendering: {url}")
        try:
            fc_url = "https://api.firecrawl.dev/v1/scrape"
            headers = {
                "Authorization": f"Bearer {FIRECRAWL_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "url": url,
                "formats": ["html"],
                "waitFor": 3000,  # Wait 3 seconds for JS to render
                "timeout": 30000
            }

            fc = requests.post(fc_url, json=payload, headers=headers, timeout=60)
            fc_data = fc.json()
            
            if fc_data.get("success"):
                fc_html = fc_data.get("data", {}).get("html", "")
                if fc_html and len(fc_html) > len(html):
                    html = fc_html
                    print(f"   ✅ Firecrawl returned {len(fc_html)} chars")
        except Exception as e:
            print(f"   ⚠️ Firecrawl error: {e}")

    return html if html and len(html) > 200 else ""

# ---------------- Enhanced Social Links Extraction ----------------
def extract_social_links_from_html(html):
    """
    Enhanced social media link extraction with multiple detection methods.
    """
    social = {
        "Facebook": "",
        "Instagram": "",
        "LinkedIn": "",
        "Twitter / X": "",
        "YouTube": "",
        "Pinterest": "",
        "TikTok": ""
    }
    
    if not html:
        return {k: social[k] for k in ["Facebook", "Instagram", "LinkedIn", "Twitter / X"]}
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Social media URL patterns (expanded)
        social_patterns = {
            "Facebook": [
                "facebook.com", "fb.com", "fb.me", 
                "m.facebook.com", "www.facebook.com",
                "business.facebook.com"
            ],
            "Instagram": [
                "instagram.com", "instagr.am", 
                "www.instagram.com", "m.instagram.com"
            ],
            "LinkedIn": [
                "linkedin.com", "www.linkedin.com", 
                "in.linkedin.com", "lnkd.in"
            ],
            "Twitter / X": [
                "twitter.com", "x.com", "www.twitter.com", 
                "mobile.twitter.com", "www.x.com"
            ],
            "YouTube": [
                "youtube.com", "youtu.be", "www.youtube.com",
                "m.youtube.com"
            ],
            "Pinterest": [
                "pinterest.com", "pin.it", "www.pinterest.com"
            ],
            "TikTok": [
                "tiktok.com", "www.tiktok.com", "vm.tiktok.com"
            ]
        }
        
        # Method 1: Standard <a> tag hrefs
        for a in soup.find_all("a", href=True):
            href = str(a.get("href", "")).strip()
            href_lower = href.lower()
            
            # Skip empty or javascript links
            if not href or href.startswith("javascript:") or href == "#":
                continue
            
            for platform, patterns in social_patterns.items():
                if not social[platform]:  # Only if not already found
                    for pattern in patterns:
                        if pattern in href_lower:
                            # Skip share/sharer links
                            if "share" in href_lower or "sharer" in href_lower:
                                continue
                            # Validate it's a proper URL
                            if href.startswith("http") or href.startswith("//"):
                                # social[platform] = href if href.startswith("http") else "https:" + href
                                raw = href if href.startswith("http") else "https:" + href
                                social[platform] = normalize_social_url(raw)
                                break
        
        # Method 2: Check data attributes (data-href, data-url, etc.)
        data_attrs = ["data-href", "data-url", "data-link", "data-social"]
        for attr in data_attrs:
            for elem in soup.find_all(attrs={attr: True}):
                href = str(elem.get(attr, "")).lower()
                original_href = elem.get(attr, "")
                for platform, patterns in social_patterns.items():
                    if not social[platform]:
                        for pattern in patterns:
                            if pattern in href:
                                if original_href.startswith("http") or original_href.startswith("//"):
                                    raw = original_href if original_href.startswith("http") else "https:" + original_href
                                    social[platform] = normalize_social_url(raw)
                                break
        
        # Method 3: Check aria-label and title attributes on links
        for a in soup.find_all("a"):
            aria_label = str(a.get("aria-label", "")).lower()
            title = str(a.get("title", "")).lower()
            href = str(a.get("href", ""))
            
            if not href or href == "#":
                continue
            
            platform_keywords = {
                "Facebook": ["facebook", "fb"],
                "Instagram": ["instagram", "insta"],
                "LinkedIn": ["linkedin"],
                "Twitter / X": ["twitter", "tweet", " x "],
                "YouTube": ["youtube", "yt"],
                "Pinterest": ["pinterest", "pin"],
                "TikTok": ["tiktok", "tik tok"]
            }
            
            for platform, keywords in platform_keywords.items():
                if not social[platform]:
                    for keyword in keywords:
                        if keyword in aria_label or keyword in title:
                            if href.startswith("http"):
                                social[platform] = normalize_social_url(href)
                            elif href.startswith("//"):
                                social[platform] = normalize_social_url("https:" + href)

                            break
        
        # Method 4: Check for social icons (font-awesome, etc.)
        icon_classes = {
            "Facebook": ["fa-facebook", "icon-facebook", "facebook-icon", "fb-icon", "fa-facebook-f", "fa-facebook-square"],
            "Instagram": ["fa-instagram", "icon-instagram", "instagram-icon", "ig-icon", "fa-instagram-square"],
            "LinkedIn": ["fa-linkedin", "icon-linkedin", "linkedin-icon", "li-icon", "fa-linkedin-in", "fa-linkedin-square"],
            "Twitter / X": ["fa-twitter", "fa-x-twitter", "icon-twitter", "twitter-icon", "x-icon", "fa-twitter-square", "fa-x"],
            "YouTube": ["fa-youtube", "icon-youtube", "youtube-icon", "yt-icon", "fa-youtube-play", "fa-youtube-square"],
            "Pinterest": ["fa-pinterest", "icon-pinterest", "pinterest-icon", "fa-pinterest-p", "fa-pinterest-square"],
            "TikTok": ["fa-tiktok", "icon-tiktok", "tiktok-icon"]
        }
        
        for platform, classes in icon_classes.items():
            if not social[platform]:
                for icon_class in classes:
                    # Find icon elements with this class
                    icons = soup.find_all(class_=lambda x: x and icon_class in str(x).lower())
                    for icon in icons:
                        # Check parent <a> tag
                        parent_a = icon.find_parent("a")
                        if parent_a and parent_a.get("href"):
                            href = parent_a.get("href")
                            if href and not href.startswith("javascript:") and href != "#":
                                if href.startswith("http") or href.startswith("//"):
                                    raw = href if href.startswith("http") else "https:" + href
                                    social[platform] = normalize_social_url(raw)
                                    break
                    if social[platform]:
                        break
        
        # Method 5: Search in onclick handlers
        for elem in soup.find_all(onclick=True):
            onclick = str(elem.get("onclick", ""))
            for platform, patterns in social_patterns.items():
                if not social[platform]:
                    for pattern in patterns:
                        if pattern in onclick.lower():
                            # Try to extract URL from onclick
                            url_match = re.search(r'(https?://[^\s\'"<>]+' + re.escape(pattern) + r'[^\s\'"<>]*)', onclick)
                            if url_match:
                                social[platform] = normalize_social_url(url_match.group(1))
                                break
        
        # Method 6: Look in JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                script_content = script.string or script.get_text()
                if script_content:
                    json_data = json.loads(script_content)
                    
                    # Handle both single object and array
                    if isinstance(json_data, list):
                        for item in json_data:
                            social = _extract_social_from_jsonld(item, social, social_patterns)
                    else:
                        social = _extract_social_from_jsonld(json_data, social, social_patterns)
            except json.JSONDecodeError:
                pass
            except Exception:
                pass
        
        # Method 7: Meta tags (og:see_also, article:author, etc.)
        for meta in soup.find_all("meta"):
            content = str(meta.get("content", ""))
            content_lower = content.lower()
            
            for platform, patterns in social_patterns.items():
                if not social[platform]:
                    for pattern in patterns:
                        if pattern in content_lower:
                            if content.startswith("http"):
                                social[platform] = normalize_social_url(content)
                                break
        
        # Method 8: Look for social widgets/embeds
        # Facebook widget
        if not social["Facebook"]:
            fb_widgets = soup.find_all("div", class_=lambda x: x and "fb-" in str(x).lower())
            for widget in fb_widgets:
                href = widget.get("data-href") or widget.get("data-url")
                if href and "facebook.com" in href.lower():
                    social["Facebook"] = normalize_social_url(href)
                    break
        
        # Method 9: Search in all text for social URLs
        page_text = str(soup)
        for platform, patterns in social_patterns.items():
            if not social[platform]:
                for pattern in patterns:
                    # Look for full URLs
                    url_pattern = rf'https?://(?:www\.)?{re.escape(pattern)}[^\s\'"<>\)}}]+'
                    matches = re.findall(url_pattern, page_text, re.IGNORECASE)
                    for match in matches:
                        # Skip share links
                        if "share" not in match.lower() and "sharer" not in match.lower():
                            social[platform] = normalize_social_url(match)
                            break
                    if social[platform]:
                        break
        for k in social:
            if social[k]:
                social[k] = normalize_social_url(social[k])

    except Exception as e:
        print(f"Error extracting social links: {e}")
    
    # Return only the standard 4 social platforms
    return {
        "Facebook": social.get("Facebook", ""),
        "Instagram": social.get("Instagram", ""),
        "LinkedIn": social.get("LinkedIn", ""),
        "Twitter / X": social.get("Twitter / X", "")
    }


def _extract_social_from_jsonld(data, social, patterns):
    """Helper to extract social links from JSON-LD data."""
    if not isinstance(data, dict):
        return social
    
    # Check sameAs property (common for social profiles)
    same_as = data.get("sameAs", [])
    if isinstance(same_as, str):
        same_as = [same_as]
    
    for url in same_as:
        url_lower = str(url).lower()
        for platform, platform_patterns in patterns.items():
            if not social[platform]:
                for pattern in platform_patterns:
                    if pattern in url_lower:
                        social[platform] = normalize_social_url(url)
                        break
    
    # Check other common properties
    social_properties = ["url", "contactPoint", "author", "publisher"]
    for prop in social_properties:
        value = data.get(prop)
        if isinstance(value, str):
            for platform, platform_patterns in patterns.items():
                if not social[platform]:
                    for pattern in platform_patterns:
                        if pattern in value.lower():
                            social[platform] = normalize_social_url(value)
                            break
        elif isinstance(value, dict):
            social = _extract_social_from_jsonld(value, social, patterns)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    social = _extract_social_from_jsonld(item, social, patterns)
                elif isinstance(item, str):
                    for platform, platform_patterns in patterns.items():
                        if not social[platform]:
                            for pattern in platform_patterns:
                                if pattern in item.lower():
                                    social[platform] = normalize_social_url(item)
                                    break
    
    # Check nested objects
    for key, value in data.items():
        if isinstance(value, dict):
            social = _extract_social_from_jsonld(value, social, patterns)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    social = _extract_social_from_jsonld(item, social, patterns)
    
    return social


# ---------------- Theme Color Extraction ----------------
def extract_theme_colors(html, base_url=None):
    """
    Extract theme/brand colors from a website.
    Returns primary color and color palette.
    """
    colors = {
        "primary_color": "",
        "secondary_color": "",
        "accent_color": "",
        "background_color": "",
        "text_color": "",
        "color_palette": []
    }
    
    if not html:
        return colors
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        found_colors = []
        
        # Method 1: Meta theme-color (highest priority - often brand color)
        theme_meta = soup.find("meta", attrs={"name": "theme-color"})
        if theme_meta and theme_meta.get("content"):
            color = normalize_color(theme_meta.get("content"))
            if color:
                colors["primary_color"] = color
                found_colors.append(("meta-theme", color, 100))  # Highest priority
        
        # Also check msapplication-TileColor
        tile_meta = soup.find("meta", attrs={"name": "msapplication-TileColor"})
        if tile_meta and tile_meta.get("content"):
            color = normalize_color(tile_meta.get("content"))
            if color and not colors["primary_color"]:
                colors["primary_color"] = color
                found_colors.append(("meta-tile", color, 95))
        
        # Check msapplication-navbutton-color
        nav_meta = soup.find("meta", attrs={"name": "msapplication-navbutton-color"})
        if nav_meta and nav_meta.get("content"):
            color = normalize_color(nav_meta.get("content"))
            if color:
                found_colors.append(("meta-nav", color, 90))
        
        # Check apple-mobile-web-app-status-bar-style (sometimes has color)
        apple_meta = soup.find("meta", attrs={"name": "apple-mobile-web-app-status-bar-style"})
        if apple_meta and apple_meta.get("content"):
            color = normalize_color(apple_meta.get("content"))
            if color:
                found_colors.append(("meta-apple", color, 85))
        
        # Collect all CSS content
        all_css = ""
        for style in soup.find_all("style"):
            all_css += (style.get_text() or "") + "\n"
        
        # Method 2: CSS Variables (high priority)
        css_var_patterns = [
            (r'--primary[^:]*:\s*([^;}\s]+)', 80),
            (r'--brand[^:]*:\s*([^;}\s]+)', 80),
            (r'--main-color[^:]*:\s*([^;}\s]+)', 78),
            (r'--accent[^:]*:\s*([^;}\s]+)', 75),
            (r'--theme[^:]*:\s*([^;}\s]+)', 75),
            (r'--color-primary[^:]*:\s*([^;}\s]+)', 80),
            (r'--color-brand[^:]*:\s*([^;}\s]+)', 80),
            (r'--color-accent[^:]*:\s*([^;}\s]+)', 75),
            (r'--secondary[^:]*:\s*([^;}\s]+)', 70),
            (r'--color-secondary[^:]*:\s*([^;}\s]+)', 70),
        ]
        
        for pattern, priority in css_var_patterns:
            matches = re.findall(pattern, all_css, re.IGNORECASE)
            for match in matches:
                color = normalize_color(match.strip())
                if color and not is_neutral_color(color):
                    found_colors.append(("css-var", color, priority))
                    if not colors["primary_color"]:
                        colors["primary_color"] = color
        
        # Method 3: Common CSS selectors for brand colors
        css_selector_patterns = [
            (r'\.btn-primary[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 70),
            (r'\.button-primary[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 70),
            (r'\.btn[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 60),
            (r'\.primary[^{]*\{[^}]*(?:background-)?color:\s*([^;}\s]+)', 65),
            (r'a[^{]*\{[^}]*color:\s*([^;}\s]+)', 50),
            (r'a:hover[^{]*\{[^}]*color:\s*([^;}\s]+)', 55),
            (r'header[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 60),
            (r'\.header[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 60),
            (r'nav[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 55),
            (r'\.navbar[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 55),
            (r'\.nav[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 55),
            (r'\.logo[^{]*\{[^}]*color:\s*([^;}\s]+)', 65),
            (r'\.brand[^{]*\{[^}]*color:\s*([^;}\s]+)', 65),
            (r'\.site-title[^{]*\{[^}]*color:\s*([^;}\s]+)', 60),
            (r'h1[^{]*\{[^}]*color:\s*([^;}\s]+)', 45),
            (r'\.cta[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 60),
            (r'\.hero[^{]*\{[^}]*background(?:-color)?:\s*([^;}\s]+)', 55),
        ]
        
        for pattern, priority in css_selector_patterns:
            matches = re.findall(pattern, all_css, re.IGNORECASE | re.DOTALL)
            for match in matches:
                color = normalize_color(match.strip())
                if color and not is_neutral_color(color):
                    found_colors.append(("css-rule", color, priority))
        
        # Method 4: Inline styles on key elements
        key_elements = [
            ("header", 60),
            ("nav", 55),
            (".header", 60),
            (".navbar", 55),
            (".logo", 65),
            (".brand", 65),
        ]
        
        for selector, priority in key_elements:
            if selector.startswith("."):
                elements = soup.find_all(class_=selector[1:])
            else:
                elements = soup.find_all(selector)
            
            for elem in elements:
                style = elem.get("style", "")
                if style:
                    bg_color = extract_color_from_style(style, "background")
                    if bg_color and not is_neutral_color(bg_color):
                        found_colors.append(("element-bg", bg_color, priority))
                    
                    text_color = extract_color_from_style(style, "color")
                    if text_color and not is_neutral_color(text_color):
                        found_colors.append(("element-text", text_color, priority - 5))
        
        # Method 5: Look for brand colors in class names and inline styles
        brand_keywords = ['brand', 'primary', 'accent', 'theme', 'main', 'logo', 'highlight']
        for keyword in brand_keywords:
            for elem in soup.find_all(class_=lambda x: x and keyword in str(x).lower()):
                style = elem.get("style", "")
                if style:
                    bg_color = extract_color_from_style(style, "background")
                    if bg_color and not is_neutral_color(bg_color):
                        found_colors.append(("brand-class", bg_color, 65))
                    
                    text_color = extract_color_from_style(style, "color")
                    if text_color and not is_neutral_color(text_color):
                        found_colors.append(("brand-class", text_color, 60))
        
        # Method 6: SVG fill colors (often used for logos)
        for svg in soup.find_all("svg"):
            fill = svg.get("fill")
            if fill:
                color = normalize_color(fill)
                if color and not is_neutral_color(color):
                    found_colors.append(("svg-fill", color, 55))
            
            for path in svg.find_all(["path", "rect", "circle", "polygon"]):
                fill = path.get("fill")
                if fill:
                    color = normalize_color(fill)
                    if color and not is_neutral_color(color):
                        found_colors.append(("svg-path", color, 50))
        
        # Method 7: Analyze most frequent non-neutral colors in CSS (FIXED REGEX)
        all_colors_in_css = re.findall(
            r'#[0-9a-fA-F]{3,6}\b|rgba?\([^)]+\)|hsla?\([^)]+\)',
            all_css,
            re.IGNORECASE
        )

        color_frequency = Counter()
        for c in all_colors_in_css:
            normalized = normalize_color(c)
            if normalized and not is_neutral_color(normalized):
                color_frequency[normalized] += 1
        
        # Add most frequent colors with lower priority
        for color, count in color_frequency.most_common(10):
            if count >= 2:  # Only if used multiple times
                priority = min(40 + count * 2, 55)  # More frequent = higher priority, max 55
                found_colors.append(("frequency", color, priority))
        
        # Method 8: Check for colors in inline HTML elements
        for elem in soup.find_all(style=True):
            style = elem.get("style", "")
            
            # Background color
            bg_match = re.search(r'background(?:-color)?:\s*([^;]+)', style, re.IGNORECASE)
            if bg_match:
                color = normalize_color(bg_match.group(1).strip().split()[0])
                if color and not is_neutral_color(color):
                    found_colors.append(("inline-bg", color, 40))
            
            # Text color (excluding background-color)
            color_match = re.search(r'(?<![a-z-])color:\s*([^;]+)', style, re.IGNORECASE)
            if color_match:
                color = normalize_color(color_match.group(1).strip().split()[0])
                if color and not is_neutral_color(color):
                    found_colors.append(("inline-text", color, 35))
        
        # Sort by priority and build final palette
        found_colors.sort(key=lambda x: x[2], reverse=True)
        
        seen_colors = set()
        palette = []
        
        for source, color, priority in found_colors:
            if color and color not in seen_colors:
                seen_colors.add(color)
                palette.append(color)
        
        # Set primary color if not already set
        if not colors["primary_color"] and palette:
            colors["primary_color"] = palette[0]
        
        # Set secondary and accent from remaining palette
        remaining = [c for c in palette if c != colors["primary_color"]]
        if remaining:
            colors["secondary_color"] = remaining[0]
        if len(remaining) > 1:
            colors["accent_color"] = remaining[1]
        
        # Try to identify background and text colors
        # Background is usually a light/neutral color
        for source, color, priority in found_colors:
            if "bg" in source.lower() or "background" in source.lower():
                if is_light_color(color):
                    colors["background_color"] = color
                    break
        
        # Text color is usually dark
        for source, color, priority in found_colors:
            if "text" in source.lower():
                if is_dark_color(color):
                    colors["text_color"] = color
                    break
        
        # Set color palette (limit to 6 unique colors)
        colors["color_palette"] = palette[:6]
        
    except Exception as e:
        print(f"Error extracting theme colors: {e}")
    
    return colors


def normalize_color(color_str):
    """
    Normalize a color string to hex format.
    Handles: hex, rgb(), rgba(), hsl(), hsla(), named colors
    """
    if not color_str:
        return ""
    
    color_str = str(color_str).strip().lower()
    
    # Skip CSS keywords that aren't colors
    skip_keywords = ['inherit', 'initial', 'unset', 'transparent', 'currentcolor', 
                     'none', 'auto', 'revert', 'revert-layer']
    if color_str in skip_keywords:
        return ""
    
    # Handle hex colors
    if color_str.startswith('#'):
        hex_color = color_str[1:]
        # Remove alpha channel if present (8 or 4 digit hex)
        if len(hex_color) == 8:
            hex_color = hex_color[:6]
        elif len(hex_color) == 4:
            hex_color = hex_color[:3]
        
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])
        if len(hex_color) == 6 and all(c in '0123456789abcdef' for c in hex_color):
            return '#' + hex_color.upper()
        return ""
    
    # Handle rgb/rgba
    rgb_match = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', color_str)
    if rgb_match:
        r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
            return '#{:02X}{:02X}{:02X}'.format(r, g, b)
        return ""
    
    # Handle hsl/hsla
    hsl_match = re.match(r'hsla?\s*\(\s*(\d+)\s*,\s*(\d+)%?\s*,\s*(\d+)%?', color_str)
    if hsl_match:
        h = int(hsl_match.group(1)) / 360
        s = int(hsl_match.group(2)) / 100
        l = int(hsl_match.group(3)) / 100
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        return '#{:02X}{:02X}{:02X}'.format(int(r*255), int(g*255), int(b*255))
    
    # Handle named colors (extended list)
    named_colors = {
        # Basic colors
        'red': '#FF0000', 'blue': '#0000FF', 'green': '#008000',
        'yellow': '#FFFF00', 'orange': '#FFA500', 'purple': '#800080',
        'pink': '#FFC0CB', 'cyan': '#00FFFF', 'magenta': '#FF00FF',
        'navy': '#000080', 'teal': '#008080', 'maroon': '#800000',
        'olive': '#808000', 'lime': '#00FF00', 'aqua': '#00FFFF',
        'fuchsia': '#FF00FF', 'silver': '#C0C0C0', 'gray': '#808080',
        'grey': '#808080', 'black': '#000000', 'white': '#FFFFFF',
        
        # Extended colors
        'indigo': '#4B0082', 'violet': '#EE82EE', 'gold': '#FFD700',
        'coral': '#FF7F50', 'salmon': '#FA8072', 'tomato': '#FF6347',
        'crimson': '#DC143C', 'darkblue': '#00008B', 'darkgreen': '#006400',
        'darkred': '#8B0000', 'lightblue': '#ADD8E6', 'lightgreen': '#90EE90',
        'skyblue': '#87CEEB', 'steelblue': '#4682B4', 'royalblue': '#4169E1',
        'slateblue': '#6A5ACD', 'mediumblue': '#0000CD', 'dodgerblue': '#1E90FF',
        'deepskyblue': '#00BFFF', 'turquoise': '#40E0D0', 'mediumturquoise': '#48D1CC',
        'darkturquoise': '#00CED1', 'cadetblue': '#5F9EA0', 'darkcyan': '#008B8B',
        'lightcyan': '#E0FFFF', 'paleturquoise': '#AFEEEE', 'aquamarine': '#7FFFD4',
        'mediumaquamarine': '#66CDAA', 'mediumspringgreen': '#00FA9A', 'springgreen': '#00FF7F',
        'seagreen': '#2E8B57', 'mediumseagreen': '#3CB371', 'lightseagreen': '#20B2AA',
        'darkslategray': '#2F4F4F', 'darkolivegreen': '#556B2F', 'olivedrab': '#6B8E23',
        'lawngreen': '#7CFC00', 'chartreuse': '#7FFF00', 'greenyellow': '#ADFF2F',
        'forestgreen': '#228B22', 'limegreen': '#32CD32',
        'palegreen': '#98FB98', 'darkseagreen': '#8FBC8F',
        'yellowgreen': '#9ACD32', 'beige': '#F5F5DC', 'ivory': '#FFFFF0',
        'lightyellow': '#FFFFE0', 'lemonchiffon': '#FFFACD', 'lightgoldenrodyellow': '#FAFAD2',
        'papayawhip': '#FFEFD5', 'moccasin': '#FFE4B5', 'peachpuff': '#FFDAB9',
        'palegoldenrod': '#EEE8AA', 'khaki': '#F0E68C', 'darkkhaki': '#BDB76B',
        'goldenrod': '#DAA520', 'darkgoldenrod': '#B8860B', 'saddlebrown': '#8B4513',
        'sienna': '#A0522D', 'chocolate': '#D2691E', 'peru': '#CD853F',
        'sandybrown': '#F4A460', 'burlywood': '#DEB887', 'tan': '#D2B48C',
        'rosybrown': '#BC8F8F', 'wheat': '#F5DEB3', 'navajowhite': '#FFDEAD',
        'bisque': '#FFE4C4', 'blanchedalmond': '#FFEBCD', 'cornsilk': '#FFF8DC',
        'orangered': '#FF4500', 'darkorange': '#FF8C00', 'lightsalmon': '#FFA07A',
        'lightcoral': '#F08080', 'indianred': '#CD5C5C', 'brown': '#A52A2A',
        'firebrick': '#B22222', 'hotpink': '#FF69B4',
        'deeppink': '#FF1493', 'mediumvioletred': '#C71585', 'palevioletred': '#DB7093',
        'lavender': '#E6E6FA', 'thistle': '#D8BFD8', 'plum': '#DDA0DD',
        'orchid': '#DA70D6', 'mediumorchid': '#BA55D3', 'darkorchid': '#9932CC',
        'darkviolet': '#9400D3', 'blueviolet': '#8A2BE2', 'mediumpurple': '#9370DB',
        'slategray': '#708090', 'lightslategray': '#778899',
        'dimgray': '#696969', 'lightgray': '#D3D3D3', 'darkgray': '#A9A9A9',
        'gainsboro': '#DCDCDC', 'whitesmoke': '#F5F5F5', 'ghostwhite': '#F8F8FF',
        'snow': '#FFFAFA', 'seashell': '#FFF5EE', 'linen': '#FAF0E6',
        'antiquewhite': '#FAEBD7', 'oldlace': '#FDF5E6', 'floralwhite': '#FFFAF0',
        'mintcream': '#F5FFFA', 'azure': '#F0FFFF', 'aliceblue': '#F0F8FF',
        'lavenderblush': '#FFF0F5', 'mistyrose': '#FFE4E1', 'honeydew': '#F0FFF0',
    }
    
    if color_str in named_colors:
        return named_colors[color_str]
    
    return ""


def is_neutral_color(hex_color):
    """
    Check if a color is neutral (black, white, or grayscale).
    Returns True for colors that shouldn't be considered "brand" colors.
    """
    if not hex_color or not hex_color.startswith('#'):
        return True
    
    try:
        hex_color = hex_color.upper()
        
        # Pure black/white
        if hex_color in ['#FFFFFF', '#000000', '#FFF', '#000']:
            return True
        
        # Parse RGB (FIXED)
        hex_value = hex_color[1:]
        if len(hex_value) == 3:
            r = int(hex_value[0] + hex_value[0], 16)
            g = int(hex_value[1] + hex_value[1], 16)
            b = int(hex_value[2] + hex_value[2], 16)
        elif len(hex_value) == 6:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
        else:
            return True
        
        # Check if grayscale (R ≈ G ≈ B)
        max_diff = max(abs(r-g), abs(g-b), abs(r-b))
        if max_diff < 20:  # Very close to grayscale
            return True
        
        # Check if too light (near white)
        if r > 245 and g > 245 and b > 245:
            return True
        
        # Check if too dark (near black)
        if r < 10 and g < 10 and b < 10:
            return True
        
        # Check saturation - low saturation = grayish
        max_rgb = max(r, g, b)
        min_rgb = min(r, g, b)
        if max_rgb > 0:
            saturation = (max_rgb - min_rgb) / max_rgb
            if saturation < 0.15:  # Very low saturation
                return True
        
        return False
        
    except Exception:
        return True


def is_light_color(hex_color):
    """Check if a color is light (high luminance)."""
    if not hex_color or not hex_color.startswith('#'):
        return False
    
    try:
        hex_value = hex_color[1:]
        if len(hex_value) == 3:
            # FIXED: Proper 3-char hex expansion
            r = int(hex_value[0] + hex_value[0], 16)
            g = int(hex_value[1] + hex_value[1], 16)
            b = int(hex_value[2] + hex_value[2], 16)
        elif len(hex_value) == 6:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
        else:
            return False
        
        # Calculate relative luminance
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance > 0.7
    except Exception:
        return False


def is_dark_color(hex_color):
    """Check if a color is dark (low luminance)."""
    if not hex_color or not hex_color.startswith('#'):
        return False
    
    try:
        hex_value = hex_color[1:]
        if len(hex_value) == 3:
            # FIXED: Proper 3-char hex expansion
            r = int(hex_value[0] + hex_value[0], 16)
            g = int(hex_value[1] + hex_value[1], 16)
            b = int(hex_value[2] + hex_value[2], 16)
        elif len(hex_value) == 6:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
        else:
            return False
        
        # Calculate relative luminance
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.3
    except Exception:
        return False


def extract_color_from_style(style_string, property_name):
    """Extract a color value from an inline style string."""
    if not style_string:
        return ""
    
    if property_name == "background":
        pattern = r'background(?:-color)?:\s*([^;]+)'
    elif property_name == "color":
        pattern = r'(?<![a-z-])color:\s*([^;]+)'
    else:
        pattern = rf'{property_name}:\s*([^;]+)'
    
    match = re.search(pattern, style_string, re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        # Handle multiple values (e.g., "red url(...)" or "linear-gradient(...)")
        # Skip gradients
        if 'gradient' in value.lower():
            return ""
        
        # Try to find a color value (FIXED REGEX)
        color_match = re.match(
            r'(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|hsla?\([^)]+\)|[a-z]+)',
            value,
            re.IGNORECASE
        )
        if color_match:
            return normalize_color(color_match.group(1))
    
    return ""


# ---------------- Contact Extraction (Multi) ----------------
def extract_all_emails(text: str, html: str = None) -> list:
    """
    Extract all valid emails from text and HTML.
    Handles Cloudflare protection and filters invalid emails.
    """
    emails = []
    
    try:
        # Standard regex extraction from text
        if text:
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
    
    # Safe patterns for phone extraction (FIXED REGEX)
    patterns = [
        r'\+?\d[\d\s().-]{8,15}',
        r'\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b',
        r'\+\d{1,3}\s?\d{4,5}\s?\d{4,6}',
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
    Extract physical addresses - supports Indian, US, and international formats.
    Ensures FULL address is captured including building numbers.
    """
    if not text:
        return []
    
    valid_addresses = []
    
    try:
        potential = []
        
        # Strategy 1: Find text around PIN codes (Indian 6-digit)
        # Look FURTHER BACK to capture building numbers
        pin_matches = list(re.finditer(r'\b(\d{6})\b', text))
        for match in pin_matches:
            # Look back further (200 chars) to capture full address
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 10)
            context = text[start:end].strip()
            
            # Find a good starting point (number, or after common delimiters)
            # Look for address start patterns
            address_start_patterns = [
                r'\b(\d{1,5}[,\s])',  # Starts with number
                r'(?:Address|Location|Office)[:\s]+',  # After label
                r'(?:\.\s+|\n\s*)(\d{1,5}[,\s])',  # After sentence, starts with number
            ]
            
            best_start = 0
            for pattern in address_start_patterns:
                match_start = re.search(pattern, context, re.IGNORECASE)
                if match_start:
                    best_start = match_start.start()
                    break
            
            # If we found a number at start, use it
            number_match = re.search(r'\b(\d{1,5})[,\s]+[A-Za-z]', context)
            if number_match and number_match.start() < 50:  # Number within first 50 chars
                best_start = number_match.start()
            
            context = context[best_start:].strip()
            
            # Clean up - remove text after PIN code
            pin_in_context = re.search(r'\b\d{6}\b', context)
            if pin_in_context:
                context = context[:pin_in_context.end()].strip()
            
            if len(context) > 20:
                potential.append(context)
        
        # Strategy 2: Direct pattern for Indian addresses starting with number
        indian_pattern = r'(\d{1,5}[,\s]+[A-Za-z][A-Za-z0-9\s,.\-/\'\"]+?(?:Gujarat|Maharashtra|Delhi|Karnataka|Rajasthan|Tamil Nadu|India)[,\s]*\d{6})'
        try:
            matches = re.findall(indian_pattern, text, re.IGNORECASE)
            potential.extend(matches)
        except:
            pass
        
        # Strategy 3: Pattern with building/tower/floor
        building_pattern = r'(\d{1,5}[,\s]+[A-Za-z][A-Za-z0-9\s,.\-/\'\"]+?(?:Tower|Building|Floor|Complex|Plaza|Block|Office)[A-Za-z0-9\s,.\-/\'\"]+?\d{6})'
        try:
            matches = re.findall(building_pattern, text, re.IGNORECASE)
            potential.extend(matches)
        except:
            pass
        
        # Strategy 4: Look for address after specific labels
        label_pattern = r'(?:Address|Location|Office|Headquarters|Contact)[:\s]+(\d{1,5}[,\s]+[A-Za-z][A-Za-z0-9\s,.\-/\'\"]{15,180}?\d{6})'
        try:
            matches = re.findall(label_pattern, text, re.IGNORECASE)
            potential.extend(matches)
        except:
            pass
        
        # Strategy 5: Generic pattern - number followed by text ending in PIN
        generic_pattern = r'(\d{1,5}[,\s]+[A-Za-z][A-Za-z0-9\s,.\-/\'\"]{20,180}?\b\d{6})\b'
        try:
            matches = re.findall(generic_pattern, text)
            potential.extend(matches)
        except:
            pass
        
        # Strategy 6: US ZIP pattern
        us_pattern = r'(\d{1,5}[,\s]+[A-Za-z][A-Za-z0-9\s,.\-]{15,100}\s+[A-Z]{2}\s*\d{5}(?:-\d{4})?)'
        try:
            matches = re.findall(us_pattern, text)
            potential.extend(matches)
        except:
            pass
        
        # Keywords for validation
        address_keywords = [
            'floor', 'tower', 'block', 'building', 'complex', 'plaza', 'office',
            'nagar', 'colony', 'society', 'road', 'street', 'lane', 'avenue',
            'sector', 'phase', 'near', 'opposite', 'marg', 'chowk', 'bh.', 'nr.'
        ]
        
        locations = [
            'ahmedabad', 'gujarat', 'mumbai', 'maharashtra', 'delhi',
            'bangalore', 'karnataka', 'chennai', 'india', 'pune',
            'hyderabad', 'kolkata', 'amraiwadi', 'surat', 'vadodara'
        ]
        
        blacklist = [
            'copyright', 'reserved', 'privacy', 'terms', 'cookie',
            'facebook', 'twitter', 'linkedin', 'instagram', '@',
            'click', 'subscribe', 'newsletter', 'loading'
        ]
        
        for addr in potential:
            if not isinstance(addr, str):
                continue
                
            addr = str(addr).strip()
            addr_lower = addr.lower()
            
            # Length check
            if len(addr) < 20 or len(addr) > 300:
                continue
            
            # Blacklist check
            if any(bl in addr_lower for bl in blacklist):
                continue
            
            # Must have PIN/ZIP
            has_pin = bool(re.search(r'\b\d{6}\b', addr))
            has_zip = bool(re.search(r'\b\d{5}\b', addr))
            
            if not (has_pin or has_zip):
                continue
            
            # Should have keyword or location
            has_keyword = any(kw in addr_lower for kw in address_keywords)
            has_location = any(loc in addr_lower for loc in locations)
            
            if has_pin or has_zip or has_keyword or has_location:
                # Clean up
                addr = re.sub(r'\s+', ' ', addr).strip()
                addr = addr.strip('.,;:|')
                addr = re.sub(r'$$email.*?$$', '', addr).strip()
                
                if len(addr) >= 20:
                    valid_addresses.append(addr)
                    
    except Exception as e:
        print(f"Address extraction error: {e}")
    
    return deduplicate_addresses(valid_addresses)

def deduplicate_addresses(addresses: list) -> list:
    """
    Remove duplicate addresses, including partial matches.
    ALWAYS keeps the LONGEST/MOST COMPLETE version.
    """
    if not addresses:
        return []
    
    # Sort by length (longest first) - so we process complete addresses first
    sorted_addresses = sorted(addresses, key=len, reverse=True)
    
    cleaned = []
    
    for addr in sorted_addresses:
        if not isinstance(addr, str):
            continue
            
        addr = addr.strip()
        if not addr or len(addr) < 10:
            continue
            
        # Normalize for comparison
        addr_normalized = re.sub(r'[,.\-\s]+', ' ', addr.lower()).strip()
        addr_normalized = re.sub(r'\s+', ' ', addr_normalized)
        
        is_duplicate = False
        
        for i, existing in enumerate(cleaned):
            existing_normalized = re.sub(r'[,.\-\s]+', ' ', existing.lower()).strip()
            existing_normalized = re.sub(r'\s+', ' ', existing_normalized)
            
            # Check if one contains the other
            if addr_normalized in existing_normalized:
                # Current is substring of existing (existing is longer/better)
                # Skip current - we already have a better version
                is_duplicate = True
                break
            elif existing_normalized in addr_normalized:
                # Existing is substring of current (current is longer/better)
                # Replace existing with current (the longer one)
                cleaned[i] = addr
                is_duplicate = True
                break
            
            # Check word overlap for fuzzy matching
            words1 = set(addr_normalized.split())
            words2 = set(existing_normalized.split())
            
            if words1 and words2:
                intersection = words1 & words2
                smaller_set = min(len(words1), len(words2))
                
                if smaller_set > 0 and len(intersection) / smaller_set > 0.7:
                    # 70% overlap - likely same address
                    # Keep the LONGER one (more complete)
                    if len(addr) > len(existing):
                        cleaned[i] = addr  # Replace with longer
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            cleaned.append(addr)
    
    return cleaned

def clean_address_list(addresses: list) -> list:
    """
    Clean and deduplicate addresses.
    Flexible validation for Indian, US, and international formats.
    """
    if not addresses:
        return []
    
    filtered = []
    
    # Words that should NOT appear in physical addresses
    invalid_words = [
        'association', 'college', 'university', 'school', 'hospital',
        'professor', 'doctor', 'training', 'faculty', 'speaker',
        'director', 'president', 'fellow', 'textbook', 'published',
        'articles', 'teaches', 'courses', 'medicine', 'pediatrics',
        'clinical', 'copyright', 'reserved', 'privacy', 'terms',
        'cookie', 'disclaimer', 'subscribe', 'newsletter', 'download',
        'facebook', 'twitter', 'linkedin', 'instagram', 'youtube'
    ]
    
    # Address indicator keywords (positive signals)
    address_keywords = [
        # Buildings/Structures
        'floor', 'tower', 'block', 'building', 'complex', 'plaza',
        'mall', 'center', 'centre', 'park', 'house', 'office',
        'suite', 'unit', 'shop', 'flat', 'plot', 'no.', 'no ',
        # Indian specific
        'nagar', 'colony', 'society', 'chowk', 'marg', 'road', 'rd',
        'gali', 'sector', 'phase', 'vihar', 'enclave', 'garden',
        'bazar', 'bazaar', 'market', 'near', 'opp', 'opposite', 
        'behind', 'beside', 'cross', 'main', 'layout', 'extension',
        'bh.', 'nr.', 'nr ', 'c.t.m', 'ctm',
        # US/Western
        'street', 'st.', 'st ', 'avenue', 'ave', 'drive', 'dr.',
        'lane', 'ln', 'boulevard', 'blvd', 'highway', 'hwy',
        'court', 'ct', 'way', 'place', 'pl', 'square', 'sq',
        'terrace', 'parkway', 'circle', 'route'
    ]
    
    # Location indicators (cities/states/countries)
    location_indicators = [
        # Indian cities
        'ahmedabad', 'mumbai', 'delhi', 'bangalore', 'bengaluru',
        'chennai', 'hyderabad', 'pune', 'kolkata', 'jaipur',
        'surat', 'vadodara', 'gandhinagar', 'rajkot', 'indore',
        'lucknow', 'noida', 'gurgaon', 'gurugram', 'chandigarh',
        'amraiwadi', 'bopal', 'satellite', 'navrangpura',
        # Indian states
        'gujarat', 'maharashtra', 'karnataka', 'tamil nadu',
        'telangana', 'rajasthan', 'uttar pradesh', 'haryana',
        'punjab', 'west bengal', 'madhya pradesh', 'kerala',
        # Countries
        'india', 'usa', 'uk', 'canada', 'australia'
    ]
    
    for addr in addresses:
        if not isinstance(addr, str):
            continue
            
        addr = addr.strip()
        addr_lower = addr.lower()
        
        # Length check (flexible)
        if len(addr) < 15 or len(addr) > 300:
            continue
        
        # Must NOT contain invalid words
        has_invalid = False
        for word in invalid_words:
            if word in addr_lower:
                has_invalid = True
                break
        
        if has_invalid:
            continue
        
        # Check for positive indicators
        has_pin = bool(re.search(r'\b\d{6}\b', addr))           # Indian PIN (6 digits)
        has_zip = bool(re.search(r'\b\d{5}(?:-\d{4})?\b', addr)) # US ZIP (5 or 9 digits)
        has_keyword = any(kw in addr_lower for kw in address_keywords)
        has_location = any(loc in addr_lower for loc in location_indicators)
        has_number = bool(re.search(r'\d', addr))               # Has any digit
        has_comma = ',' in addr                                  # Has comma (structure)
        word_count = len(addr.split())
        
        # Flexible validation rules (pass ANY of these):
        is_valid = False
        
        # Rule 1: Has PIN or ZIP code (strong indicator)
        if has_pin or has_zip:
            is_valid = True
        
        # Rule 2: Has address keyword + location name
        elif has_keyword and has_location:
            is_valid = True
        
        # Rule 3: Has keyword + number + comma (structured address)
        elif has_keyword and has_number and has_comma:
            is_valid = True
        
        # Rule 4: Has location + comma + reasonable length
        elif has_location and has_comma and word_count >= 4:
            is_valid = True
        
        # Rule 5: Has multiple keywords (very likely an address)
        elif sum(1 for kw in address_keywords if kw in addr_lower) >= 2:
            is_valid = True
        
        if is_valid:
            # Clean up the address
            addr = addr.strip().rstrip('.,;:|')
            
            # Remove email artifacts
            addr = re.sub(r'$$email.*?$$', '', addr)
            addr = re.sub(r'\s+', ' ', addr).strip()
            
            if len(addr) >= 15:  # Still valid length after cleaning
                filtered.append(addr)
    
    return deduplicate_addresses(filtered)

# ---------------- Smart Chunking ----------------
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping chunks for better context."""
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
    """Extract URLs from website sitemap."""
    try:
        sitemap_list = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/sitemap1.xml",
            "/sitemap-main.xml",
        ]
        urls = []

        for s in sitemap_list:
            try:
                sm = urllib.parse.urljoin(url, s)
                r = requests.get(sm, timeout=10)
                if r.status_code != 200:
                    continue

                soup = BeautifulSoup(r.text, "xml")

                # Handle sitemap index files
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
    """Get URLs using Firecrawl API."""
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
    """Get all URLs from a website using sitemap or Firecrawl."""
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
    """Select the most important pages to scrape."""
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

        logo_keywords = ["logo", "brand", "site-logo", "header-logo", "company-logo"]
        
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
        
        # Look for SVG logos
        for svg in soup.find_all("svg"):
            try:
                class_attr = " ".join(svg.get("class", [])).lower() if svg.get("class") else ""
                id_attr = str(svg.get("id") or "").lower()
                
                if any(key in class_attr for key in logo_keywords) or \
                   any(key in id_attr for key in logo_keywords):
                    # If SVG has a parent <a> with href, might be logo link
                    parent_a = svg.find_parent("a")
                    if parent_a:
                        # Return base URL as logo reference
                        return urllib.parse.urljoin(base_url, "/favicon.ico")
            except Exception:
                continue
                
    except Exception:
        pass

    # Fallback: try common favicon locations
    try:
        favicon_paths = ["/favicon.ico", "/favicon.png", "/apple-touch-icon.png"]
        for path in favicon_paths:
            favicon_url = urllib.parse.urljoin(base_url, path)
            try:
                r = requests.head(favicon_url, timeout=5)
                if r.status_code == 200:
                    return favicon_url
            except Exception:
                pass
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
    theme_colors = {}

    # ---------------- Parallel Scrape ----------------
    def scrape_single_page(page):
        try:
            html = fetch_page(page)
            social = extract_social_links_from_html(html)
            colors = extract_theme_colors(html, page)
            soup = BeautifulSoup(html or "", "html.parser")
            [s.extract() for s in soup(["script", "style", "noscript"])]
            text = clean_text(soup.get_text(" ", strip=True))
            return text, social, html, colors
        except Exception:
            return "", {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}, "", {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as exe:
        results = list(exe.map(scrape_single_page, main_pages))

    for text, social, html, colors in results:
        all_text += " " + (text or "")
        all_html += " " + (html or "")
        for k, v in social.items():
            if v and not all_social[k]:
                all_social[k] = v
        # Use first page's colors (usually homepage has brand colors)
        if not theme_colors.get("primary_color") and colors.get("primary_color"):
            theme_colors = colors

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

    # Theme colors
    data["Theme Colors"] = {
        "Primary": theme_colors.get("primary_color", ""),
        "Secondary": theme_colors.get("secondary_color", ""),
        "Accent": theme_colors.get("accent_color", ""),
        "Palette": theme_colors.get("color_palette", [])
    }

    # Logo
    logo_url = extract_logo_url(all_html, site_url)
    data["Logo"] = logo_url

    data["URL"] = site_url

    print("\n\n✅ Final Extracted Data:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    