"""F17 car-list editor + bot reload. Names map to the acceptance criteria in
build-docs/features/17-watchlist-web.md."""
import argparse
import json
from pathlib import Path

import pytest

import config
import main
import watchlist_web as web
from tests.test_config import create_minimal_config

SUPRA = {"store": "blinkit", "name": "Hot Wheels Supra",
         "url": "https://blinkit.com/prn/x/prid/1454828", "max_price_inr": "659", "max_orders": "3"}
ZEPTO = {"store": "zepto", "name": "Hot Wheels Skyline",
         "url": "https://www.zeptonow.com/pn/hot-wheels-skyline/pvid/abc-123", "max_price_inr": "299",
         "max_orders": "1"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    cfg = create_minimal_config(tmp_path / "config.yaml",
                                safety={"max_orders_total": 6, "max_total_spend_inr": 3000.0})
    monkeypatch.setattr(web, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(web, "WATCHLIST_PATH", str(tmp_path / "data" / "watchlist.json"))
    return tmp_path


def _form(*rows, delete=()):
    form = {}
    for i, r in enumerate(rows):
        form.update({f"{k}_{i}": [str(v)] for k, v in r.items()})
    form.update({f"delete_{i}": ["on"] for i in delete})
    return form


def test_ac1_page_shows_config_yaml_cars_before_first_save(project):
    rows, cfg, err = web.load_rows()
    assert err is None and rows[0]["url"].endswith("/prid/12345")
    assert "Nissan Skyline" in web.render(rows, cfg)


def test_ac2_valid_list_is_saved_with_derived_ids(project):
    assert web.save_rows(web.rows_from_form(_form(SUPRA, ZEPTO))) is None
    saved = json.loads(Path(web.WATCHLIST_PATH).read_text())["products"]
    assert [p["store"] for p in saved] == ["blinkit", "zepto"]
    cfg = web._load()
    assert cfg.products[0].id == "1454828" and cfg.products[1].id.startswith("zepto:")


def test_ac3_invalid_link_is_rejected_and_old_list_kept(project):
    web.save_rows(web.rows_from_form(_form(SUPRA)))
    before = Path(web.WATCHLIST_PATH).read_text()
    bad = dict(ZEPTO, url="https://evil.example.com/pvid/1")
    err = web.save_rows(web.rows_from_form(_form(SUPRA, bad)))
    assert err and "zepto link" in err
    assert Path(web.WATCHLIST_PATH).read_text() == before


@pytest.mark.parametrize("field,value,needle", [
    ("max_price_inr", "abc", "non-numeric"),
    ("url", "http://blinkit.com/prn/x/prid/1", "https"),
    ("store", "amazon", "unknown store"),
    ("max_orders", "0", "max_orders must be >= 1"),
])
def test_ac3_bad_fields_rejected(project, field, value, needle):
    assert needle in web.save_rows(web.rows_from_form(_form(dict(SUPRA, **{field: value}))))


def test_empty_list_rejected(project):
    assert "empty" in web.save_rows([])


def test_delete_and_blank_new_row_are_dropped(project):
    blank = {"store": "blinkit", "name": "", "url": "", "max_price_inr": "", "max_orders": "1"}
    rows = web.rows_from_form(_form(SUPRA, ZEPTO, blank, delete=(1,)))
    assert [r["name"] for r in rows] == ["Hot Wheels Supra"]


def test_ac4_cross_site_post_is_refused():
    assert web.same_origin({"Host": "100.1.2.3:8080", "Origin": "http://100.1.2.3:8080"})
    assert not web.same_origin({"Host": "100.1.2.3:8080", "Origin": "https://evil.example"})
    assert not web.same_origin({"Host": "100.1.2.3:8080"})


def test_ac5_names_are_escaped_in_the_page(project):
    page = web.render([dict(SUPRA, name='<script>alert(1)</script>')], None)
    assert "<script>alert" not in page and "&lt;script&gt;" in page


def _args(tmp_path, cfg_file):
    return argparse.Namespace(config=str(cfg_file), env=str(tmp_path / ".env"),
                              state=str(tmp_path / "data" / "state.json"), mode=None)


def test_ac6_bot_reloads_a_valid_list_and_keeps_old_on_invalid(project, monkeypatch):
    sent = []
    monkeypatch.setattr(main.notifier, "send", lambda t, c, priority=False: sent.append(t))
    args = _args(project, web.CONFIG_PATH)
    old = config.load_config(args.config, env_path=args.env, check_channels=False)
    web.save_rows(web.rows_from_form(_form(SUPRA, ZEPTO)))
    new, seen = main.reload_watchlist(old, args, None)
    assert [p.id for p in new.products][0] == "1454828" and "Car list updated" in sent[-1]
    assert main.reload_watchlist(new, args, seen) == (new, seen), "unchanged file: no reload, no message"

    Path(web.WATCHLIST_PATH).write_text('{"products": [{"store": "zepto", "url": "x"}]}')
    kept, _ = main.reload_watchlist(new, args, None)
    assert kept is new and "REJECTED" in sent[-1]


def test_ac7_only_blinkit_cars_are_checked_for_now(project):
    web.save_rows(web.rows_from_form(_form(SUPRA, ZEPTO)))
    cfg = web._load()
    assert [p.store for p in main.watched(cfg, {})] == ["blinkit"]
