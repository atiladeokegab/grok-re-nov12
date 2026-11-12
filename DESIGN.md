---
name: X-ray
description: Inspect property claims alongside their sources.
colors:
  bg: "#080a09"
  surface: "#141815"
  raised: "#202620"
  border: "#3f4940"
  ink: "#f2f5ee"
  muted: "#b4beb2"
  accent: "#b8ed81"
  on-accent: "#17240b"
  danger: "#ffb4a8"
  warning: "#efd18b"
  photo-shade: "#080a09e6"
  transparent: "transparent"
font:
  display: "'Jost', sans-serif"
  body: "'IBM Plex Sans', sans-serif"
type:
  caption: "13px"
  body: "16px"
  lead: "20px"
  heading: "28px"
  title: "44px"
  display: "64px"
weight:
  normal: "400"
  medium: "500"
  bold: "600"
leading:
  body: "1.5"
  heading: "1.05"
tracking:
  display: "-0.03em"
spacing:
  0: "0"
  1: "4px"
  2: "8px"
  3: "12px"
  4: "16px"
  5: "24px"
  6: "32px"
  7: "48px"
  8: "64px"
rounded:
  control: "6px"
  panel: "12px"
components:
  border-width: "1px"
  focus-width: "3px"
  control-height: "48px"
  content-width: "1440px"
  measure-body: "70ch"
  shadow-panel: "0 16px 48px rgba(0, 0, 0, 0.25)"
  duration-fast: "160ms"
---

# Design System: X-ray

## Overview

**Creative North Star: “The property dossier.”**

The interface gives a real property photograph room, then makes the evidence trail easy to follow. Claims, source records, retrieval times, and agents stay connected. Residential is the primary path; office property follows the same grammar as a secondary path.

Near-black surfaces support a focused projected demo and keep evidence legible. Pale green marks the main action and positive records; salmon marks disagreement, and amber marks unavailable evidence. The prototype label stays prominent whenever sample values appear.

**Key Characteristics:** source-linked photography; open evidence rows; restrained dividers; explicit uncertainty.

## Colors

The palette pairs dark neutral reading surfaces with one pale green action accent and two text-labelled status colors.

### Primary
- **Pale record green:** the main action and positive state. Green never serves as the only verdict cue.
- **Deep green ink:** legible foreground for the pale accent.

### Secondary
- **Record salmon:** disagreement and error copy.
- **Record amber:** unavailable evidence and uncertainty.

### Neutral
- **Night ground:** page background.
- **Evidence surface:** input and detail background.
- **Raised surface:** selected property type and active states.
- **Record border:** quiet separators and field outlines.
- **Warm white:** primary reading text.
- **Grey green:** secondary copy.
- **Photo shade:** dark caption scrim over the source image.
- **Transparent:** neutral border reset.

**The Named Verdict Rule.** Always pair status color with words and, where applicable, an icon.

## Typography

**Display Font:** Jost Medium (`starter/web/static/fonts/OFL-Jost.txt`).
**Body Font:** IBM Plex Sans Regular and Semibold (`starter/web/static/fonts/OFL-IBM-Plex-Sans.txt`).

Jost gives the short opening statement a human, firm shape. IBM Plex Sans keeps source details and controls easy to scan. Figures use tabular numerals for direct comparison.

### Hierarchy
- **Display** (500, 64px, 1.05, -0.03em): desktop opening headline.
- **Title** (500, 44px, 1.2): phone headline and major result title.
- **Heading** (500, 28px, 1.2): result section headings.
- **Lead** (400, 20px, 1.5): concise explanatory copy and comparison values.
- **Body** (400, 16px, 1.5): reading text and evidence details.
- **Caption** (400, 13px, 1.5): metadata and secondary controls; keep text at least 12px.

**The Record Rule.** Use tabular numerals when values are compared.

## Layout

The desktop opening uses a two-column composition: action and headline on the left, a full-panel source photograph with a shaded caption on the right. At widths up to 900px the photograph moves above the copy, with a 168px opening crop; results become a single column with findings before history. The content is capped at 1440px. The base spacing rhythm is 4, 8, 12, 16, 24, 32, 48, and 64px. Controls are 48px high.

## Elevation & Depth

The page is flat at rest. Depth comes from the source image, a dark photo-caption scrim, tonal surface changes, and thin dividers. A panel shadow token exists for elevated content but is not part of the current dossier. Hover background transitions use 160ms; reduced-motion preferences shorten motion and disable smooth scrolling.

## Shapes

Controls have gently rounded corners (6px); image and evidence panels use 12px corners. Dividers are one pixel. Keep the photograph rectangular and let its crop carry the visual interest.

## Components

### Buttons
- **Shape:** 6px corners and at least 48px height.
- **Primary:** pale green background and deep green text; starts a check.
- **Hover / Focus:** warm-white hover fill; visible 3px green focus outline with 4px offset.
- **Secondary:** evidence-surface background, warm-white text, and border.

### Property type selector
- Two adjacent native radio choices; selected choice uses the raised surface and pale green text.
- Preserve keyboard operation and the visible focus ring.

### Evidence rows
- Keep findings as open list rows separated by quiet rules, not equally weighted cards.
- Selecting a row brings its claim, cited evidence, reasoning, and source together.

### Inputs
- Evidence-surface fill, one-pixel border, warm-white text, 6px corners, and 48px height.
- Focus uses the shared visible green outline. Error copy uses salmon and a clear retry path.

### Property image
- Use the approved listing photograph with a source link in its caption. It supplies location context; it does not substantiate synthetic prototype findings.

## Do's and Don'ts

### Do:
- **Do** keep the listing source adjacent to the photograph.
- **Do** show a finding’s cited record and retrieval context alongside its claim.
- **Do** label sample values before presenting them.
- **Do** keep focus visible and honor reduced motion.

### Don't:
- **Don't** count unavailable evidence as a match.
- **Don't** call a discrepancy fraud or imagery AI-generated without evidence supporting that claim.
- **Don't** imply unsupported property changes or fabricate agent-call counts.
- **Don't** show Google tile imagery without visible attribution.
