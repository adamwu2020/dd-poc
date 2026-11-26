import type { JobSummary } from "../types";

interface Props {
  jobs: JobSummary[];
  activeJobId: string | null;
  onOpen: (jobId: string) => void;
}

export default function MyDatasets({ jobs, activeJobId, onOpen }: Props) {
  if (jobs.length === 0) return null;
  return (
    <section className="card">
      <h2>My datasets</h2>
      <div className="table-wrap">
        <table className="results">
          <thead>
            <tr>
              <th>Created</th>
              <th>Department</th>
              <th>Conditions</th>
              <th>Samples</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr
                key={j.job_id}
                className={j.job_id === activeJobId ? "selected" : ""}
                onClick={() => onOpen(j.job_id)}
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && onOpen(j.job_id)}
              >
                <td>{new Date(j.created_at).toLocaleString()}</td>
                <td>{j.department}</td>
                <td>{j.conditions.join(", ")}</td>
                <td>
                  {j.completed} / {j.total}
                  {j.failed > 0 && <span className="muted small"> ({j.failed} failed)</span>}
                </td>
                <td>
                  <span className={`badge status-${j.status}`}>{j.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
