import { forwardRef, type HTMLAttributes, type ReactNode, type Ref } from "react";
import clsx from "clsx";
import styles from "../../styles/surface.module.css";

type Variant = "card" | "cardLg" | "rail" | "inset";

interface SurfaceProps extends HTMLAttributes<HTMLElement> {
  variant?: Variant;
  as?: "div" | "section" | "article";
  children?: ReactNode;
}

/**
 * Liquid-glass surface shell. All the vibrancy/blur/border logic lives in
 * ``surface.module.css``; this component just applies the right class set
 * and forwards rest-props. Choose ``variant`` to pick padding + shadow
 * intensity; omit for the default card.
 *
 * The ref is typed as :type:`HTMLElement` rather than the more specific
 * ``HTMLDivElement`` because ``as`` can be ``"section"`` / ``"article"``.
 * That's the common ancestor for the three supported tags and avoids the
 * ``as never`` escape hatch that previously hid real ref/element
 * mismatches from the type system.
 */
export const Surface = forwardRef<HTMLElement, SurfaceProps>(
  ({ variant = "card", as: Component = "div", className, children, ...rest }, ref) => (
    <Component
      ref={ref as Ref<HTMLElement & HTMLDivElement>}
      className={clsx(styles.surface, styles[variant], className)}
      {...rest}
    >
      {children}
    </Component>
  ),
);
Surface.displayName = "Surface";
