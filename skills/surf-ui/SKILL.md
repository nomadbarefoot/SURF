---
name: surf-ui
description: Operate and test real browser interfaces with navigation, snapshots, clicks, typing, keys, selection, hover, viewport changes, console logs, screenshots, downloads, and network capture. Use for end-to-end UI work and rendered interaction.
---

# SURF UI

Work from observed page state and keep each interaction verifiable.

1. Create a session and navigate to the target.
2. Take a `browser_snapshot` before choosing selectors or handles.
3. Perform one clear action with `browser_click`, `browser_type`, `browser_press_key`, `browser_select_option`, or `browser_hover`.
4. Wait for the expected condition, then snapshot or inspect console/network evidence.
5. Use `browser_resize` and screenshots for responsive checks.
6. Close the session after the scenario.

Prefer stable handles from the latest snapshot. Re-snapshot after navigation or large DOM changes. Report the tested scenario, observed result, and any console, network, visual, or challenge evidence. Use `surf-web` or `surf-browse` for tasks that do not need UI mutation.
