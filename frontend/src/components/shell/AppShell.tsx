import type { ReactNode } from "react";
import styles from "../../styles/surface.module.css";

/**
 * Top-level page shell. Paints the layered Sonoma-style radial gradient
 * backdrop and provides the max-width content column.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.appBackdrop}>
      <main
        style={{
          maxWidth: 1400,
          margin: "0 auto",
          padding: "var(--space-8) var(--space-6)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-6)",
        }}
      >
        {children}
      </main>
    </div>
  );
}
