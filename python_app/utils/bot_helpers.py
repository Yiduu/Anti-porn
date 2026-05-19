import os
import httpx
from utils.i18n import t_sync

async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("[Bot helper] Error: TELEGRAM_BOT_TOKEN not set")
        return False
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code != 200:
                print(f"[Bot helper] Telegram API error status {resp.status_code}: {resp.text}")
            return resp.status_code == 200
    except Exception as e:
        print(f"[Bot helper] Failed to send message to {chat_id}: {e}")
        return False

async def get_user_lang(chat_id: int, supabase) -> str:
    try:
        res = await supabase.from_("user_settings").select("language").eq("telegram_id", chat_id).execute()
        if res.data:
            return res.data[0].get("language", "en")
    except Exception as e:
        print(f"[Bot helper] Error fetching user lang for {chat_id}: {e}")
    return "en"

async def get_mentor_topic_keyboard(chat_id: int, supabase, lang: str = "en") -> dict:
    try:
        topics_res = await supabase.from_("topics").select("id, name").eq("is_active", True).order("name").execute()
        mentor_topics_res = await supabase.from_("mentor_topics").select("topic_id").eq("telegram_id", chat_id).execute()
        
        topics = topics_res.data or []
        mentor_topics = mentor_topics_res.data or []
        selected_ids = [mt["topic_id"] for mt in mentor_topics]
        
        buttons = []
        for t in topics:
            is_selected = t["id"] in selected_ids
            mark = "✅" if is_selected else "⬜"
            buttons.append([{
                "text": f"{mark} {t['name']}",
                "callback_data": f"toggle_topic_{t['id']}"
            }])
            
        buttons.append([
            {"text": t_sync(lang, "btn_done"), "callback_data": "topic_done"},
            {"text": t_sync(lang, "btn_cancel"), "callback_data": "topic_cancel"}
        ])
        return {"inline_keyboard": buttons}
    except Exception as e:
        print(f"[Bot helper] Error generating keyboard: {e}")
        return {"inline_keyboard": []}

async def notify_mentor_approved(chat_id: int, supabase) -> bool:
    lang = await get_user_lang(chat_id, supabase)
    text = t_sync(lang, "mentor_approved")
    
    # Check if they have expertise topics
    mt_res = await supabase.from_("mentor_topics").select("topic_id").eq("telegram_id", chat_id).execute()
    if not mt_res.data:
        kb = await get_mentor_topic_keyboard(chat_id, supabase, lang)
        text_prompt = t_sync(lang, "set_expertise_prompt")
        await send_telegram_message(chat_id, text)
        return await send_telegram_message(chat_id, text_prompt, reply_markup=kb)
    else:
        # Default menu trigger message
        await send_telegram_message(chat_id, text)
        return True

async def notify_mentor_rejected(chat_id: int, supabase) -> bool:
    lang = await get_user_lang(chat_id, supabase)
    app_res = await supabase.from_("mentor_applications").select("admin_note").eq("telegram_id", chat_id).order("reviewed_at", desc=True).limit(1).execute()
    
    msg = t_sync(lang, "mentor_application_rejected")
    if app_res.data and app_res.data[0].get("admin_note"):
        note = app_res.data[0]["admin_note"]
        label = t_sync(lang, "admin_note")
        msg += f"\n\n*{label}:* {note}"
        
    return await send_telegram_message(chat_id, msg)

async def broadcast_to_all(message: str, role_filter: str, supabase) -> int:
    query = supabase.from_("users").select("telegram_id, user_settings(language)").eq("is_banned", False)
    if role_filter:
        query = query.eq("role", role_filter)
        
    res = await query.execute()
    users = res.data or []
    
    count = 0
    for u in users:
        chat_id = u.get("telegram_id")
        settings = u.get("user_settings") or {}
        lang = settings.get("language", "en")
        
        broadcast_label = t_sync(lang, "broadcast")
        text = f"📢 *{broadcast_label}*\n\n{message}"
        
        ok = await send_telegram_message(chat_id, text)
        if ok:
            count += 1
            
    return count
