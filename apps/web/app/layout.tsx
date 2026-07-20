import "./globals.css";
import type { Metadata } from "next";

import { AppNav } from "@/components/app-nav";

export const metadata: Metadata = {
  title: "cineSense",
  description: "Transparent movie lookup and structured discovery with deterministic backend ranking.",
};


export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                var theme = localStorage.getItem('cinesense-theme');
                if (theme === 'light') {
                  document.documentElement.setAttribute('data-theme', 'light');
                } else {
                  document.documentElement.setAttribute('data-theme', 'dark');
                }
              } catch (e) {}
            `,
          }}
        />
      </head>
      <body>
        <AppNav />
        {children}
      </body>
    </html>
  );
}
