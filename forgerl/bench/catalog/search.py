from ..tasks import build_family, case as c

REFERENCE = {
    "indexing.py": """
import re

def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())

def index(documents):
    result, seen = [], set()
    for document in documents:
        if document["id"] in seen:
            raise ValueError("duplicate document id")
        seen.add(document["id"])
        counts = {}
        for token in tokens(document["title"] + " " + document["body"]):
            counts[token] = counts.get(token, 0) + 1
        result.append((document, counts))
    return result
""",
    "ranking.py": """
from indexing import tokens

def ranked(indexed, query, mode, labels):
    if mode not in ("all", "any"):
        raise ValueError("unknown query mode")
    terms = list(dict.fromkeys(tokens(query)))
    if not terms:
        return []
    result = []
    for doc, counts in indexed:
        if not all(label in doc.get("labels", []) for label in labels):
            continue
        hits = [term in counts for term in terms]
        if (mode == "all" and all(hits)) or (mode == "any" and any(hits)):
            result.append({"id": doc["id"], "title": doc["title"], "score": sum(counts.get(term, 0) for term in terms)})
    return sorted(result, key=lambda row: (-row["score"], row["id"]))

def facets(indexed):
    result = {}
    for doc, _ in indexed:
        for label in set(doc.get("labels", [])):
            result[label] = result.get(label, 0) + 1
    return dict(sorted(result.items()))
""",
    "service.py": """
from indexing import index
from ranking import ranked, facets

def run(request):
    indexed = index(request.get("documents", []))
    if request.get("op") == "facets":
        return facets(indexed)
    rows = ranked(indexed, request.get("query", ""), request.get("mode", "all"), request.get("labels", []))
    offset, limit = request.get("offset", 0), request.get("limit", 10)
    if type(offset) is not int or type(limit) is not int or offset < 0 or limit < 1:
        raise ValueError("invalid pagination")
    return {"total": len(rows), "items": rows[offset:offset + limit]}
""",
}
SPEC = "A deterministic lexical document search indexes lowercase ASCII letters/digits from title and body, preserving term frequencies. Unique document ids required. Query terms are deduplicated; empty/punctuation-only queries return no hits. mode=all(default) requires every term; any requires at least one; unknown mode ValueError. Filter labels require every supplied label. Score is summed indexed frequencies for unique query terms. Sort descending score then ascending id. Search returns pre-pagination total and offset/limit slice; strict integer offset>=0,limit>=1. op=facets counts documents per label, never repeated labels within a document. This is lexical retrieval, not semantic/ML search."
D = lambda id, title, body="", labels=[]: {
    "id": id,
    "title": title,
    "body": body,
    "labels": labels,
}
H = lambda id, title, score: {"id": id, "title": title, "score": score}
R = lambda items, total=None: {
    "total": len(items) if total is None else total,
    "items": items,
}
CASE = ("indexing.py", "text.lower()", "text")
FREQ = ("indexing.py", "counts[token] = counts.get(token, 0) + 1", "counts[token] = 1")
TERMS = (
    "ranking.py",
    "terms = list(dict.fromkeys(tokens(query)))",
    "terms = tokens(query)",
)
LABEL = (
    "ranking.py",
    'not all(label in doc.get("labels", []) for label in labels)',
    'labels and not any(label in doc.get("labels", []) for label in labels)',
)
FACET = (
    "ranking.py",
    'for label in set(doc.get("labels", [])):',
    'for label in doc.get("labels", []):',
)
ORDER = ("ranking.py", '(-row["score"], row["id"])', '(row["score"], row["id"])')
PAGE = ("service.py", "rows[offset:offset + limit]", "rows[offset:limit]")


