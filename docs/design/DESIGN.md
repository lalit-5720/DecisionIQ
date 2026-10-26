---
name: DecisionIQ
colors:
  surface: '#0e1323'
  surface-dim: '#0e1323'
  surface-bright: '#34394a'
  surface-container-lowest: '#080d1d'
  surface-container-low: '#161b2b'
  surface-container: '#1a1f30'
  surface-container-high: '#25293a'
  surface-container-highest: '#2f3446'
  on-surface: '#dee1f9'
  on-surface-variant: '#bdc8d0'
  inverse-surface: '#dee1f9'
  inverse-on-surface: '#2b3041'
  outline: '#88929a'
  outline-variant: '#3e484f'
  surface-tint: '#7dd0ff'
  primary: '#7dd0ff'
  on-primary: '#00344a'
  primary-container: '#00a1da'
  on-primary-container: '#003348'
  inverse-primary: '#00658b'
  secondary: '#c7bfff'
  on-secondary: '#2c0e94'
  secondary-container: '#4330aa'
  on-secondary-container: '#b5abff'
  tertiary: '#45dfa4'
  on-tertiary: '#003825'
  tertiary-container: '#00ab78'
  on-tertiary-container: '#003624'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#c4e7ff'
  primary-fixed-dim: '#7dd0ff'
  on-primary-fixed: '#001e2d'
  on-primary-fixed-variant: '#004c6a'
  secondary-fixed: '#e5deff'
  secondary-fixed-dim: '#c7bfff'
  on-secondary-fixed: '#180065'
  on-secondary-fixed-variant: '#4330aa'
  tertiary-fixed: '#68fcbf'
  tertiary-fixed-dim: '#45dfa4'
  on-tertiary-fixed: '#002114'
  on-tertiary-fixed-variant: '#005137'
  background: '#0e1323'
  on-background: '#dee1f9'
  surface-variant: '#2f3446'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  title-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
  stat-lg:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.02em
  stat-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 26px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-lg: 1.5rem
  margin: 1rem
  margin-md: 1.5rem
  margin-lg: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
  space-2xl: 2rem
---

## Brand & Style

The design system embodies precision-driven business intelligence tailored for regional enterprise retail operations. It combines technical authority with clarity, allowing executive leadership and regional inventory planners to parse dense multi-store predictive telemetry at a glance.

The visual expression leans on modern technical enterprise aesthetics: high-contrast dark surfaces, crisp micro-borders, deep-indigo architectural containers, and focused luminous accents. Interfaces convey immediate operational confidence, eliminating decorative noise in favor of data density, real-time forecast trajectories, and actionable inventory health indicators.

## Colors

The palette establishes strict functional separation between canvas depth, structural surfaces, and semantic predictive signals:

- **Canvas & Backgrounds**: The base canvas is `#0B1020`. Structural vertical navigation anchors the interface in deep midnight navy (`#000A30`). Cards, metric tiles, and floating sheets rest on `#131A2E`.
- **Accents**: Primary focal points, active states, and analytical projections utilize electric cyan (`#00A1DA`). Secondary predictive models, cross-store correlation graphs, and AI recommendation nodes leverage luminous violet (`#8B7CF6`).
- **Semantic Indicators**:
  - Healthy / Growth / Target Exceeded: `#34D399`
  - Caution / Stock Threshold Warning: `#FBBF24`
  - High Risk / Stockout Imminent / Shrinkage Spike: `#F87171`
- **Text & Borders**: Primary readability is anchored by `#F3F6FF`. Sub-labels, metadata, axis ticks, and muted metrics use `#B7C0D8`. Architectural separation relies on a consistent 1px structural stroke in `#1E294B`.

## Typography

The type system is powered entirely by Inter to maximize legible density across charts, data grids, and high-frequency telemetry. 

- **Numeric & Metric Display**: All currency valuations (INR ₹), unit counts, and forecast percentages enforce tabular lining figures (`font-variant-numeric: tabular-nums`) to maintain visual alignment across stacked comparison rows.
- **Hierarchy Tiers**: Micro-labels (`label-sm`) utilize slight uppercase tracking to distinguish field descriptors from core metric values. Headlines preserve tight negative tracking to maintain compactness on dashboard header strips.

## Layout & Spacing

The layout utilizes a structured 12-column fluid grid system pinned against a fixed 260px primary navigation sidebar on desktop viewports. 

