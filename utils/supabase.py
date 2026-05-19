import os
from typing import Optional
from supabase._async.client import AsyncClient, create_client

_anon_client: Optional[AsyncClient] = None
_service_client: Optional[AsyncClient] = None

async def init_supabase():
    global _anon_client, _service_client
    url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url:
        raise ValueError("SUPABASE_URL env var is not set")

    if not _anon_client and anon_key:
        _anon_client = await create_client(url, anon_key)
    if not _service_client and service_key:
        _service_client = await create_client(url, service_key)

def get_anon_client() -> AsyncClient:
    if _anon_client is None:
        raise RuntimeError("Supabase anon client not initialized. Call init_supabase() first.")
    return _anon_client

def get_service_client() -> AsyncClient:
    if _service_client is None:
        raise RuntimeError("Supabase service client not initialized. Call init_supabase() first.")
    return _service_client
