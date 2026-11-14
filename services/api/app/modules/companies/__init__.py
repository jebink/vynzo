"""Company master: legal entity, sector/industry, identifiers. A company has one or more listings
(see instruments).
"""

# shortcut: fixed rupee cut-offs near AMFI's Large (top 100) / Mid (101-250) lines; switch to
# AMFI's twice-yearly rank list if the buckets drift from it.
LARGE_CAP_INR = 1e12  # 1,00,000 crore
MID_CAP_INR = 3.3e11  # 33,000 crore


def market_cap(shares_outstanding: int | None, price: float | None) -> dict:
    """market_cap (INR) and cap_category ("large" | "mid" | "small"), both None if unknown."""
    if not shares_outstanding or price is None:
        return {"market_cap": None, "cap_category": None}
    cap = shares_outstanding * float(price)
    category = "large" if cap >= LARGE_CAP_INR else "mid" if cap >= MID_CAP_INR else "small"
    return {"market_cap": cap, "cap_category": category}
