# Superdesign Reference Mockups

Design references for the fulfillment / Building-board work. These are design INTENT, not drop-in code.

## Files

| File | Type | Maps to |
|------|------|---------|
| `building_delivery_board.html` | Light-mode Superdesign mockup | Building board + Delivery board layout, assignee initials filter and badges, the Finalize Build Completion modal, the Finalize Site Installation modal |
| `installation_completion.html` | Light-mode Superdesign mockup | Future Delivery and Installation cert flow: the Installation Completion Report modal (site checklist, SE sign-off, document upload, Complete and Certify Installation) |

## How to use these

The two HTML files are LIGHT mode (Plus Jakarta Sans, Tailwind CDN). They show layout, component structure, the 5-dot stage tracker, initials badges, and modal shapes. They are NOT drop-in code.

Rule: translate design intent into the dark token system documented in [../README.md](../README.md). Do not copy the light-mode Tailwind.

## Screen mapping detail

- **building_delivery_board.html**
  - Building Pipeline column: Ready for Handoff and Active Fabrication groupings. Partly built already (Building board rebuild S2 / Layout B S5b).
  - Assignee initials filter and per-card initials badges.
  - Finalize Build Completion modal: design intent for the component-rows redesign (fixed CPU / RAM / GPU / HDD / SSD rows in the QA capture form, S6b / S6c).
  - Finalize Site Installation modal: lighter delivery-side modal. Overlaps the installation_completion.html intent below.

- **installation_completion.html**
  - Installation Completion Report modal: site setup checklist, SE sign-off, signed-document upload, Complete and Certify Installation.
  - Drives the future installation / deployment cert flow. This is a separate, lighter cert than the shipped build cert (F3/S6) and is not built yet.
