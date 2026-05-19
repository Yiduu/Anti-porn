import os
import time
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from fastapi import Request, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader

X_TELEGRAM_INIT_DATA = APIKeyHeader(name="x-telegram-init-data", auto_error=False)
X_TELEGRAM_ID = APIKeyHeader(name="x-telegram-id", auto_error=False)

def validate_telegram_data(init_data: str, bot_token: str) -> dict | None:
    try:
        params = dict(parse_qsl(init_data))
        if "hash" not in params:
            return None
        
        received_hash = params.pop("hash")
        
        sorted_params = sorted(params.items())
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
        
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if computed_hash != received_hash:
            return None
            
        auth_date = int(params.get("auth_date", 0))
        if time.time() - auth_date > 3600:
            return None
            
        user_json = params.get("user")
        if user_json:
            return json.loads(user_json)
        return None
    except Exception:
        return None

async def get_current_user(
    x_telegram_init_data: str = Security(X_TELEGRAM_INIT_DATA),
    x_telegram_id: str = Security(X_TELEGRAM_ID)
) -> dict:
    node_env = os.getenv("NODE_ENV", "production")
    if node_env == "development" and x_telegram_id:
        return {"id": int(x_telegram_id)}
        
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Missing initData")
        
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Bot token not configured")
        
    user = validate_telegram_data(x_telegram_init_data, bot_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid initData")
        
    return user

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")
    if not admin_id:
        raise HTTPException(status_code=500, detail="Admin ID not configured")
        
    if str(user.get("id")) != str(admin_id):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    return user
