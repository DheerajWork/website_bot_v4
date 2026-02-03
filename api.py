#!/usr/bin/env python3
"""
FastAPI Web Scraper API
Extracts business information, social links, and theme colors from websites.
"""

from fastapi import FastAPI, HTTPException, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any
import traceback
import json

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
    version="2.0.0"
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


# ---------------- API Endpoints ----------------
@router.post("/scrape", response_model=ScrapeResponse)
def scrape(request: URLRequest):
    """
    Scrape a website and extract business information.
    
    - **url**: The website URL to scrape (e.g., "https://example.com")
    
    Returns:
    - Business name, description, services
    - Contact information (email, phone, address)
    - Social media links
    - Theme colors (primary, secondary, accent, palette)
    - Logo URL
    """
    site_url = request.url.strip()
    
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        print(f"\n{'='*50}")
        print(f"🔍 Starting scrape for: {site_url}")
        print(f"{'='*50}\n")
        
        # Get URLs from sitemap or Firecrawl
        all_urls = website_bot.get_site_urls(site_url)
        main_pages = website_bot.select_main_pages(all_urls, site_url)
        
        print(f"📌 Selected pages to scrape: {main_pages}")

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

                # Extract theme colors (first page - homepage usually has brand colors)
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

        # Extract and clean emails with deduplication
        try:
            extracted_emails = website_bot.extract_all_emails(all_text, all_html)
            existing_emails = data.get("Email", [])
            if isinstance(existing_emails, str):
                existing_emails = [existing_emails] if existing_emails else []
            if not isinstance(existing_emails, list):
                existing_emails = []
            all_emails = existing_emails + extracted_emails
            data["Email"] = website_bot.clean_email_list(all_emails)
        except Exception as e:
            print(f"❌ Error extracting emails: {e}")
            data["Email"] = []

        # Extract and clean phones with deduplication
        try:
            extracted_phones = website_bot.extract_all_phones(all_text)
            existing_phones = data.get("Phone", [])
            if isinstance(existing_phones, str):
                existing_phones = [existing_phones] if existing_phones else []
            if not isinstance(existing_phones, list):
                existing_phones = []
            all_phones = existing_phones + extracted_phones
            data["Phone"] = website_bot.clean_phone_list(all_phones)
        except Exception as e:
            print(f"❌ Error extracting phones: {e}")
            data["Phone"] = []

        # Extract and clean addresses with deduplication
        try:
            extracted_addresses = website_bot.extract_all_addresses(all_text)
            existing_addresses = data.get("Address", [])
            if isinstance(existing_addresses, str):
                existing_addresses = [existing_addresses] if existing_addresses else []
            if not isinstance(existing_addresses, list):
                existing_addresses = []
            all_addresses = existing_addresses + extracted_addresses
            data["Address"] = website_bot.clean_address_list(all_addresses)
        except Exception as e:
            print(f"❌ Error extracting addresses: {e}")
            data["Address"] = []

        # Add social links
        for k, v in all_social.items():
            if v:
                data[k] = v

        data["URL"] = site_url

        # Set defaults with proper empty values
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
            "Theme Colors": {
                "Primary": "",
                "Secondary": "",
                "Accent": "",
                "Palette": []
            },
            "URL": site_url
        }
        
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
            elif data[k] is None:
                data[k] = v
            elif k in ["Email", "Phone", "Address", "Main Services"]:
                # Ensure these are always lists
                if not isinstance(data[k], list):
                    data[k] = [data[k]] if data[k] else []

        print(f"\n{'='*50}")
        print("✅ Scraping completed successfully!")
        print(f"{'='*50}\n")
        
        return {"success": True, "message": "Scraping Successful", "data": data}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error scraping site: {str(e)}")


@router.post("/scrape/colors")
def scrape_colors_only(request: URLRequest):
    """
    Extract only theme colors from a website.
    Faster than full scrape when you only need colors.
    """
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
    """
    Extract only social media links from a website.
    Faster than full scrape when you only need social links.
    """
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
    """
    Extract only contact information from a website.
    Returns email, phone, and address.
    """
    site_url = request.url.strip()
    
    if not site_url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")
    
    if not site_url.startswith("http"):
        site_url = "https://" + site_url

    try:
        # Get contact page if exists
        all_urls = website_bot.get_site_urls(site_url)
        pages_to_check = [site_url]
        
        for url in all_urls:
            if "contact" in url.lower():
                pages_to_check.append(url)
                break
        
        all_text = ""
        all_html = ""
        
        for page in pages_to_check[:2]:  # Limit to 2 pages
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
    return {
        "status": "healthy",
        "message": "API is running",
        "version": "2.0.0",
        "features": [
            "Business info extraction",
            "Contact extraction (email, phone, address)",
            "Social media link extraction",
            "Theme color extraction",
            "Logo extraction"
        ]
    }


@router.get("/")
def root():
    """API root endpoint with basic info."""
    return {
        "name": "Website Info Extractor API",
        "version": "2.0.0",
        "endpoints": {
            "/api/scrape": "POST - Full website scrape",
            "/api/scrape/colors": "POST - Extract theme colors only",
            "/api/scrape/social": "POST - Extract social links only",
            "/api/scrape/contacts": "POST - Extract contacts only",
            "/api/health": "GET - Health check"
        },
        "docs": "/docs"
    }


# Include router in app
app.include_router(router)


# Root redirect to docs
@app.get("/")
def app_root():
    """Redirect to API documentation."""
    return {
        "message": "Welcome to Website Info Extractor API",
        "docs": "/docs",
        "api": "/api"
    }


# Run with: uvicorn api:app --reload --host 0.0.0.0 --port 8000
if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("🚀 Starting Website Info Extractor API")
    print("="*50)
    print("\n📍 API Documentation: http://localhost:8000/docs")
    print("📍 Health Check: http://localhost:8000/api/health")
    print("\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)