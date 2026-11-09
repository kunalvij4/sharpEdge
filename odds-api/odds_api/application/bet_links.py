"""Public link context for the exact quote selected by the feed merger."""


def bet_link(quote, book_key, fresh):
    if not fresh:
        return None
    provider = book_key.split("_", 1)[0]
    result = {"provider": provider}
    if provider == "unabated":
        result.update(
            market_line_id=quote["source_selection_id"],
            market_source_id=book_key.removeprefix("unabated_"),
        )
    if quote.get("deep_link"):
        result["url"] = quote["deep_link"]
    if quote.get("app_link"):
        result["app_url"] = quote["app_link"]
    if "url" in result or "app_url" in result:
        result["status"] = "event_support" if provider == "propline" else "provided"
    return result if "url" in result or "app_url" in result or provider == "unabated" else None
