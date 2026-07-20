"use client";

import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";

export function CollapsiblePanel({ title, children, defaultExpanded = false, headerColor }: { title: string, children: ReactNode, defaultExpanded?: boolean, headerColor?: string }) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <article style={styles.panel}>
      <button type="button" onClick={() => setExpanded(!expanded)} style={{ ...styles.button, color: headerColor || "inherit" }}>
        <span>{title}</span>
        <span style={styles.icon}>{expanded ? "−" : "+"}</span>
      </button>
      {expanded && <div style={styles.content}>{children}</div>}
    </article>
  );
}

const styles: Record<string, CSSProperties> = {
  panel: {
    border: "1px solid var(--line)",
    borderRadius: 16,
    background: "rgba(255, 255, 255, 0.03)",
    overflow: "hidden",
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
    fontSize: 20,
    fontWeight: 400,
    lineHeight: 1,
  },
  content: {
    padding: "0 20px 20px",
    borderTop: "1px solid var(--line)",
    marginTop: 4,
    paddingTop: 16,
  }
};
