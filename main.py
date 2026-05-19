import os
import datetime
from dotenv import load_dotenv
load_dotenv()
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from utils.supabase import init_supabase, get_service_client
from routes.sessions import router as sessions_router
from routes.admin import router as admin_router
from routes.topics import router as topics_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Supabase Clients at startup
    await init_supabase()
    yield

app = FastAPI(title="Recovery Platform Web App", lifespan=lifespan)

# Mount static files (served from python_app/static)
# Resolve path dynamically to avoid issues
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
templates_dir = os.path.join(current_dir, "templates")

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "ts": datetime.datetime.utcnow().isoformat() + "Z"
    }

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request, start: str = Query(None)):
    if not start or not start.startswith("session_"):
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": "Invalid link. Please open this app from the Telegram Bot."
        })
        
    session_id = start.replace("session_", "")
    
    try:
        supabase = get_service_client()
        # Fetch session and host info
        res = await supabase.from_("video_sessions").select("*, host:host_id(anonymous_id)").eq("id", session_id).execute()
        if not res.data:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "error": "Session not found."
            })
            
        session = res.data[0]
        host = session.get("host")
        host_name = host.get("anonymous_id") if host else "Anonymous Mentor"
        
        # Format date for display
        scheduled_str = session.get("scheduled_at")
        try:
            dt = datetime.datetime.fromisoformat(scheduled_str.replace("Z", "+00:00"))
            formatted_date = dt.strftime("%B %d, %Y at %I:%M %p UTC")
        except Exception:
            formatted_date = scheduled_str
            
        return templates.TemplateResponse("index.html", {
            "request": request,
            "session_id": session_id,
            "session_title": session.get("title", "Recovery Session"),
            "session_status": session.get("status", "scheduled"),
            "host_name": host_name,
            "scheduled_at": formatted_date,
            "error": None
        })
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": f"Error loading session: {str(e)}"
        })

# Include API routes
app.include_router(sessions_router)
app.include_router(admin_router)
app.include_router(topics_router)
