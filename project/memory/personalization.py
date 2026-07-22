"""Personalization — the agent learns each analyst's preferences.

A small per-user profile the system reads on every request and writes when it learns
something: the regions and categories the analyst covers, the KPIs they default to, and how
they like answers formatted. This is LONG-TERM memory (cross-thread) — keyed by user_id, not
thread_id. Backed by a JSON file under `ROOT/data/local/profiles/` (git-ignored; created
lazily on first save).

Loom & Co. example: an analyst who always wants margin reported in USD by category. Once the
profile records `default_kpis=["gross_margin"]`, `output_format="table"`, `currency="USD"`,
every answer respects that without being asked. And when they say *"how's the West region
doing on Outerwear?"*, `learn_from_query` infers West + Outerwear into their coverage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from project.config import ROOT

# Long-term profile store. data/local/ is git-ignored; the dir is created on first save().
PROFILES_DIR = ROOT / "data" / "local" / "profiles"

# Output formats we recognize when learning from a query (free-text words -> profile value).
# Maps a word that may appear in a query to the canonical output_format we store.
_FORMAT_WORDS = {
    "table": "table",
    "bullets": "bullets",
    "bullet": "bullets",
    "memo": "memo",
    "prose": "prose",
}

# The Loom & Co. taxonomy (see data/docs/data-dictionary.md). We match these by name in a
# query to learn what an analyst covers — no fragile free-text extraction needed.
_REGIONS = ("West", "Northeast", "South", "Midwest")
_CATEGORIES = ("Tops", "Bottoms", "Outerwear", "Footwear", "Accessories")

# KPI phrasings we can spot in a query -> the canonical KPI key we store.
_KPI_ALIASES = {
    "net revenue": "net_revenue",
    "revenue": "net_revenue",
    "gross margin": "gross_margin",
    "margin": "gross_margin",
    "aov": "aov",
    "average order value": "aov",
    "conversion rate": "conversion_rate",
    "conversion": "conversion_rate",
    "return rate": "return_rate",
    "returns": "return_rate",
}


class UserProfile(BaseModel):
    """What the BI Analyst Agent remembers about one analyst across conversations."""

    user_id: str
    coverage_regions: list[str] = Field(default_factory=list)  # e.g. ["West", "Northeast"]
    coverage_categories: list[str] = Field(default_factory=list)  # e.g. ["Outerwear"]
    default_kpis: list[str] = Field(default_factory=list)  # e.g. ["gross_margin", "aov"]
    output_format: str = "prose"  # "prose" | "bullets" | "memo" | "table"
    currency: str = "USD"


def load_profile(user_id: str) -> UserProfile:
    """Load a user's profile, or return a fresh default if none exists yet."""
    path = PROFILES_DIR / f"{user_id}.json"
    if path.exists():
        return UserProfile.model_validate_json(path.read_text())
    return UserProfile(user_id=user_id)


def save_profile(profile: UserProfile, user_id: str | None = None) -> None:
    """Persist a profile (long-term memory). Creates the profiles dir lazily.

    `user_id` overrides the filename when provided; otherwise the profile's own `user_id`
    is used.
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    uid = user_id or profile.user_id
    (PROFILES_DIR / f"{uid}.json").write_text(profile.model_dump_json(indent=2))


def apply_profile(profile: UserProfile, system_prompt: str) -> str:
    """Fold the profile into a system prompt so answers respect the analyst's prefs.

    `system_prompt` may be a supervisor/synthesis system prompt; we append the analyst's
    standing preferences so "the usual" resolves to their coverage and every answer comes
    back in their format/currency with their default KPIs.
    """
    regions = ", ".join(profile.coverage_regions) or "all regions"
    categories = ", ".join(profile.coverage_categories) or "all categories"
    kpis = ", ".join(profile.default_kpis) or "none set"
    prefs = (
        "\n\nAnalyst preferences (apply these unless the question overrides them; resolve "
        "'my coverage'/'the usual' to the coverage regions and categories below):\n"
        f"- Coverage regions: {regions}\n"
        f"- Coverage categories: {categories}\n"
        f"- Default KPIs: {kpis}\n"
        f"- Output format: {profile.output_format}\n"
        f"- Currency: {profile.currency}"
    )
    return system_prompt + prefs


def _match_terms(query: str, terms: tuple[str, ...]) -> list[str]:
    """Return the taxonomy terms mentioned in the query (case-insensitive)."""
    lowered = query.lower()
    return [t for t in terms if t.lower() in lowered]


def _match_kpis(query: str) -> list[str]:
    """Return canonical KPI keys mentioned in the query (longest alias wins per match)."""
    lowered = query.lower()
    found: list[str] = []
    for alias, key in sorted(_KPI_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in lowered and key not in found:
            found.append(key)
    return found


def _match_format(query: str) -> str | None:
    """Return the canonical output_format implied by the query, or None."""
    lowered = query.lower()
    for word, fmt in _FORMAT_WORDS.items():
        if word in lowered:
            return fmt
    return None


def learn_from_query(profile: UserProfile, question: str) -> UserProfile:
    """Infer & persist preferences from a query, then save.

    - Detects an output format from words like 'table'/'bullets'/'memo'/'prose'.
    - Adds mentioned Loom regions/categories to the analyst's coverage.
    - Adds mentioned KPIs to their defaults.
    Returns the updated (and persisted) profile.
    """
    fmt = _match_format(question)
    if fmt:
        profile.output_format = fmt

    for region in _match_terms(question, _REGIONS):
        if region not in profile.coverage_regions:
            profile.coverage_regions.append(region)

    for category in _match_terms(question, _CATEGORIES):
        if category not in profile.coverage_categories:
            profile.coverage_categories.append(category)

    for kpi in _match_kpis(question):
        if kpi not in profile.default_kpis:
            profile.default_kpis.append(kpi)

    save_profile(profile)
    return profile


if __name__ == "__main__":
    p = load_profile("demo-analyst-1")
    # Simulate the breakout: the system *learns* from a query instead of being told.
    p = learn_from_query(
        p, "give me a table of gross margin for Outerwear in the West region"
    )
    print(
        f"learned format={p.output_format!r}, regions={p.coverage_regions}, "
        f"categories={p.coverage_categories}, kpis={p.default_kpis}"
    )
    print(apply_profile(load_profile("demo-analyst-1"), "You are the Loom & Co. BI analyst."))
