import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Where did my money go?",
  description:
    "Every rupee between what you expected and what actually arrived — which parts are normal, and the one thing you need to act on.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
