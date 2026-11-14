"""Car-list editor (F17): a one-page form that edits data/watchlist.json.

Served only inside the Tailscale network (the container shares the tailscale
container's network and publishes no port), so there is no login: being on the
tailnet is the login. The bot re-reads the file between cycles.
Stdlib only. Validation is the bot's own (config.load_config), so the page can
never save a list the bot would refuse.
"""
from __future__ import annotations

import html
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
import state

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", "data/watchlist.json")
FIELDS = ("store", "name", "url", "max_price_inr", "max_orders")
MAX_BODY = 100_000


def _load(products_raw: list | None = None) -> config.Config:
    return config.load_config(CONFIG_PATH, env_path=os.devnull, watchlist_path=WATCHLIST_PATH,
                              products_raw=products_raw, check_channels=False)


def load_rows() -> tuple[list[dict], config.Config | None, str | None]:
    """Current car list (watchlist.json, else config.yaml), the config, or an error."""
    try:
        cfg = _load()
    except config.ConfigError as exc:
        return [], None, str(exc)
    return [{f: getattr(p, f) for f in FIELDS} for p in cfg.products], cfg, None


def rows_from_form(form: dict[str, list[str]]) -> list[dict]:
    """Rows named field_<i>; ticked delete_<i> and fully blank rows are dropped."""
    idx = sorted({int(k.rsplit("_", 1)[1]) for k in form
                  if k.rsplit("_", 1)[-1].isdigit() and k.rsplit("_", 1)[0] in FIELDS})
    rows = []
    for i in idx:
        row = {f: (form.get(f"{f}_{i}") or [""])[0].strip() for f in FIELDS}
        if f"delete_{i}" in form or not (row["url"] or row["name"]):
            continue
        rows.append(row)
    return rows


def save_rows(rows: list[dict]) -> str | None:
    """Validate with the bot's rules, then write atomically. Returns an error or None."""
    try:
        cfg = _load(products_raw=rows)
    except config.ConfigError as exc:
        return str(exc)
    Path(WATCHLIST_PATH).parent.mkdir(parents=True, exist_ok=True)
    state.save({}, WATCHLIST_PATH, products=[
        {"store": p.store, "name": p.name, "url": p.url,
         "max_price_inr": p.max_price_inr, "max_orders": p.max_orders} for p in cfg.products])
    return None


def same_origin(headers) -> bool:
    """CSRF guard: a POST must come from this page, not from another site the browser visited."""
    host = headers.get("Host", "")
    src = headers.get("Origin") or headers.get("Referer") or ""
    return bool(host) and urlparse(src).netloc == host


def _row_html(i: int, row: dict, new: bool = False) -> str:
    e = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    opts = "".join(f'<option value="{s}"{" selected" if row.get("store") == s else ""}>{s}</option>'
                   for s in config.STORES)
    title = "Add a car" if new else f"Car {i + 1}"
    delete = "" if new else (f'<label class="del"><input type="checkbox" name="delete_{i}"> '
                             f'Remove this car</label>')
    return f"""<fieldset><legend>{title}</legend>
<label>Store <select name="store_{i}">{opts}</select></label>
<label>Name (as shown in the app) <input name="name_{i}" value="{e(row.get('name', ''))}"></label>
<label>Link (Share button in the app) <input name="url_{i}" type="url" inputmode="url" value="{e(row.get('url', ''))}"></label>
<div class="pair"><label>Max price Rs <input name="max_price_inr_{i}" type="number" min="1" step="1" value="{e(row.get('max_price_inr', '') or '')}"></label>
<label>Orders <input name="max_orders_{i}" type="number" min="1" max="10" value="{e(row.get('max_orders', 1))}"></label></div>
{delete}</fieldset>"""


def render(rows: list[dict], cfg: config.Config | None, error: str | None = None,
           saved: bool = False) -> str:
    caps = ""
    if cfg:
        caps = (f"<p class=note>Fixed in config.yaml, not here: at most "
                f"{cfg.safety.max_orders_total} orders in total, Rs "
                f"{cfg.safety.max_total_spend_inr:.0f} total spend, Rs "
                f"{cfg.payment.max_order_value_inr:.0f} per order.</p>")
    msg = (f'<p class=err role=alert>Not saved: {html.escape(error)}</p>' if error else
           '<p class=ok role=status>Saved. The bot picks it up within a minute.</p>' if saved else "")
    body = "".join(_row_html(i, r) for i, r in enumerate(rows))
    body += _row_html(len(rows), {"store": "blinkit", "max_orders": 1}, new=True)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Hot Wheels car list</title>
<style>
body{{font:16px/1.4 system-ui,sans-serif;margin:0 auto;max-width:640px;padding:16px;background:#fff;color:#111}}
fieldset{{border:1px solid #ccc;border-radius:8px;margin:0 0 12px;padding:8px 12px}}
label{{display:block;margin:6px 0}} input,select{{display:block;width:100%;box-sizing:border-box;padding:8px;font:inherit}}
.pair{{display:flex;gap:8px}} .pair label{{flex:1}} .del input{{display:inline;width:auto}}
button{{font:inherit;padding:10px 20px}} .err{{color:#a00}} .ok{{color:#060}} .note{{color:#555;font-size:14px}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}} fieldset{{border-color:#444}}
.note{{color:#aaa}} .err{{color:#f77}} .ok{{color:#7d7}}}}
</style></head><body><h1>Hot Wheels car list</h1>{msg}
<p class=note>Zepto, Instamart and FirstCry cars are saved now and watched once phone app support is built.</p>
<form method=post action="/">{body}<button type=submit>Save</button></form>{caps}</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, text: str, location: str | None = None) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/":
            return self._send(404, "Not found")
        rows, cfg, err = load_rows()
        self._send(200, render(rows, cfg, err, saved="saved=1" in self.path))

    def do_POST(self) -> None:
        if not same_origin(self.headers):
            return self._send(403, "Forbidden: cross-site request")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, "Too large")
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
        rows = rows_from_form(form)
        err = save_rows(rows)
        if err:
            _, cfg, _ = load_rows()
            return self._send(400, render(rows, cfg, err))
        self._send(303, "", location="/?saved=1")


if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8080"))
    print(f"Car-list editor on http://{host}:{port}", flush=True)
    HTTPServer((host, port), Handler).serve_forever()
