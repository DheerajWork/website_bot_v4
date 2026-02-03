#!/usr/bin/env python3
"""
FastAPI Web Scraper API
Extracts business information, social links, and theme colors from websites.
With Debug Endpoints for troubleshooting.
"""

from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any
import traceback
import json
import re
import shutil
from pathlib import Path

# Import website_bot
try:
    import website_bot
    import importlib
    importlib.reload(website_bot)
    print("✅ website_bot imported successfully")
except Exception as e:
    print(f"❌ Error importing website_bot: {e}")
    raise

# Initialize FastAPI app
app = FastAPI(
    title="Website Info Extractor API",
    description="Extract business information, contacts, social links, and theme colors from websites",
    version="2.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create API router
router = APIRouter(prefix="/api")


# ---------------- Pydantic Models ----------------
class URLRequest(BaseModel):
    url: str = Field(..., description="The website URL to scrape")
    force_refresh: bool = Field(False, description="Clear cache and re-scrape")
    debug: bool = Field(False, description="Include debug information in response")


class ThemeColors(BaseModel):
    Primary: str = ""
    Secondary: str = ""
    Accent: str = ""
    Palette: List[str] = []


class ScrapedData(BaseModel):
    Business_Name: Optional[str] = Field(None, alias="Business Name")
    About_Us: Optional[str] = Field(None, alias="About Us")
    Main_Services: Optional[List[str]] = Field(None, alias="Main Services")
    Description: Optional[str] = None
    Email: Optional[List[str]] = None
    Phone: Optional[List[str]] = None
    Address: Optional[List[str]] = None
    Facebook: Optional[str] = None
    Instagram: Optional[str] = None
    LinkedIn: Optional[str] = None
    Twitter_X: Optional[str] = Field(None, alias="Twitter / X")
    Logo: Optional[str] = None
    Theme_Colors: Optional[Dict[str, Any]] = Field(None, alias="Theme Colors")
    URL: Optional[str] = None

    class Config:
        populate_by_name = True


class ScrapeResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]


# ================== DEBUG ENDPOINTS ==================

