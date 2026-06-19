SEVERITY = {
    "reviewed": 0,
    "raw-only": 1,
    "candidate": 2,
    "raw-unavailable": 3,
    "restricted": 4,
}


def claim_status(obj: dict, *, raw_available: bool, restricted: bool) -> str:
    if restricted:
        return "restricted"
    if obj.get("status") == "reviewed":
        if obj.get("evidence_refs") and not raw_available:
            return "raw-unavailable"
        return "reviewed"
    if obj.get("status") == "candidate":
        return "candidate"
    return "raw-only"


def answer_status(statuses: list[str]) -> str:
    if not statuses:
        return "raw-only"
    return max(statuses, key=lambda status: SEVERITY[status])
