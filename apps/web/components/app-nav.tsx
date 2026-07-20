"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

const links = [
  { href: "/", label: "Exact Lookup" },
  { href: "/discover", label: "Discover Movies" },
];

export function AppNav() {
  const pathname = usePathname();
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    // Read theme from localStorage or document on mount
    const stored = localStorage.getItem("cinesense-theme");
    if (stored === "light") {
      setTheme("light");
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      setTheme("dark");
      document.documentElement.setAttribute("data-theme", "dark");
    }
  }, []);

  function toggleTheme() {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    document.documentElement.setAttribute("data-theme", nextTheme);
    localStorage.setItem("cinesense-theme", nextTheme);
  }

  return (
    <nav style={styles.nav} aria-label="Primary">
      <div style={styles.inner}>
        <p style={styles.brand}>cineSense</p>
        <div style={styles.links}>
          {links.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className="interactive"
                style={{
                  ...styles.link,
                  ...(active ? styles.linkActive : null),
                }}
              >
                {link.label}
              </Link>
            );
          })}

          <button
            type="button"
            onClick={toggleTheme}
            className="interactive"
            style={styles.themeToggle}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </div>
      </div>
    </nav>
  );
}

const styles: Record<string, CSSProperties> = {
  nav: {
    maxWidth: 1024,
    margin: "0 auto 20px",
  },
  inner: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "center",
    flexWrap: "wrap",
    borderRadius: 24,
    padding: "16px 20px",
    background: "var(--panel)",
    border: "1px solid var(--line)",
    boxShadow: "var(--shadow)",
    backdropFilter: "blur(12px)",
  },
  brand: {
    margin: 0,
    color: "var(--accent)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    fontSize: 12,
    fontWeight: 700,
  },
  links: {
    display: "flex",
    gap: 10,
    flexWrap: "wrap",
    alignItems: "center",
  },
  link: {
    textDecoration: "none",
    color: "var(--text)",
    padding: "10px 16px",
    borderRadius: 999,
    border: "1px solid transparent",
    background: "var(--surface)",
    fontSize: 14,
  },
  linkActive: {
    background: "var(--accent)",
    color: "#fff",
    boxShadow: "0 4px 12px var(--accent-soft)",
  },
  themeToggle: {
    background: "var(--surface)",
    border: "1px solid var(--line)",
    color: "var(--text)",
    width: 36,
    height: 36,
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    fontSize: 16,
    marginLeft: 8,
  }
};
