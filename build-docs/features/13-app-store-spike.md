# F13 — App-store feasibility spike

## Purpose
Prove, per store, that the app path works before building it. The Blinkit web assumption cost days; each answer below decides whether a store gets built, built alert-only, or dropped.

## Questions per app (Zepto, Instamart, FirstCry)
1. Does `adb shell am start -a android.intent.action.VIEW -d <share link>` open the product screen in the app?
2. Does a `uiautomator dump` of that screen show the title and a stock word ("Add", "Notify me", "Out of stock", "Coming soon"...)? Record exact texts.
3. Does an out-of-stock / coming-soon car still open by direct link (Blinkit hid them from search)?
4. Cart → checkout: is **Cash on Delivery** offered for this account and address? Stop before placing.
5. Any integrity / "unsupported device" / captcha screen? If yes, the store is dropped. No bypass.
6. Can the VPS reach adb on the phone through the existing Tailscale setup (userspace mode has no TUN device)?

## Prerequisites (user)
- Zepto, Instamart (Swiggy), FirstCry installed and logged in on the relay phone, address set.
- Developer options → USB debugging on; once, from the laptop over USB: `adb tcpip 5555`.
- Share links for one in-stock and one out-of-stock car per store.

## Output
Findings in `MEMORY.md`; per-store verdict (build / alert-only / drop) in `PLAN.md` §7.

## Acceptance criteria
- All 6 questions answered, dumps saved in `logs/app_capture/` per store.
- No order placed.
