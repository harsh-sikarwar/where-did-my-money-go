import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import "./globals.css";

/**
 * Manrope carries the whole product. Its 300 weight is unusually open for a grotesk,
 * which is what makes the calm Expected/Received figures read as deliberately quiet
 * next to a 700-weight gap rather than merely smaller.
 */
const manrope = Manrope({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
  variable: "--font-manrope",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Where did my money go?",
  description:
    "Every rupee between what you expected and what actually arrived — which parts are normal, and the one thing you need to act on.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={manrope.variable}>
      <body className="bg-[var(--color-ground)] font-sans text-[var(--color-ink)] antialiased">
        {children}
      </body>
    </html>
  );
}
