"""HTTP layer for fundamentals: request parsing and response shaping only. No
business logic here.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])
