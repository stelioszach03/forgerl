from ..tasks import build_family, case as c

REFERENCE = {
    "formatting.py": """
import re

def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")

def slug(text):
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or "untitled"

def excerpt(text, limit):
    if type(limit) is not int or limit < 0:
        raise ValueError("invalid excerpt limit")
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return "." * limit
    return normalized[:limit-3].rstrip() + "..."
""",
    "content.py": """
from formatting import escape, slug, excerpt

def localized(post, locale):
    translated = post.get("translations", {}).get(locale, {})
    return {"title": translated.get("title", post["title"]), "body": translated.get("body", post["body"])}

def render(post, locale, limit):
    values = localized(post, locale)
    return {"id": post["id"], "path": "/articles/" + slug(post["title"]) + "-" + str(post["id"]),
            "title": escape(values["title"]), "summary": escape(excerpt(values["body"], limit))}

def ready(posts, now):
    result = [post for post in posts if post.get("status", "draft") == "published" and post.get("publish_at", 0) <= now]
    return sorted(result, key=lambda post: (-post.get("publish_at", 0), str(post["id"])))
""",
    "service.py": """
from formatting import excerpt
from content import ready, render

def run(request):
    if request.get("op") == "excerpt":
        return excerpt(request["text"], request["limit"])
    locale, limit = request.get("locale", "en"), request.get("excerpt_limit", 80)
    if request.get("op") == "render":
        return render(request["post"], locale, limit)
    posts = ready(request.get("posts", []), request.get("now", 0))
    after = request.get("after")
    if after is not None:
        positions = [i for i,post in enumerate(posts) if str(post["id"]) == str(after)]
        if not positions:
            raise ValueError("unknown cursor")
        posts = posts[positions[0] + 1:]
    page_size = request.get("page_size", 20)
    if type(page_size) is not int or page_size < 1:
        raise ValueError("invalid page size")
    page = posts[:page_size]
    return {"items": [render(post, locale, limit) for post in page],
            "next": str(page[-1]["id"]) if len(posts) > page_size else None}
""",
}
SPEC = "A miniature CMS exposes feed(default), render and excerpt operations. Feed selects status='published' and publish_at<=now(default0), ordered descending publish_at then lexical string id. after is an existing visible post id and is exclusive; unknown cursor ValueError. page_size is positive integer; next is last returned id only when more rows exist. Translation overrides title/body independently when a locale key exists, including intentionally empty values. Canonical paths derive from original title using lowercase ASCII alphanumerics, other runs '-' and fallback untitled; append '-{id}'. Escape&,<,>,double/single quotes in rendered text exactly once. Excerpts collapse whitespace, fit a nonnegative integer character limit, append '...' when truncated (limits0..3 return that many dots). All records have title/body/id."
P = lambda id, title="News", body="Text", **kw: {
    "id": id,
    "title": title,
    "body": body,
    "status": "published",
    **kw,
}
V = lambda id, title="News", summary="Text", slug="news": {
    "id": id,
    "path": f"/articles/{slug}-{id}",
    "title": title,
    "summary": summary,
}
FEED = lambda items, next=None: {"items": items, "next": next}
ESC = (
    "formatting.py",
    'text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")',
    'text.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")',
)
LOCALE = (
    "content.py",
    'translated.get("title", post["title"]), "body": translated.get("body", post["body"])',
    'translated.get("title") or post["title"], "body": translated.get("body") or post["body"]',
)
SCHEDULE = (
    "content.py",
    'post.get("publish_at", 0) <= now',
    'post.get("publish_at", 0) < now',
)
CURSOR = (
    "service.py",
    "posts = posts[positions[0] + 1:]",
    "posts = posts[positions[0]:]",
)
SPACE = ("formatting.py", 'normalized = " ".join(text.split())', "normalized = text")
LENGTH = (
    "formatting.py",
    'normalized[:limit-3].rstrip() + "..."',
    'normalized[:limit].rstrip() + "..."',
)


