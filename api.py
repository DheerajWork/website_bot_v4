from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from concurrent.futures import ThreadPoolExecutor
import uuid
from website_bot import scrape_website

app = FastAPI(title="Website Data Scraper API")

# ThreadPoolExecutor for background scraping
executor = ThreadPoolExecutor(max_workers=2)

# In-memory store for results (demo; in production, use DB or Redis)
scrape_results = {}

@app.get("/")
async def home():
    return {"message": "✅ Website Scraper API is running successfully."}

def run_scrape(task_id: str, url: str):
    try:
        result = scrape_website(url)  # Heavy scraping runs here
        scrape_results[task_id] = {"status": "success", "data": result}
    except Exception as e:
        scrape_results[task_id] = {"status": "error", "message": str(e)}

@app.post("/scrape")
async def scrape(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        url = body.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="Missing 'url' field in request body")

        task_id = str(uuid.uuid4())
        # Add scraping task to background
        background_tasks.add_task(run_scrape, task_id, url)

        return {
            "status": "processing",
            "message": "Scraping started in background",
            "task_id": task_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/result/{task_id}")
async def get_result(task_id: str):
    result = scrape_results.get(task_id)
    if not result:
        return {"status": "pending", "message": "Result not ready yet"}
    return result
