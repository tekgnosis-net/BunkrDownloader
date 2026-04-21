/**
 * Design tokens for the liquid-glass UI (macOS Sonoma / iOS 17 aesthetic).
 *
 * Most tokens are also emitted as CSS custom properties by ThemeProvider
 * so style modules can reference them without importing JS. The JS object
 * is the source of truth — keep the two in sync.
 */

export const tokens = {
  color: {
    // OKLCH gives predictable lightness steps across both modes. Accent
    // hue 250 ≈ blue; 25 ≈ red; 75 ≈ amber; 150 ≈ green.
    accent: {
      50:  "oklch(97% 0.03 250)",
      100: "oklch(93% 0.06 250)",
      200: "oklch(88% 0.09 250)",
      300: "oklch(80% 0.13 250)",
      400: "oklch(70% 0.18 250)",
      500: "oklch(62% 0.20 250)",
      600: "oklch(55% 0.21 250)",
      700: "oklch(48% 0.20 250)",
    },
    success: { 500: "oklch(68% 0.16 150)" },
    warning: { 500: "oklch(76% 0.15 75)" },
    danger:  { 500: "oklch(60% 0.22 25)" },
    // Per-mode "glass" surface tints. Semi-transparent so the backdrop
    // bleeds through when backdrop-filter is available, solid when not.
    glass: {
      light: {
        base:    "color-mix(in oklch, white 72%, oklch(95% 0.02 250) 28%)",
        elevate: "color-mix(in oklch, white 58%, oklch(92% 0.03 250) 42%)",
        border:  "oklch(92% 0.02 250 / 0.6)",
        ink:     "oklch(22% 0.02 250)",
        inkMute: "oklch(45% 0.01 250)",
      },
      dark: {
        base:    "color-mix(in oklch, oklch(18% 0.02 250) 72%, transparent 28%)",
        elevate: "color-mix(in oklch, oklch(22% 0.03 250) 65%, transparent 35%)",
        border:  "oklch(40% 0.03 250 / 0.35)",
        ink:     "oklch(96% 0.01 250)",
        inkMute: "oklch(70% 0.02 250)",
      },
    },
  },

  space: { 0: "0px", 1: "4px", 2: "8px", 3: "12px", 4: "16px", 6: "24px", 8: "32px", 12: "48px", 16: "64px" },

  radius: { xs: "6px", sm: "10px", md: "14px", lg: "16px", xl: "22px", pill: "999px" },

  font: {
    sans: `"Inter Variable", "Inter", "SF Pro Text", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`,
    mono: `"JetBrains Mono", "SF Mono", ui-monospace, Menlo, Consolas, monospace`,
    features: `"cv11", "ss01", "ss02", "tnum"`,
  },

  // Apple HIG-inspired type scale. The unit is px (vs rem) so pairing with
  // CSS math stays legible; Inter's variable weight axis lets us tune the
  // semantic weights without loading multiple files.
  type: {
    largeTitle: { size: 34, weight: 700, lh: 1.15, tracking: "-0.02em" },
    title1:     { size: 28, weight: 700, lh: 1.2,  tracking: "-0.015em" },
    title2:     { size: 22, weight: 600, lh: 1.25, tracking: "-0.01em" },
    headline:   { size: 17, weight: 600, lh: 1.3 },
    body:       { size: 15, weight: 400, lh: 1.45 },
    callout:    { size: 13, weight: 500, lh: 1.4 },
    caption:    { size: 12, weight: 400, lh: 1.35 },
    mono:       { size: 12.5, weight: 400, lh: 1.5 },
  },

  shadow: {
    // Layered: inset highlight + ambient + key. The long-throw soft shadow
    // is what gives Sonoma surfaces their "floating" feel.
    glassSm: `0 1px 0 0 rgb(255 255 255 / 0.06) inset, 0 1px 2px rgb(0 0 0 / 0.04), 0 8px 24px -12px rgb(0 0 0 / 0.18)`,
    glassMd: `0 1px 0 0 rgb(255 255 255 / 0.08) inset, 0 2px 4px rgb(0 0 0 / 0.05), 0 18px 48px -20px rgb(0 0 0 / 0.28)`,
    glassLg: `0 1px 0 0 rgb(255 255 255 / 0.10) inset, 0 4px 8px rgb(0 0 0 / 0.06), 0 32px 80px -30px rgb(0 0 0 / 0.38)`,
    focus:   `0 0 0 2px var(--ring)`,
  },

  blur: { sm: "8px", md: "18px", lg: "32px" },
  saturate: { vibrancy: 1.8 },

  motion: {
    easeOut: "cubic-bezier(0.2, 0.8, 0.2, 1)",
    durFast: 140,
    durBase: 200,
    durSlow: 340,
  },

  z: { base: 0, sticky: 20, modal: 40, toast: 60 },
} as const;

export type Tokens = typeof tokens;
export type ColorMode = "light" | "dark";
