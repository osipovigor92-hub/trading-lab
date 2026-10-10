---
name: Trading Lab
description: Graphite workspace for following crypto activity and checking manual decisions
colors:
  primary: "#55cee9"
  background: "#101418"
  panel: "#191e24"
  control: "#20272e"
  border: "#343d46"
  text: "#edf3fa"
  muted: "#a7b3be"
  rising: "#59d5a1"
  falling: "#f1848b"
  chart-fast: "#4bd0f5"
  chart-slow: "#a78bcc"
  chart-vwap: "#e9bc68"
typography:
  headline:
    fontFamily: 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.025em"
  title:
    fontFamily: 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.3
  body:
    fontFamily: 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "14px"
    lineHeight: 1.6
  label:
    fontFamily: 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "12px"
    lineHeight: 1.6
rounded:
  badge: "4px"
  control: "5px"
  panel: "8px"
spacing:
  small: "8px"
  compact: "12px"
  mobile-panel: "14px"
  gutter: "15px"
  panel: "16px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#08151b"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  button-secondary:
    backgroundColor: "#17212c"
    textColor: "#d9e9f8"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    height: "42px"
  input-search:
    backgroundColor: "{colors.control}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "9px 11px"
    height: "42px"
  navigation:
    textColor: "#b7c7da"
    padding: "10px 15px"
    height: "64px"
  alert-count:
    backgroundColor: "{colors.primary}"
    textColor: "#071b1f"
    rounded: "{rounded.badge}"
    padding: "0 4px"
    height: "17px"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
---

# Design System: Trading Lab

<!-- Extracted from the final CSS cascade and synthetic preview captures on 2026-10-10. Root's bounded visual review passed at 1280, 390 and 320px on all four pages. -->

## Overview

**Creative North Star: "Graphite trading workspace"**

The approved concept is a dark working surface built around legible data, restrained cyan actions and clear selected states. Flat panels and fine dividers contain dense measurements without ornamental elevation. Green and rose indicate direction; muted text carries context and unavailable states.

The implemented identity is shared by all four pages. A compact header keeps navigation quiet, and the screener's selected coin remains recognizable across its watch entry, table row and detail panel. Numbers change in place. The visual system makes observation and manual action easy to distinguish.

**Key Characteristics:**

- Graphite backgrounds with slightly lighter flat panels.
- Cyan actions, active navigation and activity emphasis.
- Direction color accompanied by numbers or setup text.
- Compact data typography with tabular numbers.
- Persistent selection and restrained freshness labels.

## Colors

The frontmatter records the final cascade: `screener.css` overrides the global palette declared by `style.css` and is loaded on every page.

Primary cyan identifies actions, focus and activity emphasis. Rising green and falling rose express observed direction. They do not grade safety or profitability. Graphite background, panel, control and border tones establish containment; near-white text and muted text establish reading priority. The chart uses its own fast EMA, slow EMA and VWAP colors, named in the legend.

**The Direction Rule.** Use direction color with a signed value or an explicit setup label; color alone does not explain the observation.

## Typography

The interface requests Inter and falls back to Segoe UI and system faces. No font file is bundled by this panel. Headings use a compact sans hierarchy; paragraphs use comfortable line height, while tables and metrics use tabular numbers.

The main screener heading is 28px; other page headings are 27px. Panel titles are 17px and detail group labels 12–13px. Base body text is 14px, table text is 12px on the standard desktop screener, and supporting chart/measurement labels are often 10–12px. At mobile widths the main heading becomes 25px and supporting chart and setup text grows to 11px. These are observed roles, not a decorative display scale.

## Layout

The shell caps content at 1900px with 24px desktop side padding and a 64px header. The screener follows the pinned watch/table/detail arrangement: the watchlist and table form the left workspace, observation events sit directly beneath them, and the selected-coin detail occupies the right column. Standard desktop widths reserve 200px for the watchlist and 330px for detail; at 1600px and above these become 220px and 370px. The center table absorbs the remaining width.

At 1200px and below the detail moves under the watch/table region and uses a two-column internal layout. At 650px and below the screener stacks its panels: watchlist, results, observations and detail. The table scrolls within its own container; the page must not acquire horizontal overflow. Mobile watch entries form two columns. At 760px and below four fixed bottom-navigation items replace desktop tabs, and page padding reserves space for the navigation and safe area.

Desktop panels use 16px internal padding, 15px grid gutters and fine one-pixel boundaries. Mobile panels use 14px padding and 12px vertical gaps. Table headers stay visible inside their scrolling region. The left workspace has its own grid so the tall detail column does not push the observation feed down.

## Elevation & Depth

Depth comes from tonal layering and borders. Panels, selected rows and navigation states have no decorative box shadow. The chart rests on a darker field inside its panel. Focus uses a two-pixel cyan outline with three-pixel offset; this is an interaction cue, not ambient glow. Navigation transitions take 150ms and are disabled with reduced-motion preferences.

## Shapes

Panels use gently rounded eight-pixel corners. Controls, chart frames and watch entries use five-pixel corners; count badges use four pixels. Navigation tabs have a flat bottom underline instead of a rounded enclosing pill. Horizontal dividers separate measurements and observation rows. Progress tracks are thin four-pixel lines.

## Components

### Buttons and fields

Primary actions have a solid cyan background, dark text and a five-pixel radius. Secondary actions use a dark fill and restrained border. Standard controls have a 42px minimum height; primary/secondary buttons and inputs/selects become 44px on mobile. Disabled buttons reduce opacity and expose the disabled state. Hover increases brightness; keyboard focus receives the shared visible outline.

### Navigation and counts

Desktop labels occupy the header with a cyan underline and stronger text for the active page. Mobile navigation has four labeled icons and a subdued selected background. Alert counts use compact badges and represent fresh events, not the retained history total.

### Panels and watch entries

Flat bordered panels contain one task or evidence group. Watch entries keep their symbol, change and setup information together; the selected entry uses a lighter graphite fill. Star and watch actions expose pressed state. Empty watchlists give the star action as the next step.

### Screener table and selected detail

Rows preserve their symbol identity while values update. The selected row has a tonal highlight. The star indicates observation independently of selection. Activity is numeric and cyan; setup text names momentum, breakout, observation or waiting. Unavailable measurements use dashes.

The selected detail groups a price/chart area, current 1m setup, trend, volume/movement, liquidity, nearby levels and four-part activity breakdown. Reasons and risk calculation use disclosures. Chart timeframe controls change the visual candle series while the setup caption continues to state its 1m timeframe.

### Observations and PAPER

Observation rows show coin, time and event text. Current versus historical status is written explicitly; historical labels use muted text while the row and coin action remain. PAPER actions use existing button conventions and explicit virtual-position language. Missing server state and pending calculations show an explanation instead of a fabricated result.

## Do's and Don'ts

### Do:

- Do preserve the pinned graphite identity and compact data hierarchy.
- Do keep selected symbols and watched symbols visibly identifiable as values update.
- Do pair direction and freshness colors with text.
- Do keep dense tables scrollable inside their container on narrow screens.
- Do use visible focus and honor reduced-motion preferences.

### Don't:

- Don't turn an activity score into a profit claim or a command to trade.
- Don't erase an observation when its current-validity label expires.
- Don't imply that synthetic preview captures prove live exchange availability.
- Don't reintroduce removed website sections into the four-page navigation.
