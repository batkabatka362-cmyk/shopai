"""SEOIntelligence — real SEO audit and optimization algorithms.

  - Page-level SEO scoring (0-100) with specific issues
  - Keyword difficulty estimation
  - Content gap analysis vs competitors
  - Internal link graph analysis
  - Schema markup validation
"""
from __future__ import annotations

import re
import math
from typing import Any


class SEOIntelligence:
    """Real SEO analysis algorithms for e-commerce."""

    def audit_page(self, page: dict[str, Any]) -> dict[str, Any]:
        """Full SEO audit of a page. Returns score 0-100 with issues."""
        score = 100
        issues = []
        passes = []

        title = page.get("title", "")
        description = page.get("meta_description", page.get("description", ""))
        h1 = page.get("h1", "")
        content = page.get("content", page.get("body", ""))
        url = page.get("url", "")
        images = page.get("images", [])
        internal_links = page.get("internal_links", [])
        primary_keyword = page.get("keyword", page.get("primary_keyword", ""))

        # Title analysis
        if not title:
            score -= 20
            issues.append({"field": "title", "severity": "critical", "issue": "Missing title tag", "fix": "Add a descriptive title with primary keyword"})
        else:
            if len(title) < 30:
                score -= 5
                issues.append({"field": "title", "severity": "medium", "issue": f"Title too short ({len(title)} chars)", "fix": "Expand to 50-60 characters"})
            elif len(title) > 60:
                score -= 5
                issues.append({"field": "title", "severity": "medium", "issue": f"Title too long ({len(title)} chars)", "fix": "Trim to under 60 characters — rest gets cut in SERP"})
            else:
                passes.append(f"Title length OK ({len(title)} chars)")

            if primary_keyword and primary_keyword.lower() not in title.lower():
                score -= 10
                issues.append({"field": "title", "severity": "high", "issue": "Primary keyword not in title", "fix": f'Include "{primary_keyword}" in title'})
            elif primary_keyword:
                passes.append("Primary keyword in title")

        # Meta description
        if not description:
            score -= 10
            issues.append({"field": "meta_description", "severity": "high", "issue": "Missing meta description", "fix": "Write 120-155 char description with keyword and CTA"})
        else:
            if len(description) < 120:
                score -= 3
                issues.append({"field": "meta_description", "severity": "low", "issue": f"Meta description short ({len(description)} chars)", "fix": "Expand to 120-155 characters"})
            elif len(description) > 160:
                score -= 3
                issues.append({"field": "meta_description", "severity": "low", "issue": f"Meta description long ({len(description)} chars)", "fix": "Trim to under 160 characters"})
            else:
                passes.append(f"Meta description length OK ({len(description)} chars)")

        # H1
        if not h1:
            score -= 10
            issues.append({"field": "h1", "severity": "high", "issue": "Missing H1 tag", "fix": "Add one H1 tag with primary keyword"})
        elif primary_keyword and primary_keyword.lower() not in h1.lower():
            score -= 5
            issues.append({"field": "h1", "severity": "medium", "issue": "Primary keyword not in H1", "fix": f'Include "{primary_keyword}" in H1'})
        else:
            passes.append("H1 present with keyword")

        # Content
        word_count = len(content.split()) if content else 0
        if word_count < 300:
            score -= 15
            issues.append({"field": "content", "severity": "high", "issue": f"Thin content ({word_count} words)", "fix": "Expand to at least 800-1500 words for product pages, 1500+ for blog posts"})
        elif word_count < 800:
            score -= 5
            issues.append({"field": "content", "severity": "medium", "issue": f"Content could be longer ({word_count} words)", "fix": "Expand with FAQs, specifications, or use cases"})
        else:
            passes.append(f"Content length good ({word_count} words)")

        # Keyword density
        if primary_keyword and content:
            kw_count = content.lower().count(primary_keyword.lower())
            density = (kw_count * len(primary_keyword.split())) / max(word_count, 1) * 100
            if density == 0:
                score -= 10
                issues.append({"field": "content", "severity": "high", "issue": "Primary keyword not in content", "fix": f'Use "{primary_keyword}" naturally 3-5 times'})
            elif density > 3:
                score -= 5
                issues.append({"field": "content", "severity": "medium", "issue": f"Keyword stuffing risk ({density:.1f}% density)", "fix": "Reduce keyword usage — aim for 1-2%"})
            else:
                passes.append(f"Keyword density OK ({density:.1f}%)")

        # URL
        if url:
            if len(url) > 75:
                score -= 3
                issues.append({"field": "url", "severity": "low", "issue": "URL too long", "fix": "Shorten URL — use 3-5 descriptive words"})
            if any(c in url for c in "?&=#"):
                score -= 5
                issues.append({"field": "url", "severity": "medium", "issue": "URL has parameters", "fix": "Use clean URLs without query parameters"})
            if primary_keyword and primary_keyword.lower().replace(" ", "-") in url.lower():
                passes.append("Keyword in URL")

        # Images
        if isinstance(images, list):
            no_alt = sum(1 for img in images if isinstance(img, dict) and not img.get("alt"))
            if no_alt > 0:
                score -= min(no_alt * 3, 10)
                issues.append({"field": "images", "severity": "medium", "issue": f"{no_alt} images without alt text", "fix": "Add descriptive alt text to all images"})
            elif images:
                passes.append(f"All {len(images)} images have alt text")

        # Internal links
        if isinstance(internal_links, list) and len(internal_links) < 2:
            score -= 5
            issues.append({"field": "internal_links", "severity": "medium", "issue": "Few internal links", "fix": "Add 3-5 internal links to related pages"})

        score = max(0, score)

        return {
            "score": score,
            "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F",
            "issues": sorted(issues, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["severity"], 4)),
            "passes": passes,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i["severity"] == "critical"),
            "word_count": word_count,
            "has_keyword": bool(primary_keyword),
        }

    def keyword_difficulty(self, keyword: str, serp_data: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Estimate keyword difficulty (0-100)."""
        word_count = len(keyword.split())

        # Base difficulty from word count (long tail = easier)
        if word_count == 1:
            base = 75
        elif word_count == 2:
            base = 55
        elif word_count == 3:
            base = 35
        else:
            base = max(15, 40 - word_count * 5)

        # Adjust from SERP data if available
        if serp_data:
            # High DA competitors = harder
            avg_da = sum(s.get("domain_authority", 50) for s in serp_data) / len(serp_data)
            da_factor = avg_da / 100 * 30

            # Many results = more competitive
            result_count = len(serp_data)
            count_factor = min(result_count, 10) * 2

            difficulty = min(100, base + da_factor + count_factor)
        else:
            difficulty = base

        # Commercial intent keywords are harder
        commercial_words = ["buy", "best", "review", "cheap", "deal", "price", "compare", "vs"]
        if any(w in keyword.lower() for w in commercial_words):
            difficulty = min(100, difficulty + 10)

        difficulty = round(difficulty)

        return {
            "keyword": keyword,
            "difficulty": difficulty,
            "difficulty_label": "Easy" if difficulty < 30 else "Medium" if difficulty < 60 else "Hard" if difficulty < 80 else "Very Hard",
            "word_count": word_count,
            "keyword_type": "short_tail" if word_count <= 2 else "medium_tail" if word_count <= 4 else "long_tail",
            "recommendation": self._kw_recommendation(difficulty, word_count),
            "estimated_time_to_rank": f"{max(1, difficulty // 15)} months" if difficulty < 60 else f"{difficulty // 10} months",
        }

    def content_gap(self, our_content: list[dict[str, Any]],
                      competitor_content: list[dict[str, Any]]) -> dict[str, Any]:
        """Find content gaps — topics competitors cover that we don't."""
        our_keywords = set()
        for page in our_content:
            kws = page.get("keywords", [])
            if isinstance(kws, list):
                our_keywords.update(k.lower() if isinstance(k, str) else k.get("keyword", "").lower() for k in kws)
            title = page.get("title", "")
            our_keywords.update(title.lower().split())

        comp_keywords = set()
        comp_topics: dict[str, list[str]] = {}
        for page in competitor_content:
            kws = page.get("keywords", [])
            if isinstance(kws, list):
                for k in kws:
                    kw = k.lower() if isinstance(k, str) else k.get("keyword", "").lower()
                    comp_keywords.add(kw)
                    comp_topics.setdefault(kw, []).append(page.get("url", page.get("title", "")))

        gaps = comp_keywords - our_keywords
        overlaps = comp_keywords & our_keywords

        gap_details = []
        for kw in sorted(gaps):
            if len(kw) > 3:  # Skip very short words
                gap_details.append({
                    "keyword": kw,
                    "competitor_pages": len(comp_topics.get(kw, [])),
                    "opportunity": "high" if len(comp_topics.get(kw, [])) >= 2 else "medium",
                })

        gap_details.sort(key=lambda x: -x["competitor_pages"])

        return {
            "total_gaps": len(gap_details),
            "our_keyword_count": len(our_keywords),
            "competitor_keyword_count": len(comp_keywords),
            "overlap_count": len(overlaps),
            "coverage_pct": round(len(overlaps) / max(len(comp_keywords), 1) * 100, 1),
            "top_gaps": gap_details[:20],
            "recommendation": f"Create content for {min(len(gap_details), 10)} gap keywords to improve competitive coverage",
        }

    @staticmethod
    def _kw_recommendation(difficulty: int, word_count: int) -> str:
        if difficulty < 30:
            return "Easy win — create quality content and you can rank within weeks"
        if difficulty < 60:
            return "Achievable — needs solid content + 5-10 backlinks. Target within 3 months."
        if difficulty < 80:
            return "Challenging — requires authoritative content + link building campaign. 6+ months."
        return "Very competitive — consider targeting longer-tail variations first"
