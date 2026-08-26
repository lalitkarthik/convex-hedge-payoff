import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "convex-hedge — NIFTY payoff",
  description: "A Sensibull-shaped payoff calculator for NIFTY index options.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
