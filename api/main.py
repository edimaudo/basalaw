from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from .utils import extract_text_from_file
from .agents import ask_esa_lawyer
import shutil
import os
import uvicorn
import httpx
import time
import logging

logger = logging.getLogger(__name__)

PENDO_TRACK_URL = "https://data.pendo.io/data/track"
PENDO_INTEGRATION_KEY = os.getenv("PENDO_INTEGRATION_KEY", "")
PENDO_API_KEY = os.getenv("PENDO_API_KEY", "")

if not PENDO_INTEGRATION_KEY:
    logger.warning("PENDO_INTEGRATION_KEY is not set — server-side tracking will not work")
if not PENDO_API_KEY:
    logger.warning("PENDO_API_KEY is not set — client-side Pendo agent will not load")


async def pendo_track_server(event: str, visitor_id: str = "system", account_id: str = "system", properties: dict = None):
    """Send a server-side Pendo track event."""
    try:
        payload = {
            "type": "track",
            "event": event,
            "visitorId": visitor_id,
            "accountId": account_id,
            "timestamp": int(time.time() * 1000),
            "properties": properties or {}
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                PENDO_TRACK_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-pendo-integration-key": PENDO_INTEGRATION_KEY
                },
                timeout=5.0
            )
    except Exception as e:
        logger.warning(f"Pendo track event failed: {e}")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
#app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "pendo_api_key": PENDO_API_KEY})

@app.exception_handler(404)
async def custom_404_handler(request: Request, __):
    return templates.TemplateResponse("404.html", {"request": request, "pendo_api_key": PENDO_API_KEY}, status_code=404)

@app.get("/api/audit", response_class=HTMLResponse)
async def get_qa_page(request: Request):
    """Reasoning: This renders the UI when the user clicks the link."""
    return templates.TemplateResponse("audit.html", {"request": request, "pendo_api_key": PENDO_API_KEY})

@app.post("/api/audit")
async def handle_audit(file: UploadFile = File(None), clause_text: str = Form(None)):
    context = ""
    
    # 1. Extraction with Scanned PDF Detection
    if file and file.filename:
        file_bytes = await file.read()
        context = extract_text_from_file(file_bytes, file.filename)
        if context == "ERROR_IMAGE_ONLY_PDF":
            # Pendo Track: scanned_document_detected
            await pendo_track_server(
                event="scanned_document_detected",
                properties={
                    "fileName": file.filename[:100] if file.filename else "unknown",
                    "fileSize": len(file_bytes)
                }
            )
            return {
                "answer": (
                    "SCANNED DOCUMENT DETECTED\n\n"
                    "This PDF appears to be a scan or an image. Our system cannot read 'flat' text from images. "
                    "To review this, please upload a digital PDF, docx, or doc file (where you can highlight text) or "
                    "manually paste the clauses into the 'Specific Clause' tab."
                )
            }
    elif clause_text:
        context = clause_text

    if not context or "Unsupported" in context:
        return {"answer": "Error: No readable text was provided for analysis."}

    audit_prompt = (
        "1. Identify any illegal or unenforceable clauses. if none exist skip 2, 3 and 4\n"
        "2. Suggest specific corrections.\n"
        "3. If there is an illegal or unenforceable clause(s) PROVDE A DRAFT collaborative EMAIL to HR.\n[Provide a collaborative email draft here]\n\n"
        "4. If there is an illegal or unenforceable clause(s) provide a DRAFT SUMMARY FOR LAWYER\n[Provide a formal legal summary here]\n\n"
        f"CONTRACT CONTENT:\n{context}"
    )
    
    analysis = await ask_esa_lawyer(audit_prompt)
    return {"answer": analysis}


@app.get("/api/qa", response_class=HTMLResponse)
async def get_qa_page(request: Request):
    return templates.TemplateResponse("qa.html", {"request": request, "pendo_api_key": PENDO_API_KEY})

@app.post("/api/qa")
async def handle_qa_logic(question: str = Form(...)):
    answer = await ask_esa_lawyer(question)
    return {"answer": answer}
    return response

@app.get("/api/lawyers", response_class=HTMLResponse)
async def get_lawyers_page(request: Request):
    # Serves the list of LSO Certified Specialists. 
    specialists = [
        {"name": "S. Margot Blight", "firm": "S. Margot Blight, Lawyer", "city": "Mississauga"},
        {"name": "David Bannon", "firm": "Hicks Morley Hamilton Stewart Storie LLP", "city": "Toronto"},
        {"name": "Matthew Louis Certosimo", "firm": "Borden Ladner Gervais LLP", "city": "Toronto"},
        {"name": "Patrick Michael Rory Groom", "firm": "McMillan LLP", "city": "Toronto"},
        {"name": "John Hyde", "firm": "Hyde HR Law", "city": "Toronto"},
        {"name": "Donald B. Jarvis", "firm": "Filion Wakely Thorup Angeletti LLP", "city": "Toronto"},
        {"name": "Jeffrey David Arthur Murray", "firm": "Stringer LLP", "city": "Toronto"},
        {"name": "Garth O'Neill", "firm": "GOLaw Professional Corporation", "city": "Thunder Bay"},
        {"name": "Donald Shanks", "firm": "Cheadles LLP", "city": "Thunder Bay"},
        {"name": "Ronald Snyder", "firm": "Xphoria Spirits Inc.", "city": "Ottawa"}
    ]
    
    return templates.TemplateResponse("lawyers.html", {
        "request": request,
        "specialists": specialists,
        "pendo_api_key": PENDO_API_KEY
    })

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
