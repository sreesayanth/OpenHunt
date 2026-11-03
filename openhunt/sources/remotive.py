"""Remotive public API: remote jobs worldwide. Only used when the user wants remote work."""

from datetime import datetime

import httpx

from openhunt.sources.base import Query, RawJob

API = "https://remotive.com/api/remote-jobs"


class RemotiveSource:
    name = "remotive"

    async def search(self, query: Query) -> list[RawJob]:
        if not query.remote:
            return []
        jobs: list[RawJob] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for title in query.titles:
                resp = await client.get(API, params={"search": title, "limit": 50})
                resp.raise_for_status()
                # Remotive's search already matches the job text; the ranker judges relevance.
                for j in resp.json().get("jobs", []):
                    posted = j.get("publication_date")
                    jobs.append(
                        RawJob(
                            source=self.name,
                            url=j["url"],
                            title=j["title"],
                            company=j.get("company_name", ""),
                            location=j.get("candidate_required_location", "Remote"),
                            remote=True,
                            salary=j.get("salary", "") or "",
                            description=j.get("description", ""),
                            posted_at=datetime.fromisoformat(posted) if posted else None,
                        )
                    )
        return jobs
