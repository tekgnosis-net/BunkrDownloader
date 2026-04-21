import { Surface } from "../primitives/Surface";
import { TaskRow } from "./TaskRow";
import { useActiveTaskIds } from "../../lib/store";

/**
 * Panel of per-file progress rows. Subscribes only to ``activeTaskIds``
 * (a shallow-compared array); adding/removing tasks bumps this
 * reference, but per-row progress updates only trigger a ``TaskRow``
 * re-render.
 */
export function TaskList() {
  const ids = useActiveTaskIds();
  if (!ids.length) return null;

  return (
    <Surface variant="card">
      <h2
        style={{
          margin: 0,
          marginBottom: "var(--space-3)",
          fontSize: 17,
          fontWeight: 600,
          color: "var(--ink)",
        }}
      >
        Per-file progress
      </h2>
      <div role="list">
        {ids.map((id) => (
          <div key={id} role="listitem">
            <TaskRow taskId={id} />
          </div>
        ))}
      </div>
    </Surface>
  );
}
