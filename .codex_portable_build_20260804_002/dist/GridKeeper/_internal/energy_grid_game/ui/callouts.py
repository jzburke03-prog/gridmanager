"""Learn-more hook for instructional call-out boxes (SPEC-1.1 §3.7).

The energy two-pagers are not written yet, and Instructional Mode must not wait
on them. So CONTENT ships empty: a step whose `learn_more` key has no entry
renders no button at all — not a greyed-out one, not a "coming soon". Days 1-4
are complete and shippable exactly as they are, and each two-pager goes live the
moment its entry is added, with no code change.

That is the ONLY reason this indirection exists. Do not replace it with a direct
link per step.

To add one, decide the delivery mechanism and fill in entries:

    CONTENT["solar"] = {
        "title": "Solar",
        "body": ["Two or three lines shown in the call-out."],
        "link": "https://example.org/solar-two-pager.pdf",   # or None
    }
"""
import webbrowser

# source_key -> {"title": str, "body": [str], "link": str | None}
CONTENT = {}


def has(key) -> bool:
    """True when there is something to show. The call-out button is drawn only
    when this is True, so an empty CONTENT is a complete, shippable state."""
    return bool(key) and key in CONTENT


def get(key):
    return CONTENT.get(key)


def open_link(key) -> bool:
    """Open the two-pager for `key`. Returns whether anything was opened.

    Only follows an explicit `link` from CONTENT — never a URL from anywhere
    else — and failing to open is never fatal to the game loop.
    """
    entry = CONTENT.get(key)
    if not entry:
        return False
    link = entry.get("link")
    if not link:
        return False
    try:
        return webbrowser.open(link)
    except Exception:
        return False
