# Apple-Inspired Web Design Guide

This workspace may generate web pages, dashboards, landing pages, or docs UIs.
When a user asks for a premium Apple-like web design, follow this guide.

Source of inspiration:
- VoltAgent `awesome-design-md`
- Apple profile: `design-md/apple/DESIGN.md`

Scope:
- Apply this guide to web UI work only.
- Do not force these styles onto CLI output, Telegram chat text, or operational scripts.
- Prefer the existing product structure and copy over decorative redesign.

## Design Intent

- Premium, quiet, product-first presentation
- Strong hierarchy through whitespace, not clutter
- Minimal chrome, restrained color, deliberate motion
- Interface should feel precise and expensive, not playful or trendy

## Visual System

- Alternate immersive dark sections and clean light sections
- Use neutral surfaces first
- Reserve saturated blue for primary interactive states only
- Avoid busy gradients, textured backgrounds, glass overload, and card spam

Recommended tokens:

```css
:root {
  --bg-dark: #000000;
  --bg-light: #f5f5f7;
  --text-dark: #1d1d1f;
  --text-light: #ffffff;
  --accent: #0071e3;
  --accent-dark-bg: #2997ff;
  --link-light: #0066cc;
  --surface-dark: #272729;
  --shadow-soft: 0 3px 30px rgba(0, 0, 0, 0.22);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-pill: 999px;
  --content-max: 980px;
}
```

## Typography

- Use `SF Pro Display` and `SF Pro Text` when legally available
- Safe fallback stack: `"SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif`
- Large headlines should be tight, bold, and short
- Body copy should stay compact and calm

Recommended scale:
- Hero title: `56px / 1.07 / 600`
- Section title: `40px / 1.1 / 600`
- Card title: `28px / 1.14 / 400`
- Body: `17px / 1.47 / 400`
- Caption/link: `14px / 1.43 / 400`

## Layout Rules

- Prefer full-width sections with centered content blocks
- Keep content containers around `980px` max width
- Use large vertical spacing between sections
- Let one idea dominate each section
- Avoid dense multi-column layouts unless the content truly requires comparison

## Components

Buttons:
- Primary CTA: blue fill, white text, soft radius
- Secondary CTA: dark fill on light surfaces, white text
- Learn-more CTA: pill outline or text link, never louder than the main CTA

Cards:
- Use cards sparingly
- Prefer flat surfaces with subtle radius
- If elevation is needed, use one soft shadow style only

Navigation:
- Keep compact, clear, and quiet
- Sticky nav can use dark translucent background with blur if the page benefits from it

Media:
- Large product image or hero visual first
- Avoid decorative illustrations unless the page concept requires them

## Motion

- Use short fade/slide reveals and restrained stagger
- Motion should support hierarchy, not call attention to itself
- Avoid bouncy easing, parallax overload, and constant looping animation

## Do

- Use strong section rhythm with dark/light alternation
- Keep copy short and declarative
- Make the primary CTA obvious
- Design for desktop first, then tighten carefully for mobile

## Do Not

- Do not use purple accents
- Do not fill the page with generic cards
- Do not mix many accent colors
- Do not add heavy borders everywhere
- Do not use noisy shadows or exaggerated glassmorphism

## Prompting Guidance For Codex

When implementing UI in this workspace:
- Preserve existing functionality
- Change layout, spacing, typography, and surfaces before inventing new interactions
- Keep designs intentional and restrained
- If assets are missing, use abstract placeholders or clean typographic heroes instead of low-quality stock-like visuals
