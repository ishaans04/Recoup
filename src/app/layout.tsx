import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Recoup — Recovery Console",
  description:
    "Autonomous, money-safe revenue recovery: diagnose why a payment failed, act within hard constraints, and prove every step.",
};

/*
 * No web font is loaded. The console is a local-first operations surface that has
 * to render in a room with unreliable network, and a build-time font fetch is a
 * failure mode the design does not need. The system stack in globals.css is what
 * ships.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full bg-console-bg text-console-text antialiased">{children}</body>
    </html>
  );
}
