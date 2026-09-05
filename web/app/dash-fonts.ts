/**
 * Fonts for the dashboard rebuild only. The original one-page product carries
 * Manrope (see `layout.tsx`); the dashboard is a full repaint and uses the
 * three families the mockup's inline styles actually reference — Plus
 * Jakarta Sans for body copy, Newsreader for headings, IBM Plex Mono for
 * every figure, id and timestamp. (The mockup's own `<link>` import pulls
 * Manrope/Instrument Serif/JetBrains Mono instead — leftover boilerplate
 * from the design tool's shared template that none of its inline styles
 * actually name. We use what the styles say, not the broken import.)
 */

import { IBM_Plex_Mono, Newsreader, Plus_Jakarta_Sans } from "next/font/google";

export const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-plus-jakarta",
  display: "swap",
});

export const newsreader = Newsreader({
  subsets: ["latin"],
  style: ["normal", "italic"],
  weight: ["400"],
  variable: "--font-newsreader",
  display: "swap",
});

export const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const dashFontVariables = `${plusJakarta.variable} ${newsreader.variable} ${ibmPlexMono.variable}`;
