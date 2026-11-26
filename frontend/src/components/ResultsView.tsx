import { useState } from "react";
import { api } from "../api";
import type { JobStatus, Sample } from "../types";
import RecordDetail from "./RecordDetail";

interface Props {
  status: JobStatus;
  samples: Sample[];
  errors: { index: number; error: string }[];
  onCancel: () => void;
  onReset: () => void;
}

const STATUS_TEXT: Record<JobStatus["status"], string> = {
  planning: "Choosing negative diagnoses…",
  running: "Generating samples…",
  completed: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export default function ResultsView({ status, samples, errors, onCancel, onReset }: Props) {
  const [selected, setSelected] = useState<Sample | null>(null);
  const [filter, setFilter] = useState<"all" | "positive" | "negative">("all");
  const [format, setFormat] = useState("jsonl");
  const [part, setPart] = useState("full");

  const active = status.status === "planning" || status.status === "running";
  const done = status.completed + status.failed;
  const pct = status.total ? Math.round((done / status.total) * 100) : 0;
  const shown = samples.filter((s) => filter === "all" || s.label === filter);
  const positives = samples.filter((s) => s.label === "positive").length;

  return (
    <section className="card">
      <h2>Results</h2>

      <div className="progress-head">
        <strong>{STATUS_TEXT[status.status]}</strong>
        <span className="muted">
          {status.completed} of {status.total} generated
          {status.failed > 0 && `, ${status.failed} failed`}
        </span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={`progress-bar ${status.status}`} style={{ width: `${pct}%` }} />
      </div>
      {status.error && <p className="error">{status.error}</p>}
      {errors.length > 0 && (
        <details className="errors">
          <summary>{errors.length} sample(s) could not be generated</summary>
          <ul>
            {errors.map((e) => (
              <li key={e.index}>
                Sample {e.index + 1}: {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="actions">
        <div className="row tight">
          {active ? (
            <button type="button" className="danger" onClick={onCancel}>
              Cancel
            </button>
          ) : (
            <button type="button" className="secondary" onClick={onReset}>
              Close
            </button>
          )}
        </div>
        <div className="row tight export">
          <select value={part} onChange={(e) => setPart(e.target.value)} aria-label="Export content">
            <option value="full">Full records</option>
            <option value="inputs">Inputs only (diagnosis removed)</option>
            <option value="answers">Answers only (labels)</option>
          </select>
          <select value={format} onChange={(e) => setFormat(e.target.value)} aria-label="Export format">
            <option value="jsonl">JSONL</option>
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
          <a
            className={`button ${samples.length === 0 ? "disabled" : ""}`}
            href={api.exportUrl(status.job_id, format, part)}
            aria-disabled={samples.length === 0}
          >
            Download
          </a>
        </div>
      </div>

      <div className="filters" role="tablist">
        {(["all", "positive", "negative"] as const).map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={filter === f}
            className={`tab ${filter === f ? "active" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? `All (${samples.length})` : f === "positive" ? `Positive (${positives})` : `Negative (${samples.length - positives})`}
          </button>
        ))}
      </div>

      <div className="results-layout">
        <div className="table-wrap">
          <table className="results">
            <thead>
              <tr>
                <th>ID</th>
                <th>Label</th>
                <th>Target</th>
                <th>Final diagnosis</th>
                <th>Patient</th>
                <th>Chief complaint</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => (
                <tr
                  key={s.id}
                  className={selected?.id === s.id ? "selected" : ""}
                  onClick={() => setSelected(s)}
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && setSelected(s)}
                >
                  <td className="mono">{s.id}</td>
                  <td>
                    <span className={`badge ${s.label}`}>{s.label}</span>
                    {s.negative_type && <span className="muted small"> {s.negative_type}</span>}
                  </td>
                  <td>{s.target_condition}</td>
                  <td title={s.record.diagnosis.final}>
                    <div className="clamp">{s.record.diagnosis.final}</div>
                  </td>
                  <td>
                    {s.record.demographics.age} {s.record.demographics.sex[0].toUpperCase()}
                  </td>
                  <td className="truncate" title={s.record.chief_complaint}>
                    {s.record.chief_complaint}
                  </td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted center">
                    {active ? "Samples will appear here as they are generated." : "No samples."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {selected && <RecordDetail sample={selected} onClose={() => setSelected(null)} />}
      </div>
    </section>
  );
}
