/**
 * NAS-OS visual identity: an instrument-panel reading, not a SaaS dashboard.
 * Chrome stays quiet graphite/steel; the only saturated colour is functional
 * — either the one brand accent (interactive elements) or a status hue
 * (health/state). Status hues are fixed across light/dark by design (they
 * read as the same signal everywhere), everything else themes.
 */

export const statusColor = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;

export type StatusColor = keyof typeof statusColor;

export const neutral = {
  light: {
    canvas: "#eef0f3",
    surface: "#ffffff",
    surfaceRaised: "#f5f6f8",
    border: "#dce0e6",
    textPrimary: "#1a1f27",
    textSecondary: "#5b6472",
  },
  dark: {
    canvas: "#10141a",
    surface: "#1a1f27",
    surfaceRaised: "#222833",
    border: "#2e3542",
    textPrimary: "#e8ecf1",
    textSecondary: "#8b96a5",
  },
} as const;

/** Validated (dataviz skill) against both surfaces above; distinct from statusColor. */
export const brandAccent = {
  light: "#4a3aa7",
  dark: "#9085e9",
} as const;

/** Two-hue sparkline pair for Dashboard's small-multiple CPU/mem charts —
 * "second sequential context takes the next categorical slot's hue". */
export const chartLine = {
  cpu: { light: "#2a78d6", dark: "#3987e5" },
  mem: { light: "#eb6834", dark: "#d95926" },
} as const;

export const fontFamily = {
  sans: '"IBM Plex Sans", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
} as const;
