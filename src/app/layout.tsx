import type { Metadata } from "next";
import { JetBrains_Mono, Space_Grotesk } from "next/font/google";

import "./globals.css";

export const metadata: Metadata = {
  title: "Recoup — Recovery Console",
  description:
    "Autonomous, money-safe revenue recovery: diagnose why a payment failed, act within hard constraints, and prove every step.",
};

/*
 * Two typefaces, both self-hosted by next/font at build time — no request leaves
 * the browser at runtime, so the original local-first constraint still holds.
 *
 * Space Grotesk carries the display and body text: a geometric grotesque with
 * enough character to front a landing page while staying quiet enough to read at
 * length. JetBrains Mono carries every technical column — audit rows, amounts,
 * state names — where digits must line up and a zero must never be mistaken for
 * an O.
 */
const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-space-grotesk",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`h-full ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-full bg-console-bg text-console-text antialiased">{children}</body>
    </html>
  );
}