- **Density & Flow**: Grid spacing is calibrated for compact data density. Standard desktop panels deploy `1.5rem` outer canvas padding and `1rem` column gutters, allowing simultaneous rendering of multi-outlet predictive tiles, demand curves, and inventory risk tables without unnecessary scrolling.
- **Breakpoints & Adaptability**:
  - **Desktop (≥1280px)**: Persistent 260px navy sidebar, 12-column grid, modular multi-pane split.
  - **Tablet / Small Desktop (768px – 1279px)**: Collapsed icon-only navigation (72px), 8-column layout, metrics collapse into 2x2 grids.
  - **Mobile (<768px)**: Off-canvas navigation drawer, single-column stacked hierarchy with horizontal overflow carousels for fast KPI inspection.

## Elevation & Depth

Visual hierarchy is constructed through structural tonal layering accented with subtle luminous containment rather than heavy dropped shadows:

- **Base Layer (Level 0)**: Background canvas (`#0B1020`) and permanent navigation frame (`#000A30`).
- **Surface Layer (Level 1)**: Primary operational cards, data tables, and chart blocks (`#131A2E`) bordered by a crisp `1px solid #1E294B`. Shadows are minimal: `0 4px 12px rgba(0, 0, 0, 0.35)`.
- **Floating Layer (Level 2)**: Flyouts, filter dropdowns, and context tooltips (`#16203A`) layered with `0 8px 24px rgba(0, 0, 0, 0.5)` and a brighter contour border (`1px solid #283763`).
- **Interactive Focus / Glow**: Active predictive elements, AI insight callouts, and selected inventory nodes receive an internal or ambient cyan trace (`box-shadow: 0 0 16px rgba(0, 161, 218, 0.15)`).

## Shapes

The geometric framework balances functional modernism with a calibrated curvature:

- **Primary Cards & Containers**: Fixed at `12px` border-radius to preserve structural order across high-density multi-card dashboard arrays.
- **Interactive Controls**: Buttons, input fields, search filters, and segmented toggles use `8px` (`0.5rem`) for compact handoff.
- **Status Pills & Micro Badges**: Built with full pill radii (`9999px`) to create immediate visual differentiation against rectangular analytical containers.

## Components

### Buttons
- **Primary Action**: Background `#00A1DA`, label `#0B1020` (600 weight), height 36px, radius 8px, padding 0 16px. Hover shifts background to `#00B5F5` with subtle cyan glow.
- **Secondary Action**: Background transparent, border `1px solid #1E294B`, text `#F3F6FF`. Hover sets surface to `#1A233D` and border to `#283763`.
- **Destructive**: Background `rgba(248, 113, 113, 0.12)`, border `1px solid #F87171`, text `#F87171`.

### Status Badges & Pills
- Pill-shaped (`rounded-full`), height 22px, padding 2px 10px, typography `label-sm`.
- **Healthy**: Background `rgba(52, 211, 153, 0.12)`, text `#34D399`, border `1px solid rgba(52, 211, 153, 0.25)`.
- **Warning**: Background `rgba(251, 191, 36, 0.12)`, text `#FBBF24`, border `1px solid rgba(251, 191, 36, 0.25)`.
- **Risk / Alert**: Background `rgba(248, 113, 113, 0.12)`, text `#F87171`, border `1px solid rgba(248, 113, 113, 0.25)`.

### Cards & Metric Containers
- Surface `#131A2E`, radius `12px`, border `1px solid #1E294B`, padding `16px` to `20px`.
- Header houses category label (`label-sm`, `#B7C0D8`) and regional tag. Core stat rendered in `stat-lg` (`#F3F6FF`) followed by inline sparkline tracking 7-day velocity.

### Input Fields & Selectors
- Height 38px, radius 8px, background `#0E1528`, border `1px solid #1E294B`, text `#F3F6FF`, placeholder `#5B688A`.
- Active/Focus: Border `#00A1DA`, outline none, box-shadow `0 0 0 1px #00A1DA`.

### Data Grid & Inventory Lists
- Header: Background `#0E1528`, height 36px, typography `label-sm`, text `#B7C0D8`, bottom border `1px solid #1E294B`.
- Row: Height 48px, background `#131A2E`, bottom border `1px solid #18223D`. Hover state `#17213B`. Values adhere strictly to tabular numeric alignment with standard Indian numbering formatting (e.g., `₹12,45,000`).

### Sparklines & Predictive Visuals
- Path stroke 2px. Base line uses `#00A1DA`; projected/predicted trendlines transition into dashed `#8B7CF6` trajectories with a soft vertical gradient fill descending to opacity 0.