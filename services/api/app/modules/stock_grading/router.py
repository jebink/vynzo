"""HTTP layer for stock_grading: request parsing and response shaping only. No
business logic here.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/grades", tags=["stock-grading"])
