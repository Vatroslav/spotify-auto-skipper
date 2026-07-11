---
name: dashboard-layout
description: Layout math for dashboard/container CSS changes in cloud/app/static/css/style.css. Use before changing container widths, paddings, breakpoints, column layouts, or anything about the chart-open side-by-side view. The layout numbers are interdependent - two past changes burned multiple deploy cycles by guessing instead of computing.
---

# Dashboard layout changes

Layout widths in this app are a small system of interdependent numbers. Changing one without recomputing the others has twice led to iterate-on-prod loops (settings width v3.4.0-17→20 ended in a revert; chart width v3.16.8 ate two wrong snapshots on a single 16px padding mistake). **Compute the expected widths on paper first, then change the CSS once.**

## The numbers (as of v3.16.8)

| Value | Where | Meaning |
|---|---|---|
| `640px` | `.container` max-width | Base column width, all pages |
| `16px` | `.container` padding (mobile) | Default padding |
| `24px` | `.container` padding at `min-width: 768px` | Desktop padding — **not 16!** |
| `88px` | `.container` margin-left at desktop | Room for the sidebar nav |
| `592px` | `.dashboard-main` / `.dashboard-side` flex-basis when chart open | = 640 − 2×24 (closed content width on desktop) |
| `1248px` | `.container-wide.chart-open` max-width | = 592 + 16 gap + 592 + 2×24 padding |
| `1360px` | side-by-side media query gate | 1248 container + 88 sidebar ≈ 1336 needed; below this the chart stacks under Now Playing at the same 592px |

These are documented in the comment above `@media (min-width: 1360px)` in `style.css` — **update that comment whenever any of them changes.**

## The trap that cost two snapshots

Content width on desktop is `640 − 48 = 592`, not `640 − 32 = 608`, because the desktop (`≥768px`) media query overrides padding to 24px. Any "match the closed width" computation must use the padding of the breakpoint it applies at. When a column is even ~16px off, the visible symptom is the layout subtly shifting when a panel opens/closes — if you see that, re-derive the arithmetic, don't nudge pixels.

## Rules

- **Invariant:** opening/closing a panel (chart, etc.) must not change the width of the Now Playing column. Verify this explicitly.
- Chart bars are elastic (`flex: 1`, `min-width: 0`, `max-width: 64px`) — they absorb width changes; don't give them fixed widths.
- Mobile (< 768px) stays untouched by desktop-layout work: single column, 16px padding.
- Changing `.container` max-width (640) or desktop padding (24) cascades into 592, 1248, and 1360 — recompute all of them and the CSS comment in the same change.
- Verify per breakpoint before deploying: mobile (~375px), desktop stacked (768–1359px), side-by-side (≥1360px), each in both chart-open and chart-closed states. Docker isn't in the local PATH, so rendering verification happens on the VPS via test deploys of the branch — the paper math is what keeps that to ONE test deploy instead of three.
