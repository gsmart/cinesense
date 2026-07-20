"use client";

import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";

export function CollapsiblePanel({ title, children, defaultExpanded = false, headerColor }: { title: string, children: ReactNode, defaultExpanded?: boolean, headerColor?: string }) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <article style={styles.panel}>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="interactive"
        style={{ ...styles.button, color: headerColor || "inherit" }}
        aria-expanded={expanded}
      >
        <span>{title}</span>
        <span style={{ ...styles.icon, transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}>
          ▼
        </span>
      </button>
      <div
        style={{
          ...styles.contentWrapper,
          gridTemplateRows: expanded ? "1fr" : "0fr",
          opacity: expanded ? 1 : 0,
        }}
      >
        <div style={styles.contentInner}>
          <div style={styles.content}>
            {children}
          </div>
        </div>
      </div>
    </article>
  );
}

const styles: Record<string, CSSProperties> = {
  panel: {
    border: "1px solid var(--line)",
    borderRadius: 16,
    background: "var(--surface)",
    overflow: "hidden",
    marginBottom: 8,
  },
  button: {
    width: "100%",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "16px 20px",
    background: "transparent",
    border: "none",
    color: "var(--text)",
    fontSize: 16,
    fontWeight: 600,
    cursor: "pointer",
    textAlign: "left",
  },
  icon: {
    fontSize: 14,
    transition: "transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  },
  contentWrapper: {
    display: "grid",
    transition: "grid-template-rows 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
  },
  contentInner: {
    overflow: "hidden",
  },
  content: {
    padding: "0 20px 20px",
    borderTop: "1px solid var(--line)",
    marginTop: 4,
    paddingTop: 16,
  }
};
