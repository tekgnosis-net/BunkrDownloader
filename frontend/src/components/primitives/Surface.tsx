import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import styles from "../../styles/surface.module.css";

type Variant = "card" | "cardLg" | "rail" | "inset";

interface SurfaceProps extends HTMLAttributes<HTMLDivElement> {
  variant?: Variant;
  as?: "div" | "section" | "article";
  children?: ReactNode;
}

/**
 * Liquid-glass surface shell. All the vibrancy/blur/border logic lives in
 * ``surface.module.css``; this component just applies the right class set
 * and forwards rest-props. Choose ``variant`` to pick padding + shadow
 * intensity; omit for the default card.
 */
export const Surface = forwardRef<HTMLDivElement, SurfaceProps>(
  ({ variant = "card", as: Component = "div", className, children, ...rest }, ref) => (
    <Component
      ref={ref as never}
      className={clsx(styles.surface, styles[variant], className)}
      {...rest}
    >
      {children}
    </Component>
  ),
);
Surface.displayName = "Surface";
