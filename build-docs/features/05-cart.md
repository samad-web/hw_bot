# F5 — Cart automation (Mode B)

## Purpose
Between detecting a restock and a human reacting there are minutes, and the item may be gone. Mode B closes that gap: the bot secures the item in the cart at the correct address and the human only taps Pay. It is also the proving ground for every selector Mode C will reuse.

## Architecture
`executor.add_to_cart(page, cfg) -> CartResult`:
1. Alert first (F3), then click Add using `cfg.selectors.add_button`.
2. Wait for the quantity stepper / cart badge to confirm the click landed.
3. Set quantity to `product.quantity` if it is not already 1.
4. Open the cart, read back: item name, unit price, quantity, delivery address, total payable.
5. Return those values. Mode B stops here and alerts "Cart ready, pay now" with the read-back values in the message.

The read-back is the contract with F6: Mode C runs the identical function and then validates its return value. There is exactly one add-to-cart code path, so Mode B genuinely tests Mode C's first half.

## Impact map
| Touches | What breaks |
|---|---|
| `config.yaml: selectors` | add button, stepper, cart open, cart line items, address line, total |
| F2 | consumes its IN_STOCK verdict; a false positive here starts a real cart action |
| F6 | reuses this function wholesale — a bug here is a bug in the paid path |
| F3 | the restock alert must already have been sent before the first click |
| Blinkit account cart | **real side effect**: this mutates your actual live cart |

## Edge cases and failure modes
- Item sells out between detection and the Add click → alert "missed it", clear nothing, return to watching.
- Add click succeeds but no stepper appears → treat as uncertain: re-read the cart before any retry, never click Add twice blindly.
- Cart already contains other items → read all lines; the target item's line is identified by name, and the total used for validation is the **total payable**, which may include those other items. If the cart is not empty of unexpected items, Mode C aborts and alerts rather than paying for someone else's groceries.
- Quantity stepper overshoots (double click) → read back and correct down, or abort if it cannot be corrected.
- Address shown in the cart differs from the header → abort and alert. Cart address is authoritative.
- Minimum-order-value fee or surge fee pushes the total past the ceiling → that is F6's validation, but the read-back must expose fees separately enough to explain the alert.
- Popup/interstitial (coupon, rain delay, app-install nag) covering the button → dismiss known ones by selector, otherwise unknown-layout capture plus alert.

## Acceptance criteria
1. On an in-stock fixture, the add flow produces a `CartResult` with name, unit price, quantity, address and total populated.
2. Sold-out-on-click path returns a distinct "missed" result and sends the missed alert.
3. Quantity in the cart equals `product.quantity` after the flow, or the run aborts with a clear reason.
4. Cart containing an unexpected extra item → `CartResult` flags it, and Mode B's alert names it.
5. The restock alert is sent before any click (verified by call-order assertion in the test).
6. `--dry-run` in Mode B still adds to cart (that is the point of Mode B) but is clearly logged; Mode C's dry run stops before pay.
7. A missing add-button selector aborts with a named error instead of clicking something arbitrary.
