"""AnalyticsIntelligence — real web analytics and conversion optimization.

Processes analytics data (GA4-style) to produce actionable insights:
  - Funnel analysis with drop-off detection
  - Conversion rate optimization recommendations
  - Traffic source ROI analysis
  - Session behavior analysis
  - Page performance scoring
  - Revenue attribution by channel
"""
from __future__ import annotations

import math
from typing import Any


class AnalyticsIntelligence:
    """Real analytics algorithms for e-commerce conversion optimization."""

    def analyze_funnel(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze conversion funnel to find drop-off points.

        Input: [{"step": "visit", "users": 10000}, {"step": "product_view", "users": 4000}, ...]
        """
        if not steps or len(steps) < 2:
            return {"error": "Need at least 2 funnel steps"}

        analyzed = []
        worst_drop = {"step": "", "drop_pct": 0}

        for i, step in enumerate(steps):
            users = int(step.get("users", step.get("count", step.get("sessions", 0))))
            entry = {
                "step": step.get("step", step.get("name", f"step_{i}")),
                "users": users,
            }

            if i > 0:
                prev_users = int(steps[i-1].get("users", steps[i-1].get("count", 1)))
                if prev_users > 0:
                    rate = users / prev_users * 100
                    drop = 100 - rate
                    entry["conversion_rate"] = round(rate, 2)
                    entry["drop_off_pct"] = round(drop, 2)
                    entry["lost_users"] = prev_users - users

                    if drop > worst_drop["drop_pct"]:
                        worst_drop = {"step": entry["step"], "drop_pct": round(drop, 2), "lost_users": prev_users - users}

            analyzed.append(entry)

        total_users = int(steps[0].get("users", steps[0].get("count", 1)))
        final_users = int(steps[-1].get("users", steps[-1].get("count", 0)))
        overall_rate = final_users / max(total_users, 1) * 100

        return {
            "steps": analyzed,
            "overall_conversion": round(overall_rate, 2),
            "worst_drop_off": worst_drop,
            "total_entered": total_users,
            "total_converted": final_users,
            "total_lost": total_users - final_users,
            "recommendations": self._funnel_recommendations(analyzed, worst_drop),
        }

    def analyze_traffic_sources(self, sources: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze traffic source performance and ROI.

        Input: [{"source": "google", "sessions": 5000, "conversions": 100, "revenue": 3000, "cost": 500}, ...]
        """
        if not sources:
            return {"error": "No traffic source data"}

        analyzed = []
        for src in sources:
            name = src.get("source", src.get("channel", "unknown"))
            sessions = int(src.get("sessions", src.get("visitors", 0)))
            conversions = int(src.get("conversions", src.get("purchases", 0)))
            revenue = float(src.get("revenue", 0))
            cost = float(src.get("cost", src.get("spend", 0)))

            conv_rate = conversions / max(sessions, 1) * 100
            roas = revenue / max(cost, 0.01) if cost > 0 else 0
            cpa = cost / max(conversions, 1) if conversions > 0 else cost
            revenue_per_session = revenue / max(sessions, 1)

            analyzed.append({
                "source": name,
                "sessions": sessions,
                "conversions": conversions,
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "conversion_rate": round(conv_rate, 2),
                "roas": round(roas, 2),
                "cpa": round(cpa, 2),
                "revenue_per_session": round(revenue_per_session, 4),
                "profit": round(revenue - cost, 2),
                "grade": self._source_grade(roas, conv_rate),
            })

        analyzed.sort(key=lambda s: -s["revenue_per_session"])

        total_revenue = sum(s["revenue"] for s in analyzed)
        total_cost = sum(s["cost"] for s in analyzed)

        return {
            "sources": analyzed,
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_revenue - total_cost, 2),
            "overall_roas": round(total_revenue / max(total_cost, 0.01), 2),
            "best_source": analyzed[0]["source"] if analyzed else None,
            "worst_source": analyzed[-1]["source"] if analyzed else None,
            "recommendations": self._source_recommendations(analyzed),
        }

    def analyze_pages(self, pages: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze page performance — bounce rate, time on page, exit rate.

        Input: [{"url": "/products/earbuds", "views": 5000, "bounces": 2000, "exits": 1500, "avg_time_seconds": 45}, ...]
        """
        if not pages:
            return {"error": "No page data"}

        analyzed = []
        for page in pages:
            url = page.get("url", page.get("page", "unknown"))
            views = int(page.get("views", page.get("pageviews", 0)))
            bounces = int(page.get("bounces", 0))
            exits = int(page.get("exits", 0))
            avg_time = float(page.get("avg_time_seconds", page.get("time_on_page", 0)))
            conversions = int(page.get("conversions", page.get("add_to_cart", 0)))

            bounce_rate = bounces / max(views, 1) * 100
            exit_rate = exits / max(views, 1) * 100
            conv_rate = conversions / max(views, 1) * 100

            # Page score (0-100)
            score = 50
            if bounce_rate < 30: score += 15
            elif bounce_rate > 60: score -= 15
            if avg_time > 60: score += 10
            elif avg_time < 15: score -= 10
            if conv_rate > 3: score += 15
            elif conv_rate > 1: score += 5
            if exit_rate < 20: score += 10
            elif exit_rate > 50: score -= 10
            score = max(0, min(100, score))

            analyzed.append({
                "url": url,
                "views": views,
                "bounce_rate": round(bounce_rate, 1),
                "exit_rate": round(exit_rate, 1),
                "avg_time_seconds": round(avg_time, 1),
                "conversion_rate": round(conv_rate, 2),
                "score": score,
                "issues": self._page_issues(bounce_rate, exit_rate, avg_time, conv_rate),
            })

        analyzed.sort(key=lambda p: p["score"])  # Worst first

        return {
            "pages": analyzed,
            "total_pages": len(analyzed),
            "avg_bounce_rate": round(sum(p["bounce_rate"] for p in analyzed) / max(len(analyzed), 1), 1),
            "worst_pages": analyzed[:3],
            "best_pages": analyzed[-3:],
        }

    def session_analysis(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyze user session behavior patterns.

        Input: [{"session_id": "s1", "pages_viewed": 5, "duration_seconds": 180, "converted": True, "device": "mobile"}, ...]
        """
        if not sessions:
            return {"error": "No session data"}

        total = len(sessions)
        converted = sum(1 for s in sessions if s.get("converted"))
        pages = [int(s.get("pages_viewed", s.get("page_count", 0))) for s in sessions]
        durations = [float(s.get("duration_seconds", s.get("duration", 0))) for s in sessions]

        # Device split
        devices: dict[str, dict] = {}
        for s in sessions:
            dev = s.get("device", "unknown")
            if dev not in devices:
                devices[dev] = {"sessions": 0, "converted": 0}
            devices[dev]["sessions"] += 1
            if s.get("converted"):
                devices[dev]["converted"] += 1

        device_rates = {dev: {"sessions": d["sessions"],
                              "conversion_rate": round(d["converted"] / max(d["sessions"], 1) * 100, 2)}
                        for dev, d in devices.items()}

        # Converted vs non-converted behavior
        conv_pages = [int(s.get("pages_viewed", 0)) for s in sessions if s.get("converted")]
        non_conv_pages = [int(s.get("pages_viewed", 0)) for s in sessions if not s.get("converted")]

        return {
            "total_sessions": total,
            "conversion_rate": round(converted / max(total, 1) * 100, 2),
            "avg_pages_viewed": round(sum(pages) / max(len(pages), 1), 1),
            "avg_duration_seconds": round(sum(durations) / max(len(durations), 1), 1),
            "device_breakdown": device_rates,
            "converted_avg_pages": round(sum(conv_pages) / max(len(conv_pages), 1), 1) if conv_pages else 0,
            "non_converted_avg_pages": round(sum(non_conv_pages) / max(len(non_conv_pages), 1), 1) if non_conv_pages else 0,
            "insight": self._session_insight(conv_pages, non_conv_pages, device_rates),
        }

    def revenue_attribution(self, touchpoints: list[dict[str, Any]]) -> dict[str, Any]:
        """Simple last-touch revenue attribution by channel.

        Input: [{"channel": "google", "revenue": 500}, {"channel": "facebook", "revenue": 300}, ...]
        """
        if not touchpoints:
            return {"error": "No touchpoint data"}

        channels: dict[str, float] = {}
        for t in touchpoints:
            ch = t.get("channel", t.get("source", "direct"))
            rev = float(t.get("revenue", 0))
            channels[ch] = channels.get(ch, 0) + rev

        total = sum(channels.values())
        attribution = [
            {"channel": ch, "revenue": round(rev, 2), "share_pct": round(rev / max(total, 1) * 100, 1)}
            for ch, rev in sorted(channels.items(), key=lambda x: -x[1])
        ]

        return {
            "total_revenue": round(total, 2),
            "attribution": attribution,
            "top_channel": attribution[0]["channel"] if attribution else None,
            "concentration": round(attribution[0]["share_pct"], 1) if attribution else 0,
            "diversification": "risky" if attribution and attribution[0]["share_pct"] > 60 else "healthy",
        }

    # --- Recommendations ---

    @staticmethod
    def _funnel_recommendations(steps: list, worst: dict) -> list[dict[str, str]]:
        recs = []
        if worst.get("drop_pct", 0) > 50:
            recs.append({"priority": "high", "action": f"Fix {worst['step']} — {worst['drop_pct']}% drop-off losing {worst.get('lost_users', 0)} users"})
        if len(steps) >= 2 and steps[1].get("drop_off_pct", 0) > 40:
            recs.append({"priority": "high", "action": "Improve product pages — high bounce after landing"})
        if len(steps) >= 3 and steps[-1].get("drop_off_pct", 0) > 30:
            recs.append({"priority": "medium", "action": "Optimize checkout — losing users at final step"})
        if not recs:
            recs.append({"priority": "low", "action": "Funnel looks healthy — focus on increasing top-of-funnel traffic"})
        return recs

    @staticmethod
    def _source_recommendations(sources: list) -> list[dict[str, str]]:
        recs = []
        for s in sources:
            if s["roas"] > 3 and s["cost"] > 0:
                recs.append({"priority": "medium", "action": f"Scale {s['source']} — ROAS {s['roas']}x, increase budget 20%"})
            elif s["roas"] < 1 and s["cost"] > 0:
                recs.append({"priority": "high", "action": f"Pause or fix {s['source']} — ROAS {s['roas']}x losing money"})
        if not recs:
            recs.append({"priority": "low", "action": "All sources performing — continue monitoring"})
        return recs[:3]

    @staticmethod
    def _source_grade(roas: float, conv_rate: float) -> str:
        if roas >= 4 and conv_rate >= 3: return "A"
        if roas >= 2 and conv_rate >= 1.5: return "B"
        if roas >= 1: return "C"
        return "D"

    @staticmethod
    def _page_issues(bounce: float, exit: float, time: float, conv: float) -> list[str]:
        issues = []
        if bounce > 60: issues.append("High bounce rate — improve above-fold content")
        if time < 15: issues.append("Very short time on page — content not engaging")
        if conv < 1: issues.append("Low conversion — improve CTA and product presentation")
        if exit > 50: issues.append("High exit rate — add related products or next-step CTA")
        return issues

    @staticmethod
    def _session_insight(conv_pages: list, non_conv: list, devices: dict) -> str:
        insights = []
        if conv_pages and non_conv:
            avg_c = sum(conv_pages) / len(conv_pages)
            avg_n = sum(non_conv) / len(non_conv)
            if avg_c > avg_n * 1.5:
                insights.append(f"Converters view {avg_c:.0f} pages vs {avg_n:.0f} — encourage deeper browsing")

        for dev, data in devices.items():
            if data["conversion_rate"] < 1 and data["sessions"] > 10:
                insights.append(f"{dev} conversion only {data['conversion_rate']}% — optimize {dev} experience")

        return "; ".join(insights) if insights else "Session patterns look normal"
