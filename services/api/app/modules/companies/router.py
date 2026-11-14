"""HTTP layer for companies: request parsing and response shaping only. No business logic here."""

from fastapi import APIRouter

router = APIRouter(prefix="/companies", tags=["companies"])
