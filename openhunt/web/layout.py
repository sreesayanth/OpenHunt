"""Shared HTML shell for the wizard pages (no frontend build step needed)."""

from fastapi.responses import HTMLResponse

CSS = """
:root{--bg:#f7f7fb;--fg:#1c1c28;--muted:#6b6b80;--card:#fff;--line:#e3e3ec;--accent:#4f46e5;--accent-fg:#fff;--err:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#121218;--fg:#ececf3;--muted:#9a9ab0;--card:#1c1c26;--line:#2c2c3a;--accent:#818cf8;--accent-fg:#0b0b12;--err:#f97066}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:640px;margin:0 auto;padding:24px 16px 64px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
header b{font-size:18px}header small{color:var(--muted)}h1{font-size:26px;margin:0 0 8px}.lead{color:var(--muted);margin-top:0}
a{color:var(--accent)}code{background:var(--line);padding:1px 6px;border-radius:4px}
input,select{width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);font-size:16px;margin:8px 0}
button{padding:12px 18px;border:0;border-radius:10px;background:var(--accent);color:var(--accent-fg);font-size:16px;font-weight:600;cursor:pointer}
button.secondary{background:var(--line);color:var(--fg)}button.link{background:none;color:var(--muted);text-decoration:underline;padding:12px 0}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.row form{margin:0}
.steps li{margin:6px 0}.error{color:var(--err);font-weight:600}.muted{color:var(--muted)}
.big{display:block;text-align:center;padding:16px;border-radius:12px;background:var(--accent);color:var(--accent-fg);font-weight:700;text-decoration:none;margin:16px 0}
.big small{display:block;font-weight:400;opacity:.85}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:10px 0}
.card summary{cursor:pointer;font-weight:600}.qr{background:#fff;padding:16px;border-radius:12px;width:fit-content;margin:16px auto}
.qr svg{display:block;width:220px;height:220px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:16px 0}
.stats div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}.stats small{display:block;color:var(--muted)}
table{width:100%;border-collapse:collapse;margin-top:16px}td{border-top:1px solid var(--line);padding:10px 6px;vertical-align:top}
.pill{display:inline-block;min-width:36px;text-align:center;background:var(--accent);color:var(--accent-fg);border-radius:999px;padding:2px 8px;font-weight:700}
"""


def page(subtitle: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OpenHunt</title><style>{CSS}</style></head>
<body><main><header><b>🎯 OpenHunt</b><small>{subtitle}</small></header>{body}</main></body></html>""")
