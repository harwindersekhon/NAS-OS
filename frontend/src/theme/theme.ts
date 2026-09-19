import { createTheme, type MantineColorsTuple } from "@mantine/core";

import { brandAccent, fontFamily } from "./tokens";

// Anchors: index 6 resolves to brandAccent.light (Mantine's light primaryShade),
// index 8 to brandAccent.dark (its dark primaryShade). The rest interpolate —
// used only for hover/subtle backgrounds, not the primary interactive colour.
const brand: MantineColorsTuple = [
  "#f1effc",
  "#e1ddf7",
  "#c3baf0",
  "#a596e8",
  "#8b7be3",
  "#7666dd",
  brandAccent.light,
  "#3f3291",
  brandAccent.dark,
  "#241c54",
];

export const theme = createTheme({
  fontFamily: fontFamily.sans,
  fontFamilyMonospace: fontFamily.mono,
  primaryColor: "brand",
  primaryShade: { light: 6, dark: 8 },
  defaultRadius: "sm",
  radius: {
    xs: "2px",
    sm: "3px",
    md: "5px",
    lg: "8px",
    xl: "12px",
  },
  colors: { brand },
  headings: {
    fontWeight: "600",
  },
});
