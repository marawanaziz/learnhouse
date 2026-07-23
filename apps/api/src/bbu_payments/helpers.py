"""Pure helpers for bbu_payments — no FastAPI/Stripe imports, so they're unit
testable in isolation and safe to reuse anywhere."""
from typing import Iterable


def merge_course_uuids(course_uuid_csvs: Iterable[str]) -> str:
    """Merge several comma-separated course_uuid strings into one deduped,
    order-preserving CSV. Used at checkout to compute the full set of courses a
    purchase (primary product + any order-bump add-ons) should unlock.

    Order matters (the first product's courses come first), and duplicates are
    dropped so a course granted by both the product and a bump isn't listed twice.
    """
    out, seen = [], set()
    for csv in course_uuid_csvs:
        for cu in (csv or "").split(","):
            cu = cu.strip()
            if cu and cu not in seen:
                seen.add(cu)
                out.append(cu)
    return ",".join(out)
