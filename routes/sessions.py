import os
import datetime
from fastapi import APIRouter, Depends, HTTPException
import jwt

from utils.supabase import get_service_client
from utils.auth import get_current_user

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

def generate_jitsi_jwt(room_name: str, user_info: dict, jitsi_jwt_secret: str, jitsi_app_id: str = "recovery-app"):
    if not jitsi_jwt_secret:
        return None
    
    payload = {
        "context": {"user": user_info},
        "aud": "jitsi",
        "iss": jitsi_app_id,
        "sub": "meet.jit.si",
        "room": room_name,
        "exp": int((datetime.datetime.utcnow() + datetime.timedelta(hours=4)).timestamp())
    }
    return jwt.encode(payload, jitsi_jwt_secret, algorithm="HS256")

@router.get("/{session_id}/join")
async def join_session(session_id: str, user: dict = Depends(get_current_user)):
    telegram_id = user.get("id")
    supabase = get_service_client()
    
    # Fetch session details
    sess_res = await supabase.from_("video_sessions").select("*").eq("id", session_id).execute()
    if not sess_res.data:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = sess_res.data[0]
    is_group = session.get("is_group", False)
    host_id = session.get("host_id")
    room_name = session.get("room_name")
    room_password = session.get("room_password")
    
    if not is_group:
        # Check participant
        part_res = await supabase.from_("session_participants").select("telegram_id").eq("session_id", session_id).eq("telegram_id", telegram_id).execute()
        if not part_res.data:
            raise HTTPException(status_code=403, detail="Not a participant")
    else:
        # Join group session - add participant
        await supabase.from_("session_participants").upsert(
            {"session_id": session_id, "telegram_id": telegram_id},
            on_conflict="session_id,telegram_id"
        ).execute()
        
    # Mark joined
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    await supabase.from_("session_participants").update({"joined_at": now_iso}).eq("session_id", session_id).eq("telegram_id", telegram_id).execute()
    
    # Activate session if scheduled
    if session.get("status") == "scheduled":
        await supabase.from_("video_sessions").update({"status": "active", "started_at": now_iso}).eq("id", session_id).execute()
        
    # Get user anonymous_id
    user_res = await supabase.from_("users").select("anonymous_id").eq("telegram_id", telegram_id).execute()
    display_name = user_res.data[0].get("anonymous_id", "Anonymous") if user_res.data else "Anonymous"
    
    is_moderator = host_id == telegram_id
    
    jitsi_jwt_secret = os.getenv("JITSI_JWT_SECRET")
    jitsi_app_id = os.getenv("JITSI_APP_ID", "recovery-app")
    
    jitsi_token = generate_jitsi_jwt(
        room_name=room_name,
        user_info={"displayName": display_name, "moderator": is_moderator},
        jitsi_jwt_secret=jitsi_jwt_secret,
        jitsi_app_id=jitsi_app_id
    )
    
    return {
        "room_name": room_name,
        "room_password": room_password,
        "jitsi_token": jitsi_token,
        "display_name": display_name,
        "is_moderator": is_moderator
    }
