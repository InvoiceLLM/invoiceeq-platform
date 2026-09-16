"use client";

import { useState } from "react";
import { Pencil, Plus, Undo2, X } from "lucide-react";
import { cleanEntry, DetailColumn, DetailEntry, DetailFormat, DetailListSpec } from "@/lib/correctableDetails";

/**
 * BE Gap 531: one list-shaped invoice detail (tax IDs, tax lines, addresses, …),
 * shown read-only and correctable in place. Edits are staged into the page's
 * `corrections` like any other field and saved by the same Save Correction /
 * resolve call, so nothing here talks to the API.
 */
export default function DetailListEditor({
  spec,
  rows,
  isDirty,
  disabled,
  formatNumber,
  onChange,
  onRevert,
}: {
  spec: DetailListSpec;
  /** The staged correction if there is one, else what was extracted. */
  rows: DetailEntry[];
  isDirty: boolean;
  disabled?: boolean;
  formatNumber: (value: number, format: DetailFormat) => string;
  onChange: (rows: DetailEntry[]) => void;
  onRevert: () => void;
}) {
  const [editing, setEditing] = useState(false);

  if (disabled && rows.length === 0) return null;

  const updateCell = (index: number, key: string, value: string | number | undefined) =>
    onChange(rows.map((row, i) => (i === index ? cleanEntry({ ...row, [key]: value }) : row)));

  const showCell = (row: DetailEntry, column: DetailColumn): string | null => {
    const value = row[column.key];
    if (value === undefined || value === "") return null;
    return typeof value === "number" && column.format ? formatNumber(value, column.format) : String(value);
  };

  const [firstColumn, ...otherColumns] = spec.columns;

  return (
    <div className="flex flex-col gap-1" data-testid={`detail-list-${spec.field}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500">
          {spec.label}
          {isDirty && (
            <span title="Corrected — will be saved on resolve/dismiss">
              <Pencil size={10} className="text-blue-400" />
            </span>
          )}
        </span>
        {!disabled && (
          <div className="flex shrink-0 items-center gap-1.5">
            {isDirty && (
              <button
                type="button"
                onClick={() => {
                  onRevert();
                  setEditing(false);
                }}
                className="flex items-center gap-1 rounded border border-slate-600/50 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:border-slate-400 hover:text-slate-200"
                title={`Discard the correction to ${spec.label}`}
              >
                <Undo2 size={10} /> Revert
              </button>
            )}
            <button
              type="button"
              onClick={() => setEditing((prev) => !prev)}
              className="rounded border border-[#222D3D] px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:border-slate-500 hover:text-slate-200"
            >
              {editing ? "Done" : "Edit"}
            </button>
          </div>
        )}
      </div>

      {editing && !disabled ? (
        <div className="flex flex-col gap-2">
          {rows.map((row, index) => (
            <div key={index} className="flex items-start gap-2 rounded-md border border-[#222D3D] bg-[#0F172A] p-2">
              <div className="grid min-w-0 flex-1 grid-cols-1 gap-1.5 sm:grid-cols-2">
                {spec.columns.map((column) => (
                  <label key={column.key} className="flex min-w-0 flex-col gap-0.5 text-[10px] text-slate-500">
                    {column.label}
                    {column.required ? " *" : ""}
                    <input
                      type={column.kind === "number" ? "number" : "text"}
                      step={column.kind === "number" ? "any" : undefined}
                      value={row[column.key] ?? ""}
                      onChange={(e) => {
                        const raw = e.target.value;
                        updateCell(
                          index,
                          column.key,
                          column.kind === "number" ? (raw === "" ? undefined : Number(raw)) : raw
                        );
                      }}
                      className="w-full rounded border border-[#222D3D] bg-[#1E293B] px-2 py-1 text-xs text-slate-200 outline-none focus:border-blue-500"
                    />
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
                aria-label={`Remove ${spec.entryLabel} ${index + 1}`}
                className="shrink-0 p-1 text-rose-500 transition-colors hover:text-rose-400"
              >
                <X size={14} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => onChange([...rows, {}])}
            className="flex items-center gap-1 self-start text-xs font-semibold text-blue-400 hover:text-blue-300"
          >
            <Plus size={12} /> Add {spec.entryLabel}
          </button>
        </div>
      ) : rows.length === 0 ? (
        <p className="text-xs italic text-slate-600">None</p>
      ) : (
        rows.map((row, index) => (
          <div key={index} className="flex justify-between gap-3 text-xs">
            <span className="min-w-0 break-words text-slate-500">{showCell(row, firstColumn) ?? "—"}</span>
            <span className="min-w-0 break-all text-right font-mono text-slate-300">
              {otherColumns.map((column) => showCell(row, column)).filter(Boolean).join(" · ")}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
