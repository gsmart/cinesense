"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CSSProperties } from "react";

const links = [
  { href: "/", label: "Exact Lookup" },
  { href: "/discover", label: "Discover Movies" },
];

export function AppNav() {
  const pathname = usePathname();

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
                style={{
                  ...styles.link,
                  ...(active ? styles.linkActive : null),
                }}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

const styles: Record<string, CSSProperties> = {
  nav: {
    maxWidth: 980,
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
    background: "rgba(255, 252, 245, 0.78)",
    border: "1px solid rgba(141,46,22,0.14)",
    boxShadow: "0 16px 40px rgba(86, 42, 16, 0.08)",
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
  },
  link: {
    textDecoration: "none",
    color: "var(--text)",
    padding: "10px 16px",
    borderRadius: 999,
    border: "1px solid rgba(31, 26, 23, 0.08)",
    background: "rgba(255,255,255,0.55)",
  },
  linkActive: {
    background: "linear-gradient(135deg, #8d2e16 0%, #c85f33 100%)",
    color: "#fff8f0",
    borderColor: "transparent",
  },
};
