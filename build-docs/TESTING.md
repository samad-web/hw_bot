# TESTING

Strategy: pure functions (validation, backoff, state, parsing) are unit-tested with `pytest`. Anything touching Playwright is tested against mocks and saved fixtures, never against the live site. No test ever places a real order.

## Results (2026-11-07)

### 2026-11-14 F17 watchlist web — 91 passed
- `tests/test_watchlist.py` (13): ac1 seed from config.yaml, ac2 save + derived ids, ac3 invalid link/fields/empty rejected and old file kept, delete/blank rows, ac4 CSRF, ac5 escaping, ac6 bot reload valid/invalid/unchanged, ac7 Blinkit-only.
- `test_max_orders_total_must_equal_sum_of_max_orders` replaced by `..._is_a_backstop_not_a_restatement`: the rule changed by design (F17), not to make a test pass.
- HTTP smoke test on a local server: GET 200, cross-site POST 403, bad link 400 with reason, good POST 303 + file written.

### 2026-11-14 alerts: outage log-only + popup guard — 78 passed
- `test_navigation_failure_skips_check_and_alerts_relay_once` now asserts NO "RELAY OFFLINE" message (requirement changed by user), recovery still once.
- Autouse `_no_desktop_popups` fixture: verified no MessageBox process after a full run.

### 2026-11-14 alert debounce — 78 passed
- `test_navigation_failure_skips_check_and_alerts_relay_once` (now with a fake clock), `test_short_relay_blip_sends_no_message`, `test_page_error_warns_once_per_streak_not_per_blip`, `test_login_error_warns_immediately_once`.

36 tests passing across all features:

- `tests/test_state.py` (4 tests):
  - `test_load_nonexistent_returns_defaults`: First-run missing state.json returns default values.
  - `test_save_and_load_roundtrip`: Atomic save via tmp file + `os.fsync` + `os.replace`.
  - `test_corrupt_state_is_quarantined_and_flagged`: Corrupt state quarantined to `state.corrupt.<ts>`, ordering blocked.
  - `test_can_order_rules`: Enforces single-order lock, detects uncertain crash state (`payment_attempt_started and not order_placed`), blocks invalid total orders.

- `tests/test_config.py` (6 tests):
  - `test_load_valid_config`: Validates complete YAML into frozen dataclass hierarchy.
  - `test_polling_interval_clamped_to_floor`: Enforces 20-second hard floor.
  - `test_invalid_mode_rejected`: Fails fast on invalid mode string.
  - `test_mode_c_requires_positive_spend_ceilings`: Blocks Mode C startup if `max_order_value_inr` or `max_price_inr` are unset/zero.
  - `test_max_orders_total_must_be_one`: Enforces single-order restriction.
  - `test_env_overlay_reads_telegram_and_evolution`: Overlays `.env` secrets without saving in YAML.

- `tests/test_checker.py` (9 tests):
  - `test_missing_selector_returns_error`: Missing selectors yield ERROR, never guesses.
  - `test_login_wall_detected`: Detects expired session or login wall.
  - `test_location_drift_detected`: Verifies header delivery label/pincode before stock check.
  - `test_wrong_product_detected`: Gated by identity assertion against product title.
  - `test_in_stock_detected`: Matches active Add button.
  - `test_in_stock_quantity_stepper`: Matches quantity stepper indicator.
  - `test_out_of_stock_detected`: Matches Notify Me / Out of stock indicator.
  - `test_add_button_disabled_is_out_of_stock`: Disabled Add button treated as out-of-stock.
  - `test_unknown_layout_detected`: Reports ERROR(unknown_layout) if neither CTA matches.

- `tests/test_notifier.py` (5 tests):
  - `test_command_pause_and_resume`: Remote `/pause` and `/resume` state mutation.
  - `test_command_status`: Remote `/status` output with lock, WhatsApp and mode status.
  - `test_command_mode_switch`: Remote `/mode` validation and lock awareness.
  - `test_command_otp`: Card OTP relay format validation (4-8 digits).
  - `test_poll_commands_ignores_unauthorized_chat`: Ignores unauthorized chat IDs silently.

- `tests/test_executor.py` (6 tests):
  - `test_validate_cart_price_ceiling`: Unit price ceiling check.
  - `test_validate_cart_total_order_ceiling`: Total payable ceiling check.
  - `test_validate_cart_extra_items_rejected`: Refuses checkout if foreign items in cart.
  - `test_validate_cart_address_mismatch`: Validates delivery address on checkout screen.
  - `test_checkout_dry_run_never_pays`: Dry run halts before pay click, never sets attempt lock.
  - `test_checkout_lock_written_before_pay`: Crucial lock sequence test: asserts `payment_attempt_started=True` was written and fsynced to disk *before* pay click is executed.

- `tests/test_hardening.py` (3 tests):
  - `test_next_delay_schedule`: Escalating backoff (60, 120, 300, 900, 900s).
  - `test_calculate_interval_floor`: Jitter never drops below 20s floor across 1000 samples.
  - `test_save_failure_capture_and_pruning`: Captures HTML + screenshot and caps at 20 directories.