def tasks():
    return build_family(
        "search",
        "test",
        REFERENCE,
        SPEC,
        [
            dict(
                slug="case-normalization",
                title="Normalize document and query token case",
                category="bug_fix",
                summary="Uppercase words disappear from the lexical index.",
                instructions="Apply the same lowercase ASCII tokenization to documents and queries without merging punctuation-separated words.",
                mutations=[CASE],
                public=[
                    c(
                        "title uppercase",
                        {"documents": [D("a", "HELLO")], "query": "hello"},
                        R([H("a", "HELLO", 1)]),
                    ),
                    c(
                        "query uppercase",
                        {"documents": [D("a", "hello")], "query": "HELLO"},
                        R([H("a", "hello", 1)]),
                    ),
                ],
                hidden=[
                    c(
                        "punctuation",
                        {"documents": [D("a", "A-B")], "query": "a b"},
                        R([H("a", "A-B", 2)]),
                    ),
                    c(
                        "digits",
                        {"documents": [D("a", "Model 42")], "query": "42"},
                        R([H("a", "Model 42", 1)]),
                    ),
                    c(
                        "empty query",
                        {"documents": [D("a", "hello")], "query": "!!!"},
                        R([]),
                    ),
                    c(
                        "plain",
                        {"documents": [D("a", "hello")], "query": "hello"},
                        R([H("a", "hello", 1)]),
                    ),
                ],
            ),
            dict(
                slug="frequency-ranking",
                title="Implement frequency-aware deduplicated scoring",
                category="multi_file",
                summary="The index loses frequencies while repeated query words inflate score.",
                instructions="Preserve corpus term frequency, count each distinct query token once and retain ranking tie-breaks.",
                mutations=[FREQ, TERMS],
                public=[
                    c(
                        "frequency",
                        {"documents": [D("a", "x x", "x")], "query": "x"},
                        R([H("a", "x x", 3)]),
                    ),
                    c(
                        "query repeated",
                        {"documents": [D("a", "x y")], "query": "x x y"},
                        R([H("a", "x y", 2)]),
                    ),
                ],
                hidden=[
                    c(
                        "ordered",
                        {"documents": [D("a", "x"), D("b", "x x")], "query": "x"},
                        R([H("b", "x x", 2), H("a", "x", 1)]),
                    ),
                    c(
                        "any",
                        {"documents": [D("a", "x")], "query": "x z", "mode": "any"},
                        R([H("a", "x", 1)]),
                    ),
                    c("all", {"documents": [D("a", "x")], "query": "x z"}, R([])),
                    c(
                        "duplicate document",
                        {"documents": [D("a", "x"), D("a", "y")], "query": "x"},
                        error="ValueError",
                    ),
                ],
            ),
            dict(
                slug="label-semantics",
                title="Add conjunctive label filters and document facets",
                category="feature",
                summary="Label filtering accepts partial matches and facets count duplicate tags.",
                instructions="Require all filter labels and count each label once per document in facets.",
                mutations=[LABEL, FACET],
                public=[
                    c(
                        "all labels",
                        {
                            "documents": [
                                D("a", "x", labels=["A"]),
                                D("b", "x", labels=["A", "B"]),
                            ],
                            "query": "x",
                            "labels": ["A", "B"],
                        },
                        R([H("b", "x", 1)]),
                    ),
                    c(
                        "facets",
                        {
                            "op": "facets",
                            "documents": [
                                D("a", "x", labels=["A", "A"]),
                                D("b", "y", labels=["A", "B"]),
                            ],
                        },
                        {"A": 2, "B": 1},
                    ),
                ],
                hidden=[
                    c(
                        "no labels",
                        {"documents": [D("a", "x")], "query": "x"},
                        R([H("a", "x", 1)]),
                    ),
                    c(
                        "missing",
                        {"documents": [D("a", "x")], "query": "x", "labels": ["A"]},
                        R([]),
                    ),
                    c(
                        "repeated filter",
                        {
                            "documents": [D("a", "x", labels=["A"])],
                            "query": "x",
                            "labels": ["A", "A"],
                        },
                        R([H("a", "x", 1)]),
                    ),
                    c("empty facets", {"op": "facets", "documents": []}, {}),
                ],
            ),
            dict(
                slug="ranked-pagination",
                title="Preserve ranking across nonzero-offset pages",
                category="failing_tests",
                summary="The second page slices at the limit instead of offset plus limit.",
                instructions="Sort strongest results first and apply offset/limit after scoring, preserving total hit count.",
                mutations=[ORDER, PAGE],
                public=[
                    c(
                        "descending",
                        {"documents": [D("a", "x"), D("b", "x x")], "query": "x"},
                        R([H("b", "x x", 2), H("a", "x", 1)]),
                    ),
                    c(
                        "offset",
                        {
                            "documents": [D("a", "x"), D("b", "x"), D("c", "x")],
                            "query": "x",
                            "offset": 1,
                            "limit": 1,
                        },
                        R([H("b", "x", 1)], 3),
                    ),
                ],
                hidden=[
                    c(
                        "tie",
                        {
                            "documents": [D("b", "x"), D("a", "x")],
                            "query": "x",
                            "limit": 1,
                        },
                        R([H("a", "x", 1)], 2),
                    ),
                    c(
                        "beyond",
                        {"documents": [D("a", "x")], "query": "x", "offset": 8},
                        R([], 1),
                    ),
                    c("invalid", {"query": "x", "limit": 0}, error="ValueError"),
                    c("negative", {"query": "x", "offset": -1}, error="ValueError"),
                ],
            ),
            dict(
                slug="search-release",
                title="Recover the document discovery pipeline",
                category="long_horizon",
                difficulty="hard",
                summary="Tokenization, scoring, tags and pagination regressed together.",
                instructions="Restore case normalization, frequencies, unique query terms, conjunctive labels, distinct-document facets, score order and offset pagination. Miniature integrated stress task.",
                mutations=[CASE, FREQ, TERMS, LABEL, FACET, ORDER, PAGE],
                public=[
                    c(
                        "combined",
                        {
                            "documents": [
                                D("a", "X", labels=["A", "B"]),
                                D("b", "X X", labels=["A", "B"]),
                                D("c", "X X X", labels=["A"]),
                            ],
                            "query": "X x",
                            "labels": ["A", "B"],
                            "offset": 1,
                            "limit": 1,
                        },
                        R([H("a", "X", 1)], 2),
                    ),
                    c(
                        "facets",
                        {"op": "facets", "documents": [D("a", "x", labels=["A", "A"])]},
                        {"A": 1},
                    ),
                ],
                hidden=[
                    c(
                        "all terms",
                        {"documents": [D("a", "X Y")], "query": "x y"},
                        R([H("a", "X Y", 2)]),
                    ),
                    c(
                        "any term",
                        {"documents": [D("a", "X")], "query": "x y", "mode": "any"},
                        R([H("a", "X", 1)]),
                    ),
                    c("empty", {"documents": [D("a", "X")], "query": ""}, R([])),
                    c(
                        "ties",
                        {"documents": [D("b", "X"), D("a", "X")], "query": "x"},
                        R([H("a", "X", 1), H("b", "X", 1)]),
                    ),
                    c("bad mode", {"query": "x", "mode": "fuzzy"}, error="ValueError"),
                ],
            ),
        ],
    )
