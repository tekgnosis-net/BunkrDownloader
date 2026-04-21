import { memo } from "react";
import { GlassProgress } from "../primitives/GlassProgress";
import { useTaskRow } from "../../lib/store";

/**
 * Single file progress row. Memoised on the task id and subscribes
 * directly to its own slice so a sibling's update won't cause this row
 * to re-render.
 */
export const TaskRow = memo(function TaskRow({ taskId }: { taskId: number }) {
  const task = useTaskRow(taskId);
  if (!task || !task.visible) return null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(140px, 1fr) 2fr 60px",
        alignItems: "center",
        gap: "var(--space-4)",
        padding: "var(--space-2) 0",
      }}
    >
      <span
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: "var(--ink)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {task.label}
      </span>
      <GlassProgress value={task.completed} label={task.label} />
      <span
        className="tabular"
        style={{
          textAlign: "right",
          fontSize: 12,
          color: "var(--ink-muted)",
        }}
      >
        {Math.round(task.completed)}%
      </span>
    </div>
  );
});