- `tests/test_main.py` (3 tests):
  - `test_parse_args_defaults`: CLI defaults.
  - `test_parse_args_overrides`: CLI overrides.
  - `test_main_exits_if_uncertain_state`: Halts on startup and alerts if prior checkout crashed.

### 2026-11-07 — Full-build review pass

47 tests pass (`python -m pytest -q`). Suite grew from 36 after the review found
defects the existing tests did not cover.

Defects found and fixed, each with a regression test:

| Defect | Severity | Test |
|---|---|---|
| Loop skipped `goto()` once `page.url` matched the target, so it re-read a stale DOM and could never see a restock | **blocker** | `test_loop_refetches_the_page_every_iteration` |
| `state.save` ignored `--state`; lock read from one file, written to another | **blocker** | `test_loop_writes_state_to_the_path_given_by_state_flag` |
| compose bind-mounted `state.json` as a single file; `os.replace` fails EBUSY → crash loop in Docker | **blocker** | manual (compose now mounts `./data`) |
| Lock written before the `pay_button` selector was validated, bricking the bot on a config error | high | `test_missing_pay_button_does_not_write_the_lock` |
| Config placeholders silently disabled the product-identity gate in checker and executor | high | `test_mode_b_rejects_placeholder_product_name`, `..._pincode`, `..._requires_core_selectors`, `test_mode_c_requires_checkout_selectors` |
| Stale in-memory state after a failed checkout would allow a blind retry | high | `test_uncertain_state_blocks_a_second_checkout` |
| No notification channel was required; a silent bot could spend money | medium | `test_requires_at_least_one_notification_channel` |
| `/otp` persisted the OTP to `state.json`, against the F6 security rule | medium | `test_command_otp` |
| Blindness detection and healthcheck ping were specified but absent | medium | `test_is_possibly_blind_only_after_the_window`, `test_ping_healthcheck_skips_empty_url` |

Not fixed, tracked as gaps: order-history check before retry (F6 AC6/7) and the
card OTP relay (spec req 13). Both need real Blinkit HTML that does not exist yet.

### 2026-11-07 — F8 multi-product

59 tests pass. Suite grew 49 → 59: a shared `tests/conftest.py` now builds Config
in one place, and `tests/test_multi_product.py` covers the F8 acceptance criteria.

| F8 AC | Test |
|---|---|
| 1 — only the restocked target is ordered, others keep being watched | `test_ac1_cycle_visits_every_outstanding_target`, `test_ac1_a_bought_target_is_dropped_from_the_watch_list` |
| 2 — exits once every target is bought, restart does not re-order | `test_ac2_bot_exits_once_every_target_is_bought` |
| 3 — per-product lock survives a crash | `test_record_order_marks_bought_and_clears_the_in_flight_flag`, `test_legacy_state_with_an_order_is_flagged_not_guessed` |
| 4 — in-flight payment blocks EVERY target | `test_ac4_in_flight_payment_blocks_every_target`, `test_can_order_rules` |
| 5 — spend cap blocks the crossing order before any lock write | `test_spend_cap_blocks_the_order_that_would_cross_it` |
| 6 — cycle interval scales with target count | `test_polling_floor_scales_with_target_count` |
| 7 — duplicate prid rejected | `test_duplicate_product_id_rejected` |
| 8 — max_orders_total must equal product count | `test_max_orders_total_must_equal_product_count` |

Also verified: Mode A's mute window is per product and persisted
(`test_mode_a_mute_is_per_product_and_survives_restart`).

**Live smoke run** (real Chromium, real Blinkit, Mode A, dry-run): the bot
started, fetched the K5 Blazer page, and the checker read the location bar as
"Delivery in 12 minutes", correctly returning `location_drift` rather than
guessing at stock. Confirms `product_title`, `header_address` and the hydration
wait work against the live site. The address subtitle is empty until a session
with a saved address exists, which is the expected pre-login state.

## 2026-11-12 — F10 home relay + F11 web COD checkout + repeat orders
- Unit: 75 pass. New: browser_options env; nav failure skips stale DOM + one relay alert; COD dry run never pays; lock before Pay; COD disabled / Pay Now disabled / wrong address / no confirmation (lock stays) / missing selector (no lock); one unit per order; caps; grand-total parsing; repeat orders to max_orders; single-record state migration; config max_orders_total = sum.
- Live gate (VPS via phone): egress = home Airtel IP; product page 200; `/checkout` payment iframe loads headful.
- Live practice (`--practice 774429`, VPS via phone), failures found and fixed:
  1. "Proceed" absent when the address is pre-chosen -> made optional.
  2. empty_cart gave up before steppers hydrated -> loop until no lines.
  3. Address hidden in mobile layout -> read text_content, not inner_text.
  4. COD option loads after the iframe -> wait_for it.
  5. Pay Now matched 11, then 2 (hidden copy) -> `Zpayments__Button ... :visible` = 1; must be enabled after COD.
  Final: PRACTICE PASSED (cart Rs 185, address verified, COD selected, Pay Now enabled, not clicked, cart emptied).
- NOT verified: post-Pay confirmation (no real order placed, user's choice). Failure mode is safe: lock stays, bot stops ordering and alerts.
