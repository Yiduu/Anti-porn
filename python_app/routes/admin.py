import datetime
import io
import csv
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from utils.supabase import get_service_client
from utils.auth import require_admin
from utils.bot_helpers import notify_mentor_approved, notify_mentor_rejected, broadcast_to_all

router = APIRouter(prefix="/api/admin", tags=["admin"])

async def log_audit(admin_id: int, action: str, target_id: Optional[int], target_type: Optional[str], details: Optional[dict] = None):
    supabase = get_service_client()
    await supabase.from_("audit_logs").insert({
        "admin_id": str(admin_id),
        "action": action,
        "target_id": str(target_id) if target_id is not None else None,
        "target_type": target_type,
        "details": details or {}
    }).execute()

# Input Validation Models
class UpdateRolePayload(BaseModel):
    role: str

class UpdateBanPayload(BaseModel):
    banned: bool

class ReviewApplicationPayload(BaseModel):
    action: str  # "approved" or "rejected"
    admin_note: Optional[str] = ""

class ReplyTicketPayload(BaseModel):
    admin_reply: str
    status: Optional[str] = "resolved"

class BroadcastPayload(BaseModel):
    message: str
    role_filter: Optional[str] = None

# Routes
@router.get("/stats")
async def get_stats(admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    today_iso = datetime.datetime.utcnow().date().isoformat() + "T00:00:00.000Z"
    
    # Run counts using Head select count
    total = await supabase.from_("users").select("telegram_id", count="exact").execute()
    new_today = await supabase.from_("users").select("telegram_id", count="exact").gte("created_at", today_iso).execute()
    mentors = await supabase.from_("users").select("telegram_id", count="exact").eq("role", "mentor").execute()
    pending = await supabase.from_("mentor_applications").select("id", count="exact").eq("status", "pending").execute()
    flagged = await supabase.from_("messages").select("id", count="exact").eq("is_flagged", True).execute()
    open_t = await supabase.from_("support_tickets").select("id", count="exact").eq("status", "open").execute()
    
    return {
        "total_users": total.count or 0,
        "new_today": new_today.count or 0,
        "active_mentors": mentors.count or 0,
        "pending_applications": pending.count or 0,
        "flagged_messages": flagged.count or 0,
        "open_tickets": open_t.count or 0
    }

@router.get("/users")
async def get_users(
    page: int = Query(1, ge=1),
    search: Optional[str] = None,
    role: Optional[str] = None,
    admin: dict = Depends(require_admin)
):
    supabase = get_service_client()
    limit = 25
    offset = (page - 1) * limit
    
    query = supabase.from_("users").select("*, user_settings(display_name, bio)", count="exact")
    if search:
        query = query.ilike("anonymous_id", f"%{search}%")
    if role:
        query = query.eq("role", role)
        
    res = await query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    total = res.count or 0
    pages = (total + limit - 1) // limit
    
    return {
        "users": res.data or [],
        "total": total,
        "page": page,
        "pages": pages
    }

@router.patch("/users/{telegram_id}/role")
async def update_user_role(
    telegram_id: int,
    payload: UpdateRolePayload,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    role = payload.role
    if role not in ["user", "mentor"]:
        raise HTTPException(status_code=400, detail="Invalid role")
        
    supabase = get_service_client()
    await supabase.from_("users").update({"role": role}).eq("telegram_id", telegram_id).execute()
    
    if role == "mentor":
        await supabase.from_("mentors").upsert({"telegram_id": telegram_id}, on_conflict="telegram_id").execute()
        # Ensure user settings exists
        await supabase.from_("user_settings").upsert({"telegram_id": telegram_id}, on_conflict="telegram_id").execute()
        
    await log_audit(admin_id, "change_role", telegram_id, "user", {"new_role": role})
    return {"success": True}

@router.patch("/users/{telegram_id}/ban")
async def update_user_ban(
    telegram_id: int,
    payload: UpdateBanPayload,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    banned = payload.banned
    
    supabase = get_service_client()
    await supabase.from_("users").update({"is_banned": banned}).eq("telegram_id", telegram_id).execute()
    
    action = "ban_user" if banned else "unban_user"
    await log_audit(admin_id, action, telegram_id, "user")
    return {"success": True}

@router.delete("/users/{telegram_id}/delete")
async def delete_user(
    telegram_id: int,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    supabase = get_service_client()
    
    # Get user details first
    u_res = await supabase.from_("users").select("anonymous_id").eq("telegram_id", telegram_id).execute()
    if not u_res.data:
        raise HTTPException(status_code=404, detail="User not found")
    anon_id = u_res.data[0]["anonymous_id"]
    
    await supabase.from_("users").delete().eq("telegram_id", telegram_id).execute()
    await log_audit(admin_id, "delete_user", telegram_id, "user", {"anonymous_id": anon_id})
    return {"success": True}

@router.get("/applications")
async def get_applications(
    page: int = Query(1, ge=1),
    status: str = "pending",
    admin: dict = Depends(require_admin)
):
    supabase = get_service_client()
    limit = 20
    offset = (page - 1) * limit
    
    res = await supabase.from_("mentor_applications").select(
        "*, user:users(anonymous_id, sex, age_range, created_at)",
        count="exact"
    ).eq("status", status).order("submitted_at", desc=True).range(offset, offset + limit - 1).execute()
    
    total = res.count or 0
    pages = (total + limit - 1) // limit
    
    return {
        "applications": res.data or [],
        "total": total,
        "page": page,
        "pages": pages
    }

@router.patch("/applications/{app_id}")
async def review_application(
    app_id: str,
    payload: ReviewApplicationPayload,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    action = payload.action
    admin_note = payload.admin_note
    
    if action not in ["approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid action")
        
    supabase = get_service_client()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    
    app_res = await supabase.from_("mentor_applications").update({
        "status": action,
        "admin_note": admin_note,
        "reviewed_at": now_iso
    }).eq("id", app_id).execute()
    
    if not app_res.data:
        raise HTTPException(status_code=404, detail="Application not found")
        
    app_data = app_res.data[0]
    target_telegram_id = app_data["telegram_id"]
    
    if action == "approved":
        await supabase.from_("users").update({"role": "mentor"}).eq("telegram_id", target_telegram_id).execute()
        await supabase.from_("mentors").upsert({"telegram_id": target_telegram_id}, on_conflict="telegram_id").execute()
        await notify_mentor_approved(target_telegram_id, supabase)
    elif action == "rejected":
        await notify_mentor_rejected(target_telegram_id, supabase)
        
    await log_audit(admin_id, f"application_{action}", target_telegram_id, "mentor_application", {"app_id": app_id})
    return {"success": True, "application": app_data}

@router.get("/messages")
async def get_messages(
    page: int = Query(1, ge=1),
    flagged: str = "false",
    admin: dict = Depends(require_admin)
):
    supabase = get_service_client()
    limit = 50
    offset = (page - 1) * limit
    
    query = supabase.from_("messages").select("*", count="exact")
    if flagged == "true":
        query = query.eq("is_flagged", True)
        
    res = await query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    total = res.count or 0
    pages = (total + limit - 1) // limit
    
    return {
        "messages": res.data or [],
        "total": total,
        "page": page,
        "pages": pages
    }

@router.get("/tickets")
async def get_tickets(admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    res = await supabase.from_("support_tickets").select(
        "*, user:telegram_id(anonymous_id)"
    ).in_("status", ["open", "in_progress"]).order("created_at", desc=True).execute()
    return res.data or []

@router.patch("/tickets/{ticket_id}")
async def reply_ticket(
    ticket_id: str,
    payload: ReplyTicketPayload,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    admin_reply = payload.admin_reply
    status = payload.status
    
    supabase = get_service_client()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    
    res = await supabase.from_("support_tickets").update({
        "admin_reply": admin_reply,
        "status": status,
        "updated_at": now_iso
    }).eq("id", ticket_id).execute()
    
    if not res.data:
        raise HTTPException(status_code=404, detail="Ticket not found")
        
    await log_audit(admin_id, "ticket_reply", None, "support_ticket", {"ticket_id": ticket_id})
    return res.data[0]

@router.post("/broadcast")
async def send_broadcast(
    payload: BroadcastPayload,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    message = payload.message
    role_filter = payload.role_filter
    
    supabase = get_service_client()
    sent_count = await broadcast_to_all(message, role_filter, supabase)
    
    await log_audit(admin_id, "broadcast", None, "all", {
        "message": message[:100],
        "role_filter": role_filter
    })
    return {"sent_to": sent_count}

@router.get("/audit-logs")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    admin: dict = Depends(require_admin)
):
    supabase = get_service_client()
    limit = 50
    offset = (page - 1) * limit
    
    res = await supabase.from_("audit_logs").select("*", count="exact").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    total = res.count or 0
    
    return {
        "logs": res.data or [],
        "total": total,
        "page": page
    }

@router.get("/export/{table}")
async def export_table(
    table: str,
    admin: dict = Depends(require_admin)
):
    allowed = ["users", "messages", "video_sessions", "mentor_applications", "support_tickets"]
    if table not in allowed:
        raise HTTPException(status_code=400, detail="Table not exportable")
        
    supabase = get_service_client()
    res = await supabase.from_(table).select("*").limit(10000).execute()
    data = res.data or []
    
    output = io.StringIO()
    writer = csv.writer(output)
    if data:
        # Write headers
        writer.writerow(data[0].keys())
        # Write rows
        for row in data:
            writer.writerow(row.values())
            
    csv_content = output.getvalue()
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}-export.csv"'}
    )

@router.patch("/mentors/{telegram_id}/disqualify")
async def disqualify_mentor(
    telegram_id: int,
    admin: dict = Depends(require_admin)
):
    admin_id = admin.get("id")
    supabase = get_service_client()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    
    await supabase.from_("users").update({"role": "user"}).eq("telegram_id", telegram_id).execute()
    await supabase.from_("mentors").update({"is_active": False}).eq("telegram_id", telegram_id).execute()
    await supabase.from_("mentorship_assignments").update({
        "is_active": False,
        "ended_at": now_iso
    }).eq("mentor_id", telegram_id).eq("is_active", True).execute()
    
    await log_audit(admin_id, "disqualify_mentor", telegram_id, "mentor")
    return {"success": True}