def tasks():
    return build_family(
        "publishing",
        "train",
        REFERENCE,
        SPEC,
        [
            dict(
                slug="text-escaping",
                title="Avoid double-escaping rendered CMS text",
                category="bug_fix",
                summary="Generated escape entities are escaped a second time.",
                instructions="Correct escaping order for both title and summary, including existing literal entities.",
                mutations=[ESC],
                public=[
                    c(
                        "tag text",
                        {"op": "render", "post": P("1", "<News>", "A&B")},
                        V("1", "&lt;News&gt;", "A&amp;B"),
                    ),
                    c(
                        "quotes",
                        {"op": "render", "post": P("2", '"Hi"', "'x'")},
                        V("2", "&quot;Hi&quot;", "&#39;x&#39;", "hi"),
                    ),
                ],
                hidden=[
                    c(
                        "literal entity",
                        {"op": "render", "post": P("a", "News", "&lt;")},
                        V("a", summary="&amp;lt;"),
                    ),
                    c("normal", {"op": "render", "post": P("1")}, V("1")),
                    c(
                        "empty title",
                        {"op": "render", "post": P("x", "", "<")},
                        V("x", "", "&lt;", "untitled"),
                    ),
                    c(
                        "combined",
                        {"op": "render", "post": P("b", "A & B", "<&>")},
                        V("b", "A &amp; B", "&lt;&amp;&gt;", "a-b"),
                    ),
                ],
            ),
            dict(
                slug="partial-translations",
                title="Support intentionally empty localized fields",
                category="feature",
                summary="Blank translations fall back to original text unexpectedly.",
                instructions="Use key presence rather than truthiness, with independent fallback per field and stable canonical paths.",
                mutations=[LOCALE],
                public=[
                    c(
                        "empty title",
                        {
                            "op": "render",
                            "locale": "el",
                            "post": P("1", translations={"el": {"title": ""}}),
                        },
                        V("1", ""),
                    ),
                    c(
                        "empty body",
                        {
                            "op": "render",
                            "locale": "el",
                            "post": P("1", translations={"el": {"body": ""}}),
                        },
                        V("1", summary=""),
                    ),
                ],
                hidden=[
                    c(
                        "partial",
                        {
                            "op": "render",
                            "locale": "el",
                            "post": P("1", translations={"el": {"title": "Νέα"}}),
                        },
                        V("1", "Νέα"),
                    ),
                    c(
                        "unknown locale",
                        {
                            "op": "render",
                            "locale": "fr",
                            "post": P("1", translations={"el": {"title": "Νέα"}}),
                        },
                        V("1"),
                    ),
                    c(
                        "localized escape",
                        {
                            "op": "render",
                            "locale": "el",
                            "post": P("1", translations={"el": {"body": "<x>"}}),
                        },
                        V("1", summary="&lt;x&gt;"),
                    ),
                    c(
                        "path original",
                        {
                            "op": "render",
                            "locale": "el",
                            "post": P(
                                "1",
                                "Hello World",
                                translations={"el": {"title": "News"}},
                            ),
                        },
                        V("1", slug="hello-world"),
                    ),
                ],
            ),
            dict(
                slug="feed-continuation",
                title="Publish scheduled posts with exclusive cursors",
                category="multi_file",
                summary="Boundary publication and pagination produce missing and duplicate posts.",
                instructions="Include exactly-due published posts and resume after the cursor without repeating it.",
                mutations=[SCHEDULE, CURSOR],
                public=[
                    c(
                        "due",
                        {"now": 5, "posts": [P("1", publish_at=5)]},
                        FEED([V("1")]),
                    ),
                    c(
                        "exclusive",
                        {
                            "now": 10,
                            "posts": [P("1", publish_at=2), P("2", publish_at=1)],
                            "after": "1",
                        },
                        FEED([V("2")]),
                    ),
                ],
                hidden=[
                    c(
                        "page token",
                        {
                            "now": 10,
                            "posts": [P("2", publish_at=1), P("1", publish_at=2)],
                            "page_size": 1,
                        },
                        FEED([V("1")], "1"),
                    ),
                    c(
                        "draft",
                        {"now": 10, "posts": [P("1", status="draft")]},
                        FEED([]),
                    ),
                    c("future", {"now": 0, "posts": [P("1", publish_at=1)]}, FEED([])),
                    c("unknown", {"posts": [], "after": "bad"}, error="ValueError"),
                ],
            ),
            dict(
                slug="shared-excerpts",
                title="Normalize excerpt behavior across CMS facades",
                category="refactor",
                summary="Render and excerpt APIs preserve irregular whitespace and exceed limits.",
                instructions="Restore one consistent excerpt contract for standalone and rendered summaries. Tests check behavioral compatibility rather than a specific refactor layout.",
                mutations=[SPACE, LENGTH],
                public=[
                    c(
                        "whitespace",
                        {"op": "excerpt", "text": " a  b\nc ", "limit": 20},
                        "a b c",
                    ),
                    c(
                        "limit",
                        {"op": "excerpt", "text": "abcdefghij", "limit": 6},
                        "abc...",
                    ),
                ],
                hidden=[
                    c("zero", {"op": "excerpt", "text": "abc", "limit": 0}, ""),
                    c("two", {"op": "excerpt", "text": "abc", "limit": 2}, ".."),
                    c("exact", {"op": "excerpt", "text": "abc", "limit": 3}, "abc"),
                    c(
                        "render",
                        {
                            "op": "render",
                            "post": P("1", body=" a  b  cdefgh "),
                            "excerpt_limit": 7,
                        },
                        V("1", summary="a b..."),
                    ),
                    c(
                        "invalid",
                        {"op": "excerpt", "text": "abc", "limit": -1},
                        error="ValueError",
                    ),
                ],
            ),
            dict(
                slug="cms-release",
                title="Recover the CMS publishing and rendering pipeline",
                category="long_horizon",
                difficulty="hard",
                summary="Localization, scheduling, pagination and text formatting fail together.",
                instructions="Repair safe text escaping, intentional blank translations, normalized bounded excerpts, scheduled publication and exclusive pagination. Miniature integrated stress task.",
                mutations=[ESC, LOCALE, SCHEDULE, CURSOR, SPACE, LENGTH],
                public=[
                    c(
                        "combined",
                        {
                            "now": 5,
                            "locale": "el",
                            "posts": [
                                P(
                                    "1",
                                    publish_at=5,
                                    translations={"el": {"title": "<N>", "body": ""}},
                                )
                            ],
                        },
                        FEED([V("1", "&lt;N&gt;", "")]),
                    ),
                    c(
                        "pagination",
                        {"now": 0, "posts": [P("1"), P("2")], "after": "1"},
                        FEED([V("2")]),
                    ),
                ],
                hidden=[
                    c(
                        "excerpt",
                        {"op": "excerpt", "text": " abcdefghi ", "limit": 6},
                        "abc...",
                    ),
                    c("draft", {"now": 8, "posts": [P("1", status="draft")]}, FEED([])),
                    c(
                        "quote",
                        {"op": "render", "post": P("1", body="<>&")},
                        V("1", summary="&lt;&gt;&amp;"),
                    ),
                    c(
                        "empty localization",
                        {
                            "op": "render",
                            "locale": "el",
                            "post": P("1", translations={"el": {"title": ""}}),
                        },
                        V("1", ""),
                    ),
                    c(
                        "stable tie",
                        {"posts": [P("b"), P("a")], "page_size": 1},
                        FEED([V("a")], "a"),
                    ),
                ],
            ),
        ],
    )
