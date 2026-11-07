# TESTING

Strategy: pure functions (validation, backoff, state, parsing) are unit-tested with `pytest`. Anything touching Playwright is tested against saved HTML fixtures captured from a real session via `main.py --capture`, never against the live site. No test ever places a real order.

Per-feature results are appended below as each feature is built.

## Results
_(empty — nothing built yet)_
