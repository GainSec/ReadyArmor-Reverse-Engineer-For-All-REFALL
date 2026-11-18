from urllib.parse import quote


def format_provided_wishlist(subject, provided_wishes):
    endpoint = f"/wishlist?subject={quote(subject)}&status=provided"
    lines = [
        "DELIVERED WISHLIST ITEMS:",
        f"- Check {endpoint} during preflight for the live delivered-tool/access state.",
    ]
    wishes = list(provided_wishes or [])
    if not wishes:
        lines.append("- No delivered wishlist items are recorded yet.")
    else:
        lines.append("- Use these before requesting duplicate tooling. Do not re-request matching items.")
        for wish in wishes:
            kind = wish.get("kind") or "item"
            item = wish.get("item") or "(unnamed)"
            requested_by = wish.get("requested_by") or "unknown agent"
            reason = wish.get("reason") or "no reason recorded"
            lines.append(f"  * {kind}: {item} — requested by {requested_by}; reason: {reason}")
    return "\n".join(lines)


def provided_wishes_from(cov, subject):
    try:
        return cov.wishlist(subject, status="provided")
    except Exception:
        return []
