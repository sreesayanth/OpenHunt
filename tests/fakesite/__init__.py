"""A tiny fake job site for login tests: login form, wrong password, PIN, app approval, CAPTCHA.

Emails choose the path: pin@x → email code, app@x → approve in app, captcha@x → CAPTCHA,
digits@x → one box per digit. Password "right" is correct; code "123456" is correct.
"""

import json
import threading
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

PAGES = Path(__file__).parent / "pages"
SUBMISSIONS: dict[str, list[dict]] = {}  # site → every application received
ROUTES = {
    "/gh/acme/jobs/1": "greenhouse.html",
    "/lever/acme/1": "lever_job.html",
    "/lever/acme/1/apply": "lever.html",
    "/ashby/acme/1/application": "ashby.html",
    "/careers/job/1": "generic_job.html",
    "/careers/apply/1": "generic_form.html",
    "/jobs/view/1/": "linkedin_job.html",
    "/jobs/view/2/": "linkedin_external.html",
    "/naukri/job-listings-1": "naukri_job.html",
}
THANKS = {
    "greenhouse": "<h1>Thank you for applying.</h1><p>Your application has been received.</p>",
    "lever": "<h3>Application submitted!</h3><p>Thanks for applying to Acme.</p>",
    "generic": "<h1>Thank you!</h1><p>We received your application.</p>",
}

PAGE = "<html><body>{}</body></html>"
LOGIN = """<h1>Sign in</h1>{error}
<form method=post action=/do-login>
<input id=username name=session_key type=text>
<input id=password name=session_password type=password>
<button type=submit aria-label="Sign in">Sign in</button></form>"""
PIN = """<h1>Let's do a quick verification</h1><p>We sent a code to your email.</p>{error}
<form method=post action=/pin><input id=input__email_verification_pin name=pin type=text>
<button id=email-pin-submit-button type=submit>Submit</button></form>"""
DIGITS = """<h1>Enter OTP</h1><form method=post action=/pin>
<input maxlength=1 name=d1 oninput="this.nextElementSibling&&this.nextElementSibling.focus()"><input maxlength=1 name=d2
 oninput="this.nextElementSibling.focus()"><input maxlength=1 name=d3 oninput="this.nextElementSibling.focus()"><input
 maxlength=1 name=d4 oninput="this.nextElementSibling.focus()"><input maxlength=1 name=d5 oninput="this.nextElementSibling.focus()"><input
 maxlength=1 name=d6><button type=submit>Verify</button></form>"""
APPROVE = """<h1>Check your LinkedIn app</h1><p>We sent a notification to your phone.</p>
<script>setTimeout(function(){location.href='/approved'}, 1500)</script>"""
CAPTCHA = """<h1>Let's do a quick security check</h1><iframe src="https://client-api.arkoselabs.com/x"></iframe>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, cookie=None, location=None, status=200):
        self.send_response(303 if location else status)
        if cookie:
            self.send_header("Set-Cookie", f"li_at={cookie}; Path=/")
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.format(body).encode())

    def _form(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("application/json"):
            return json.loads(body or b"{}")
        if ctype.startswith("multipart/form-data"):
            msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
            out: dict = {}
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                filename = part.get_filename()
                payload = part.get_payload(decode=True) or b""
                value = f"file:{filename}:{len(payload)}" if filename else payload.decode(errors="ignore")
                if name in out:  # checkbox groups send several values
                    out[name] = out[name] if isinstance(out[name], list) else [out[name]]
                    out[name].append(value)
                else:
                    out[name] = value
            return out
        return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(body.decode()).items()}

    def _logged_in(self):
        return "li_at=ok" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ROUTES:
            return self._send((PAGES / ROUTES[path]).read_text().replace("<html><body>", "").replace("</body></html>", ""))
        if self.path.startswith("/login"):
            return self._send(LOGIN.format(error=""))
        if self.path.startswith("/feed"):
            if not self._logged_in():
                return self._send("", location="/login")
            return self._send("<h1>Your feed</h1>")
        if self.path.startswith("/approved"):
            return self._send("", cookie="ok", location="/feed/")
        if self.path.startswith("/weird"):
            return self._send("<h1>Something unexpected</h1>")
        return self._send("not found", status=404)

    def do_POST(self):
        f = self._form()
        if self.path.startswith("/submit/"):
            site = self.path.split("/")[2]
            SUBMISSIONS.setdefault(site, []).append(f)
            return self._send(THANKS.get(site, "ok"))
        if self.path == "/do-login":
            if f.get("session_password") != "right":
                return self._send(LOGIN.format(error='<div id=error-for-password>Wrong password. Try again.</div>'))
            email = f.get("session_key", "")
            if email.startswith("pin"):
                return self._send(PIN.format(error=""))
            if email.startswith("digits"):
                return self._send(DIGITS)
            if email.startswith("app"):
                return self._send(APPROVE)
            if email.startswith("captcha"):
                return self._send(CAPTCHA)
            return self._send("", cookie="ok", location="/feed/")
        if self.path == "/pin":
            code = f.get("pin") or "".join(f.get(f"d{i}", "") for i in range(1, 7))
            if code == "123456":
                return self._send("", cookie="ok", location="/feed/")
            return self._send(PIN.format(error="<p>That code didn't work.</p>"))
        return self._send("not found", status=404)


def start() -> tuple[str, ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server
