import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "cineSense Phase 1A",
  description: "Exact movie-title lookup with transparent provenance.",
};


export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

