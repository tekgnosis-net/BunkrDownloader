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
 * The outer ref type is :type:`HTMLElement` — the common ancestor of the
 * three tags ``as`` supports — so consumers get an honest contract.
 * Internally we fall to :type:`Ref<never>` to bridge into React's JSX
 * ref types, which require a specific subtype (``HTMLDivElement`` /
 * ``HTMLSectionElement`` / ``HTMLHeadingElement``) per tag. ``Ref<never>``
 * is idiomatic React for polymorphic ``as`` props: it's assignable to
 * every specific ref type without lying about the runtime element (which
 * ``Ref<HTMLDivElement>`` would do for ``as="section"``).
 */
export const Surface = forwardRef<HTMLElement, SurfaceProps>(
  ({ variant = "card", as: Component = "div", className, children, ...rest }, ref) => (
    <Component
      ref={ref as Ref<never>}
      className={clsx(styles.surface, styles[variant], className)}
      {...rest}
    >
      {children}
    </Component>
  ),
);
Surface.displayName = "Surface";
