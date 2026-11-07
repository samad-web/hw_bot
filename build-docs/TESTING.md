# TESTING

Strategy: pure functions (validation, backoff, state, parsing) are unit-tested with `pytest`. Anything touching Playwright is tested against mocks and saved fixtures, never against the live site. No test ever places a real order.

## Results (2026-11-07)

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
