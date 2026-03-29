"""SeoLogic — deep business logic for SEO engines."""
from __future__ import annotations
from typing import Any


class SeoLogic:
    """Real SEO computations."""

    SEO_ENGINES = {
        "seo", "keyword_research", "content_optimization", "search_optimization",
        "link_building", "local_seo", "international_seo", "voice_search",
        "featured_snippet", "structured_data", "sitemap_generation",
        "title_optimizer", "meta_description", "internal_linking",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.SEO_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        keywords = data.get("keywords", data.get("seed_keywords", data.get("keyword_data", [])))
        page_data = data.get("page_data", data.get("content_data", {}))

        if isinstance(keywords, list) and keywords:
            result["keyword_analysis"] = self._analyze_keywords(keywords)

        if isinstance(page_data, dict) and page_data:
            result["on_page_audit"] = self._audit_on_page(page_data)

        result["score"] = self._seo_score(result)
        result["decision"] = "approve" if result["score"] >= 5 else "reject"
        result["reason"] = self._seo_reason(result)
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        keywords = data.get("keywords", data.get("seed_keywords", []))
        page = data.get("page_data", data.get("content_data", {}))

        if isinstance(keywords, list) and keywords:
            result["keyword_strategy"] = self._build_keyword_strategy(keywords)

        if isinstance(page, dict) and page:
            result["optimization_actions"] = self._generate_actions(page)
            result["meta_recommendations"] = self._recommend_meta(page)

        result["technical_checklist"] = self._technical_checklist()
        result["generated"] = True
        return result

    def _analyze_keywords(self, keywords: list) -> dict:
        analyzed = []
        for kw in keywords:
            if isinstance(kw, str):
                analyzed.append({"keyword": kw, "word_count": len(kw.split()), "type": self._keyword_type(kw)})
            elif isinstance(kw, dict):
                vol = int(kw.get("volume", kw.get("search_volume", 0)))
                diff = float(kw.get("difficulty", kw.get("kd", 50)))
                analyzed.append({
                    "keyword": kw.get("keyword", kw.get("term", "")),
                    "volume": vol,
                    "difficulty": diff,
                    "opportunity_score": round((vol / 1000) * (100 - diff) / 100, 2) if vol > 0 else 0,
                    "type": self._keyword_type(kw.get("keyword", "")),
                })

        analyzed.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        return {
            "total_keywords": len(analyzed),
            "keywords": analyzed,
            "top_opportunities": analyzed[:5],
            "long_tail_count": sum(1 for a in analyzed if a.get("type") == "long_tail"),
        }

    def _audit_on_page(self, page: dict) -> dict:
        issues = []
        title = page.get("title", "")
        description = page.get("description", page.get("meta_description", ""))
        h1 = page.get("h1", "")
        content = page.get("content", page.get("body", ""))

        if not title: issues.append({"field": "title", "issue": "missing", "severity": "high"})
        elif len(title) > 60: issues.append({"field": "title", "issue": "too_long", "severity": "medium", "length": len(title)})
        elif len(title) < 30: issues.append({"field": "title", "issue": "too_short", "severity": "medium", "length": len(title)})

        if not description: issues.append({"field": "meta_description", "issue": "missing", "severity": "high"})
        elif len(description) > 160: issues.append({"field": "meta_description", "issue": "too_long", "severity": "medium"})

        if not h1: issues.append({"field": "h1", "issue": "missing", "severity": "high"})

        word_count = len(content.split()) if isinstance(content, str) else 0
        if word_count < 300: issues.append({"field": "content", "issue": "thin_content", "severity": "high", "word_count": word_count})

        return {
            "issues": issues,
            "issue_count": len(issues),
            "high_severity": sum(1 for i in issues if i["severity"] == "high"),
            "word_count": word_count,
            "has_title": bool(title),
            "has_description": bool(description),
            "has_h1": bool(h1),
        }

    def _build_keyword_strategy(self, keywords: list) -> dict:
        primary = []
        secondary = []
        long_tail = []

        for kw in keywords:
            term = kw if isinstance(kw, str) else kw.get("keyword", "")
            ktype = self._keyword_type(term)
            if ktype == "short_tail": primary.append(term)
            elif ktype == "medium_tail": secondary.append(term)
            else: long_tail.append(term)

        return {
            "primary_keywords": primary[:3],
            "secondary_keywords": secondary[:5],
            "long_tail_keywords": long_tail[:10],
            "content_clusters": self._build_clusters(keywords),
        }

    def _build_clusters(self, keywords: list) -> list[dict]:
        terms = [kw if isinstance(kw, str) else kw.get("keyword", "") for kw in keywords]
        words: dict[str, list[str]] = {}
        for term in terms:
            for word in term.lower().split():
                if len(word) > 3:
                    words.setdefault(word, []).append(term)
        clusters = [{"theme": word, "keywords": list(set(kws))[:5]} for word, kws in words.items() if len(kws) >= 2]
        return sorted(clusters, key=lambda x: len(x["keywords"]), reverse=True)[:5]

    def _generate_actions(self, page: dict) -> list[dict]:
        actions = []
        title = page.get("title", "")
        if not title: actions.append({"action": "add_title", "priority": "high", "impact": "high"})
        if not page.get("description"): actions.append({"action": "add_meta_description", "priority": "high", "impact": "high"})
        if not page.get("h1"): actions.append({"action": "add_h1", "priority": "high", "impact": "medium"})

        content = page.get("content", "")
        if isinstance(content, str) and len(content.split()) < 1000:
            actions.append({"action": "expand_content", "priority": "medium", "impact": "high", "target_words": 1500})

        if not page.get("images"): actions.append({"action": "add_images", "priority": "medium", "impact": "medium"})
        if not page.get("internal_links"): actions.append({"action": "add_internal_links", "priority": "medium", "impact": "medium"})

        return actions

    def _recommend_meta(self, page: dict) -> dict:
        title = page.get("title", "")
        keyword = page.get("primary_keyword", title.split()[0] if title else "product")
        return {
            "title_template": f"{keyword.title()} - Best {{benefit}} | {{brand}}",
            "description_template": f"Discover {keyword} that {{benefit}}. {{social_proof}}. {{cta}}.",
            "h1_template": f"{{modifier}} {keyword.title()} for {{audience}}",
        }

    def _technical_checklist(self) -> list[dict]:
        return [
            {"item": "SSL certificate", "category": "security"},
            {"item": "Mobile responsive", "category": "mobile"},
            {"item": "Page speed < 3s", "category": "performance"},
            {"item": "XML sitemap", "category": "crawlability"},
            {"item": "Robots.txt", "category": "crawlability"},
            {"item": "Canonical tags", "category": "duplicate_content"},
            {"item": "Structured data", "category": "rich_results"},
            {"item": "Image alt text", "category": "accessibility"},
        ]

    def _seo_score(self, analysis: dict) -> float:
        score = 7.0
        audit = analysis.get("on_page_audit", {})
        score -= audit.get("high_severity", 0) * 1.5
        if audit.get("word_count", 0) > 1000: score += 1
        kw = analysis.get("keyword_analysis", {})
        if kw.get("total_keywords", 0) > 5: score += 1
        return max(min(round(score, 1), 10), 0)

    def _seo_reason(self, analysis: dict) -> str:
        audit = analysis.get("on_page_audit", {})
        kw = analysis.get("keyword_analysis", {})
        return f"{audit.get('issue_count', 0)} issues, {kw.get('total_keywords', 0)} keywords analyzed"

    @staticmethod
    def _keyword_type(keyword: str) -> str:
        words = len(keyword.split())
        if words <= 2: return "short_tail"
        if words <= 4: return "medium_tail"
        return "long_tail"
