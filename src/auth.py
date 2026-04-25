from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


class SupabaseUser(BaseModel):
    id: str
    email: Optional[str] = None


async def get_current_user(request: Request) -> SupabaseUser:
    authorization = request.headers.get("authorization") or request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing or invalid",
        )

    access_token = authorization.split(" ", 1)[1].strip()
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token missing",
        )

    url = f"{SUPABASE_URL}/auth/v1/user"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Supabase access token",
        )

    data = response.json()
    if not data or not data.get("id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Supabase user data",
        )

    return SupabaseUser(id=data["id"], email=data.get("email"))
