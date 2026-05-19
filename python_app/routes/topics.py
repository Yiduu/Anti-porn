from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils.supabase import get_service_client
from utils.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/topics", tags=["topics"])

class CreateTopicPayload(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None

class UpdateTopicPayload(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

# GET /api/topics - list active topics
@router.get("/")
async def list_active_topics():
    supabase = get_service_client()
    res = await supabase.from_("topics").select("*").eq("is_active", True).order("name", desc=False).execute()
    return res.data or []

# GET /api/topics/admin - list all topics
@router.get("/admin")
async def list_all_topics(admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    res = await supabase.from_("topics").select("*").order("name", desc=False).execute()
    return res.data or []

# POST /api/topics - create a new topic
@router.post("/")
async def create_topic(payload: CreateTopicPayload, admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    res = await supabase.from_("topics").insert({
        "name": payload.name,
        "slug": payload.slug,
        "description": payload.description
    }).execute()
    
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create topic")
    return res.data[0]

# PUT /api/topics/{topic_id} - update topic
@router.put("/{topic_id}")
async def update_topic(topic_id: int, payload: UpdateTopicPayload, admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    update_data = {}
    if payload.name is not None:
        update_data["name"] = payload.name
    if payload.slug is not None:
        update_data["slug"] = payload.slug
    if payload.description is not None:
        update_data["description"] = payload.description
    if payload.is_active is not None:
        update_data["is_active"] = payload.is_active
        
    res = await supabase.from_("topics").update(update_data).eq("id", topic_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Topic not found")
    return res.data[0]

# DELETE /api/topics/{topic_id} - soft delete
@router.delete("/{topic_id}")
async def delete_topic(topic_id: int, admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    res = await supabase.from_("topics").update({"is_active": False}).eq("id", topic_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"success": True}

# GET /api/topics/stats - topic popularity stats
@router.get("/stats")
async def get_topic_stats(admin: dict = Depends(require_admin)):
    supabase = get_service_client()
    res = await supabase.from_("mentorship_assignments").select("topic_id, topics(name)").execute()
    data = res.data or []
    
    stats = {}
    for item in data:
        topic_info = item.get("topics")
        name = topic_info.get("name") if topic_info else "Unknown"
        stats[name] = stats.get(name, 0) + 1
        
    return stats
