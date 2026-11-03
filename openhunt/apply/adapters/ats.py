"""Company career sites (no login needed): Greenhouse, Lever, Ashby. The safest place to apply automatically."""

import re

from openhunt.apply.adapters.base import Adapter, settle


class Greenhouse(Adapter):
    name = "greenhouse"
    label = "Greenhouse"
    hosts = ("greenhouse.io",)
    paths = (r"/gh/",)

    def form_url(self, url: str) -> str:
        # Old embed links (…/embed/job_app?token=123&for=acme) → the hosted application page.
        m = re.search(r"greenhouse\.io/embed/job_app\?.*?for=([\w-]+).*?token=(\d+)|greenhouse\.io/embed/job_app\?.*?token=(\d+).*?for=([\w-]+)", url)
        if m:
            board, job = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            return f"https://job-boards.greenhouse.io/{board}/jobs/{job}"
        return url


class Lever(Adapter):
    name = "lever"
    label = "Lever"
    hosts = ("lever.co",)
    paths = (r"/lever/",)

    def form_url(self, url: str) -> str:
        url = url.split("?")[0].rstrip("/")
        return url if url.endswith("/apply") else url + "/apply"


class Ashby(Adapter):
    name = "ashby"
    label = "Ashby"
    hosts = ("ashbyhq.com",)
    paths = (r"/ashby/",)
    button_groups = True  # yes/no questions are buttons

    def form_url(self, url: str) -> str:
        url = url.split("?")[0].rstrip("/")
        return url if url.endswith("/application") else url + "/application"

    async def open(self, page, url: str):
        await page.goto(self.form_url(url), wait_until="domcontentloaded")
        await settle(page, 2000)  # the form is drawn by JavaScript
        return (await self.state(page)) or page