@router.post("/debug/address")
def debug_address_extraction(request: URLRequest):
    """
    🔍 DEBUG: See exactly why addresses aren't being extracted.
    Returns detailed information about the extraction process.
    """
    site_url = request.url.strip()
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        print(f"\n{'='*60}")
        print(f"🔍 DEBUG ADDRESS EXTRACTION: {site_url}")
        print(f"{'='*60}\n")
        
        # Get pages
        all_urls = website_bot.get_site_urls(site_url)
        main_pages = website_bot.select_main_pages(all_urls, site_url)
        
        debug_info = {
            "url": site_url,
            "pages_found": len(all_urls),
            "pages_scraped": main_pages,
            "raw_text_samples": [],
            "html_analysis": {},
            "pin_codes_found": [],
            "zip_codes_found": [],
            "address_keywords_found": [],
            "potential_address_contexts": [],
            "addresses_after_extraction": [],
            "addresses_after_cleaning": [],
            "footer_content": "",
            "contact_elements": [],
            "issues_detected": []
        }
        
        all_text = ""
        all_html = ""
        
        for page in main_pages:
            try:
                print(f"📄 Fetching: {page}")
                html = website_bot.fetch_page(page)
                
                if not html:
                    debug_info["issues_detected"].append(f"No HTML returned for {page}")
                    continue
                
                all_html += " " + html
                
                # Analyze HTML
                html_lower = html.lower()
                page_analysis = {
                    "page": page,
                    "html_length": len(html),
                    "is_nextjs": "__next" in html or "_next/static" in html,
                    "is_react": "react" in html_lower,
                    "has_address_word": "address" in html_lower,
                    "has_location_word": "location" in html_lower,
                    "has_ahmedabad": "ahmedabad" in html_lower,
                    "has_gujarat": "gujarat" in html_lower,
                    "has_india": "india" in html_lower,
                    "pin_codes_in_html": re.findall(r'\b\d{6}\b', html)[:5],
                }
                debug_info["html_analysis"][page] = page_analysis
                
                # Extract text
                soup = BeautifulSoup(html, "html.parser")
                [s.extract() for s in soup(["script", "style", "noscript"])]
                page_text = website_bot.clean_text(soup.get_text(" ", strip=True))
                all_text += " " + page_text
                
                # Sample of text
                debug_info["raw_text_samples"].append({
                    "page": page,
                    "text_length": len(page_text),
                    "first_500_chars": page_text[:500] if page_text else "",
                    "last_500_chars": page_text[-500:] if len(page_text) > 500 else ""
                })
                
                # Check footer
                footer = soup.find("footer")
                if footer:
                    footer_text = footer.get_text(" ", strip=True)
                    if footer_text:
                        debug_info["footer_content"] = footer_text[:1000]
                
                # Check contact/address elements
                address_selectors = [
                    ("class", "address"),
                    ("class", "contact"),
                    ("class", "location"),
                    ("id", "address"),
                    ("id", "contact"),
                    ("itemprop", "address"),
                ]
                
                for attr, value in address_selectors:
                    if attr == "class":
                        elements = soup.find_all(class_=lambda x: x and value in str(x).lower())
                    elif attr == "id":
                        elements = soup.find_all(id=lambda x: x and value in str(x).lower())
                    else:
                        elements = soup.find_all(attrs={attr: True})
                    
                    for elem in elements[:3]:
                        elem_text = elem.get_text(" ", strip=True)[:300]
                        if elem_text:
                            debug_info["contact_elements"].append({
                                "selector": f"{attr}={value}",
                                "text": elem_text
                            })
                
            except Exception as e:
                debug_info["issues_detected"].append(f"Error on {page}: {str(e)}")
        
        # Analyze extracted text
        text_lower = all_text.lower()
        
        # Find PIN codes
        pin_codes = list(set(re.findall(r'\b\d{6}\b', all_text)))
        debug_info["pin_codes_found"] = pin_codes
        
        # Find ZIP codes
        zip_codes = list(set(re.findall(r'\b\d{5}\b', all_text)))[:10]
        debug_info["zip_codes_found"] = zip_codes
        
        # Check for address keywords
        address_keywords = [
            'ahmedabad', 'gujarat', 'india', 'mumbai', 'delhi', 'bangalore',
            'floor', 'tower', 'building', 'office', 'road', 'street', 
            'nagar', 'colony', 'sector', 'block', 'near', 'opposite'
        ]
        
        for kw in address_keywords:
            if kw in text_lower:
                debug_info["address_keywords_found"].append(kw)
                
                # Find context around keyword
                idx = text_lower.find(kw)
                if idx != -1:
                    start = max(0, idx - 80)
                    end = min(len(all_text), idx + 120)
                    context = all_text[start:end].strip()
                    debug_info["potential_address_contexts"].append({
                        "keyword": kw,
                        "context": context
                    })
        
        # Run extraction
        print("\n🔧 Running extract_all_addresses()...")
        try:
            extracted = website_bot.extract_all_addresses(all_text)
            debug_info["addresses_after_extraction"] = extracted
            print(f"   Extracted: {extracted}")
        except Exception as e:
            debug_info["issues_detected"].append(f"Extraction error: {str(e)}")
            extracted = []
        
        # Run cleaning
        print("🔧 Running clean_address_list()...")
        try:
            cleaned = website_bot.clean_address_list(extracted)
            debug_info["addresses_after_cleaning"] = cleaned
            print(f"   Cleaned: {cleaned}")
        except Exception as e:
            debug_info["issues_detected"].append(f"Cleaning error: {str(e)}")
        
        # Detect issues
        if not pin_codes and not zip_codes:
            debug_info["issues_detected"].append("❌ No PIN/ZIP codes found in text - address might be JS rendered")
        
        if not debug_info["address_keywords_found"]:
            debug_info["issues_detected"].append("❌ No address keywords found")
        
        if any(a.get("is_nextjs") for a in debug_info["html_analysis"].values()):
            debug_info["issues_detected"].append("⚠️ Site appears to be Next.js - may need Firecrawl for full content")
        
        if extracted and not cleaned:
            debug_info["issues_detected"].append("⚠️ Addresses found but filtered out by clean_address_list()")
        
        # Summary
        debug_info["summary"] = {
            "total_text_length": len(all_text),
            "pages_scraped": len(main_pages),
            "pin_codes_count": len(pin_codes),
            "keywords_found_count": len(debug_info["address_keywords_found"]),
            "addresses_extracted": len(extracted),
            "addresses_after_clean": len(cleaned),
            "issues_count": len(debug_info["issues_detected"])
        }
        
        print(f"\n✅ Debug complete. Issues: {len(debug_info['issues_detected'])}")
        
        return {
            "success": True,
            "message": "Debug info collected",
            "debug": debug_info
        }
        
    except Exception as e:
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@router.post("/debug/raw-html")
def debug_raw_html(request: URLRequest):
    """
    🔍 DEBUG: Get raw HTML content from a page.
    Useful to see what content is actually being fetched.
    """
    site_url = request.url.strip()
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        html = website_bot.fetch_page(site_url)
        
        if not html:
            return {
                "success": False,
                "message": "No HTML content fetched",
                "url": site_url
            }
        
        soup = BeautifulSoup(html, "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = soup.get_text(" ", strip=True)
        
        return {
            "success": True,
            "url": site_url,
            "html_length": len(html),
            "text_length": len(text),
            "html_preview": html[:3000] + "..." if len(html) > 3000 else html,
            "text_preview": text[:2000] + "..." if len(text) > 2000 else text,
            "contains": {
                "address": "address" in html.lower(),
                "contact": "contact" in html.lower(),
                "email": "email" in html.lower() or "@" in html,
                "phone": "phone" in html.lower() or "tel:" in html.lower(),
                "pin_codes": re.findall(r'\b\d{6}\b', html)[:10],
                "is_nextjs": "__next" in html,
                "is_react": "react" in html.lower()
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/debug/test-patterns")
def debug_test_patterns(request: URLRequest):
    """
    🔍 DEBUG: Test address extraction patterns on a URL.
    Shows what each regex pattern finds.
    """
    site_url = request.url.strip()
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        # Fetch and get text
        html = website_bot.fetch_page(site_url)
        soup = BeautifulSoup(html or "", "html.parser")
        [s.extract() for s in soup(["script", "style", "noscript"])]
        text = website_bot.clean_text(soup.get_text(" ", strip=True))
        
        # Test patterns
        patterns = {
            "indian_pin_context": r'([A-Za-z0-9][A-Za-z0-9\s,.\-/]{10,150}?\b\d{6})\b',
            "starts_with_number": r'\b(\d{1,5}[,\s]+[A-Za-z][A-Za-z0-9\s,.\-/]{10,120})',
            "us_zip_with_state": r'([A-Za-z0-9][A-Za-z0-9\s,.\-]{15,100}\s+[A-Z]{2}\s*\d{5}(?:-\d{4})?)\b',
            "after_address_label": r'(?:Address|Location|Office)[:\s]+([A-Za-z0-9#/,.\s\-]{15,200})',
            "near_opposite_pattern": r'((?:Near|Opp\.?|Opposite|Behind)[A-Za-z0-9\s,.\-]{15,120}\d{6})',
            "floor_building_pattern": r'((?:Floor|Office|Tower|Building)[^,]*,[^,]+,[^,]+)',
        }
        
        results = {}
        for name, pattern in patterns.items():
            try:
                matches = re.findall(pattern, text, re.IGNORECASE)
                results[name] = {
                    "matches_count": len(matches),
                    "matches": matches[:5]  # Limit to 5
                }
            except Exception as e:
                results[name] = {"error": str(e)}
        
        return {
            "success": True,
            "url": site_url,
            "text_length": len(text),
            "pattern_results": results,
            "text_sample": text[:1500]
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ================== CACHE MANAGEMENT ==================

@router.post("/cache/clear-all")
def clear_all_cache():
    """
    🗑️ Clear ALL ChromaDB collections (full cache reset).
    """
    try:
        if website_bot.chroma_client is None:
            return {
                "success": False,
                "message": "ChromaDB client not initialized"
            }
        
        collections = website_bot.chroma_client.list_collections()
        deleted = []
        errors = []
        
        for collection in collections:
            try:
                website_bot.chroma_client.delete_collection(name=collection.name)
                deleted.append(collection.name)
                print(f"🗑️ Deleted: {collection.name}")
            except Exception as e:
                errors.append({"collection": collection.name, "error": str(e)})
        
        return {
            "success": True,
            "message": f"Cleared {len(deleted)} collections",
            "deleted": deleted,
            "errors": errors if errors else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/cache/clear")
def clear_url_cache(request: URLRequest):
    """
    🗑️ Clear ChromaDB cache for a specific URL.
    """
    site_url = request.url.strip()
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        if website_bot.chroma_client is None:
            return {
                "success": False,
                "message": "ChromaDB client not initialized"
            }
        
        collection_name = website_bot.sanitize_collection_name(site_url)
        
        try:
            website_bot.chroma_client.delete_collection(name=collection_name)
            return {
                "success": True,
                "message": f"Cache cleared for {site_url}",
                "collection_name": collection_name
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Collection not found or error: {str(e)}",
                "collection_name": collection_name
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/cache/list")
def list_cache():
    """
    📋 List all cached collections in ChromaDB.
    """
    try:
        if website_bot.chroma_client is None:
            return {
                "success": False,
                "message": "ChromaDB client not initialized"
            }
        
        collections = website_bot.chroma_client.list_collections()
        
        collection_info = []
        for coll in collections:
            try:
                count = coll.count()
                collection_info.append({
                    "name": coll.name,
                    "document_count": count
                })
            except:
                collection_info.append({
                    "name": coll.name,
                    "document_count": "unknown"
                })
        
        return {
            "success": True,
            "total_collections": len(collections),
            "collections": collection_info
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.delete("/cache/reset-directory")
def reset_chroma_directory():
    """
    ⚠️ DANGER: Delete entire ChromaDB directory (nuclear option).
    Use this if collections are corrupted.
    """
    try:
        chroma_path = Path("./chroma")
        
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
            return {
                "success": True,
                "message": "ChromaDB directory deleted. Restart the API to reinitialize."
            }
        else:
            return {
                "success": True,
                "message": "ChromaDB directory doesn't exist"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ================== MAIN SCRAPE ENDPOINT (UPDATED) ==================

@router.post("/scrape", response_model=ScrapeResponse)
def scrape(request: URLRequest):
    """
    Scrape a website and extract business information.
    
    - **url**: The website URL to scrape
    - **force_refresh**: Clear cache and re-scrape (default: false)
    - **debug**: Include debug info in response (default: false)
    """
    site_url = request.url.strip()
    
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    debug_info = {} if request.debug else None

    try:
        print(f"\n{'='*50}")
        print(f"🔍 Starting scrape for: {site_url}")
        print(f"   Force refresh: {request.force_refresh}")
        print(f"   Debug mode: {request.debug}")
        print(f"{'='*50}\n")
        
        # Clear cache if force_refresh
        if request.force_refresh:
            try:
                if website_bot.chroma_client:
                    collection_name = website_bot.sanitize_collection_name(site_url)
                    website_bot.chroma_client.delete_collection(name=collection_name)
                    print(f"🔄 Cleared cache: {collection_name}")
            except Exception as e:
                print(f"⚠️ Cache clear warning: {e}")
        
        # Get URLs from sitemap or Firecrawl
        all_urls = website_bot.get_site_urls(site_url)
        main_pages = website_bot.select_main_pages(all_urls, site_url)
        
        print(f"📌 Selected pages to scrape: {main_pages}")
        
        if request.debug:
            debug_info["pages_found"] = len(all_urls)
            debug_info["pages_scraped"] = main_pages

        all_text = ""
        all_html = ""
        all_social = {"Facebook": "", "Instagram": "", "LinkedIn": "", "Twitter / X": ""}
        logo_url_found = None
        theme_colors = {}

        # Scrape each page
        for page in main_pages:
            try:
                print(f"\n📄 Processing: {page}")
                html = website_bot.fetch_page(page)
                
                if not html:
                    print(f"   ⚠️ No HTML content fetched")
                    continue
                
                all_html += " " + html

                # Extract logo (first page only)
                if not logo_url_found:
                    logo = website_bot.extract_logo_url(html, page)
                    if logo:
                        logo_url_found = logo
                        print(f"   🖼️ Logo found: {logo}")

                # Extract theme colors
                if not theme_colors.get("primary_color"):
                    theme_colors = website_bot.extract_theme_colors(html, page)
                    if theme_colors.get("primary_color"):
                        print(f"   🎨 Primary color: {theme_colors['primary_color']}")

                # Extract social links
                page_social = website_bot.extract_social_links_from_html(html)
                for k, v in page_social.items():
                    if v and not all_social[k]:
                        all_social[k] = v
                        print(f"   📱 {k}: {v}")

                # Extract text content
                soup = BeautifulSoup(html, "html.parser")
                [s.extract() for s in soup(["script", "style", "noscript"])]
                page_text = website_bot.clean_text(soup.get_text(" ", strip=True))
                all_text += " " + page_text
                
                print(f"   ✅ Extracted {len(page_text)} characters of text")
                
            except Exception as e:
                print(f"   ❌ Error processing page {page}: {e}")
                continue

        # Clean and chunk text
        all_text = website_bot.clean_text(all_text)
        chunks = website_bot.chunk_text(all_text)
        
        print(f"\n📊 Total text: {len(all_text)} chars, {len(chunks)} chunks")
        
        if request.debug:
            debug_info["total_text_length"] = len(all_text)
            debug_info["chunks_count"] = len(chunks)
            debug_info["text_preview"] = all_text[:1000]
            debug_info["pin_codes_found"] = re.findall(r'\b\d{6}\b', all_text)

        # Run RAG extraction
        print("\n🧠 Running RAG extraction...")
        data = website_bot.rag_extract(chunks, site_url)

        # Ensure data is a dict
        if not isinstance(data, dict):
            data = {}

        # Add logo
        data["Logo"] = logo_url_found or ""

        # Add theme colors
        data["Theme Colors"] = {
            "Primary": theme_colors.get("primary_color", ""),
            "Secondary": theme_colors.get("secondary_color", ""),
            "Accent": theme_colors.get("accent_color", ""),
            "Palette": theme_colors.get("color_palette", [])
        }

        # Extract and clean emails
        try:
            extracted_emails = website_bot.extract_all_emails(all_text, all_html)
            existing_emails = data.get("Email", [])
            if isinstance(existing_emails, str):
                existing_emails = [existing_emails] if existing_emails else []
            if not isinstance(existing_emails, list):
                existing_emails = []
            all_emails = existing_emails + extracted_emails
            data["Email"] = website_bot.clean_email_list(all_emails)
            
            if request.debug:
                debug_info["emails_extracted"] = extracted_emails
                debug_info["emails_final"] = data["Email"]
        except Exception as e:
            print(f"❌ Error extracting emails: {e}")
            data["Email"] = []

        # Extract and clean phones
        try:
            extracted_phones = website_bot.extract_all_phones(all_text)
            existing_phones = data.get("Phone", [])
            if isinstance(existing_phones, str):
                existing_phones = [existing_phones] if existing_phones else []
            if not isinstance(existing_phones, list):
                existing_phones = []
            all_phones = existing_phones + extracted_phones
            data["Phone"] = website_bot.clean_phone_list(all_phones)
            
            if request.debug:
                debug_info["phones_extracted"] = extracted_phones
        except Exception as e:
            print(f"❌ Error extracting phones: {e}")
            data["Phone"] = []

        # Extract and clean addresses with DEBUG
        try:
            print("\n🏠 Address extraction debug:")
            extracted_addresses = website_bot.extract_all_addresses(all_text)
            print(f"   Raw extracted: {extracted_addresses}")
            
            existing_addresses = data.get("Address", [])
            if isinstance(existing_addresses, str):
                existing_addresses = [existing_addresses] if existing_addresses else []
            if not isinstance(existing_addresses, list):
                existing_addresses = []
            
            print(f"   From RAG: {existing_addresses}")
            
            all_addresses = existing_addresses + extracted_addresses
            print(f"   Combined: {all_addresses}")
            
            data["Address"] = website_bot.clean_address_list(all_addresses)
            print(f"   After cleaning: {data['Address']}")
            
            if request.debug:
                debug_info["addresses_from_rag"] = existing_addresses
                debug_info["addresses_extracted"] = extracted_addresses
                debug_info["addresses_combined"] = all_addresses
                debug_info["addresses_final"] = data["Address"]
        except Exception as e:
            print(f"❌ Error extracting addresses: {e}")
            traceback.print_exc()
            data["Address"] = []

        # Add social links
        for k, v in all_social.items():
            if v:
                data[k] = v

        data["URL"] = site_url

        # Set defaults
        defaults = {
            "Business Name": "",
            "About Us": "",
            "Main Services": [],
            "Description": "",
            "Email": [],
            "Phone": [],
            "Address": [],
            "Facebook": "",
            "Instagram": "",
            "LinkedIn": "",
            "Twitter / X": "",
            "Logo": "",
            "Theme Colors": {"Primary": "", "Secondary": "", "Accent": "", "Palette": []},
            "URL": site_url
        }
        
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
            elif data[k] is None:
                data[k] = v
            elif k in ["Email", "Phone", "Address", "Main Services"]:
                if not isinstance(data[k], list):
                    data[k] = [data[k]] if data[k] else []

        print(f"\n{'='*50}")
        print("✅ Scraping completed successfully!")
        print(f"{'='*50}\n")
        
        response = {"success": True, "message": "Scraping Successful", "data": data}
        
        if request.debug:
            response["debug"] = debug_info
        
        return response

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error scraping site: {str(e)}")


# ================== OTHER ENDPOINTS (UNCHANGED) ==================

@router.post("/scrape/colors")
def scrape_colors_only(request: URLRequest):
    """Extract only theme colors from a website."""
    site_url = request.url.strip()
    
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        html = website_bot.fetch_page(site_url)
        
        if not html:
            raise HTTPException(status_code=404, detail="Could not fetch website content")
        
        theme_colors = website_bot.extract_theme_colors(html, site_url)
        
        return {
            "success": True,
            "message": "Colors extracted successfully",
            "data": {
                "URL": site_url,
                "Theme Colors": {
                    "Primary": theme_colors.get("primary_color", ""),
                    "Secondary": theme_colors.get("secondary_color", ""),
                    "Accent": theme_colors.get("accent_color", ""),
                    "Background": theme_colors.get("background_color", ""),
                    "Text": theme_colors.get("text_color", ""),
                    "Palette": theme_colors.get("color_palette", [])
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error extracting colors: {str(e)}")


@router.post("/scrape/social")
def scrape_social_only(request: URLRequest):
    """Extract only social media links from a website."""
    site_url = request.url.strip()
    
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        html = website_bot.fetch_page(site_url)
        
        if not html:
            raise HTTPException(status_code=404, detail="Could not fetch website content")
        
        social_links = website_bot.extract_social_links_from_html(html)
        
        return {
            "success": True,
            "message": "Social links extracted successfully",
            "data": {
                "URL": site_url,
                "Facebook": social_links.get("Facebook", ""),
                "Instagram": social_links.get("Instagram", ""),
                "LinkedIn": social_links.get("LinkedIn", ""),
                "Twitter / X": social_links.get("Twitter / X", "")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error extracting social links: {str(e)}")


@router.post("/scrape/contacts")
def scrape_contacts_only(request: URLRequest):
    """Extract only contact information from a website."""
    site_url = request.url.strip()
    
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        all_urls = website_bot.get_site_urls(site_url)
        pages_to_check = [site_url]
        
        for url in all_urls:
            if "contact" in url.lower():
                pages_to_check.append(url)
                break
        
        all_text = ""
        all_html = ""
        
        for page in pages_to_check[:2]:
            try:
                html = website_bot.fetch_page(page)
                if html:
                    all_html += " " + html
                    soup = BeautifulSoup(html, "html.parser")
                    [s.extract() for s in soup(["script", "style", "noscript"])]
                    all_text += " " + website_bot.clean_text(soup.get_text(" ", strip=True))
            except:
                continue
        
        emails = website_bot.extract_all_emails(all_text, all_html)
        phones = website_bot.extract_all_phones(all_text)
        addresses = website_bot.extract_all_addresses(all_text)
        
        return {
            "success": True,
            "message": "Contacts extracted successfully",
            "data": {
                "URL": site_url,
                "Email": emails,
                "Phone": phones,
                "Address": addresses
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error extracting contacts: {str(e)}")


@router.get("/health")
def health_check():
    """Check if the API is running and healthy."""
    chroma_status = "connected" if website_bot.chroma_client else "not initialized"
    
    return {
        "status": "healthy",
        "message": "API is running",
        "version": "2.1.0",
        "chroma_status": chroma_status,
        "features": [
            "Business info extraction",
            "Contact extraction (email, phone, address)",
            "Social media link extraction",
            "Theme color extraction",
            "Logo extraction",
            "Debug endpoints",
            "Cache management"
        ]
    }


@router.get("/")
def api_root():
    """API root endpoint with all available endpoints."""
    return {
        "name": "Website Info Extractor API",
        "version": "2.1.0",
        "endpoints": {
            "scraping": {
                "POST /api/scrape": "Full website scrape (supports force_refresh, debug)",
                "POST /api/scrape/colors": "Extract theme colors only",
                "POST /api/scrape/social": "Extract social links only",
                "POST /api/scrape/contacts": "Extract contacts only"
            },
            "debugging": {
                "POST /api/debug/address": "Debug address extraction",
                "POST /api/debug/raw-html": "Get raw HTML from URL",
                "POST /api/debug/test-patterns": "Test regex patterns"
            },
            "cache": {
                "GET /api/cache/list": "List all cached collections",
                "POST /api/cache/clear": "Clear cache for specific URL",
                "POST /api/cache/clear-all": "Clear all cache",
                "DELETE /api/cache/reset-directory": "Delete ChromaDB directory"
            },
            "health": {
                "GET /api/health": "Health check"
            }
        },
        "docs": "/docs"
    }


# Include router in app
app.include_router(router)


@app.get("/")
def app_root():
    """Redirect to API documentation."""
    return {
        "message": "Welcome to Website Info Extractor API",
        "docs": "/docs",
        "api": "/api"
    }


if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print("🚀 Starting Website Info Extractor API v2.1.0")
    print("="*60)
    print("\n📍 API Documentation: http://localhost:8000/docs")
    print("📍 Health Check: http://localhost:8000/api/health")
    print("\n🔧 Debug Endpoints:")
    print("   POST /api/debug/address - Debug address extraction")
    print("   POST /api/debug/raw-html - Get raw HTML")
    print("   POST /api/debug/test-patterns - Test regex patterns")
    print("\n🗑️ Cache Management:")
    print("   GET  /api/cache/list - List cached collections")
    print("   POST /api/cache/clear-all - Clear all cache")
    print("\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)