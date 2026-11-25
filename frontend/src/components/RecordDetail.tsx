import type { ReactNode } from "react";
import type { Sample } from "../types";

function List({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="muted">None</p>;
  return (
    <ul>
      {items.map((i, n) => (
        <li key={n}>{i}</li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="report-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

export default function RecordDetail({ sample, onClose }: { sample: Sample; onClose: () => void }) {
  const r = sample.record;
  const v = r.physical_exam.vitals;

  return (
    <aside className="detail" aria-label={`Record ${sample.id}`}>
      <header className="detail-header">
        <div>
          <h3>{sample.id}</h3>
          <p>
            <span className={`badge ${sample.label}`}>{sample.label}</span>
            {sample.negative_type && <span className="badge">{sample.negative_type} negative</span>}
            <span className="muted">Target: {sample.target_condition}</span>
          </p>
        </div>
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </header>

      <div className="report">
        <Section title="Patient">
          <p>
            {r.demographics.age}-year-old {r.demographics.sex} · {sample.department}
          </p>
        </Section>
        <Section title="Chief complaint">
          <p>{r.chief_complaint}</p>
        </Section>
        <Section title="History of present illness">
          <p>{r.history_of_present_illness}</p>
        </Section>
        <Section title="Past medical history">
          <List items={r.past_medical_history} />
        </Section>
        <Section title="Medications">
          <List items={r.medications} />
        </Section>
        <Section title="Allergies">
          <List items={r.allergies} />
        </Section>
        <Section title="Family history">
          <p>{r.family_history}</p>
        </Section>
        <Section title="Social history">
          <p>{r.social_history}</p>
        </Section>
        <Section title="Review of systems">
          <p>{r.review_of_systems}</p>
        </Section>
        <Section title="Physical examination">
          <p className="vitals">
            BP {v.blood_pressure} · HR {v.heart_rate} · RR {v.respiratory_rate} · Temp {v.temperature_c} °C · SpO₂{" "}
            {v.spo2}%
          </p>
          <p>{r.physical_exam.findings}</p>
        </Section>
        <Section title="Investigations">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Result</th>
                  <th>Reference</th>
                  <th>Flag</th>
                </tr>
              </thead>
              <tbody>
                {r.test_results.map((t, i) => (
                  <tr key={i}>
                    <td>
                      {t.name}
                      <div className="muted small">{t.category}</div>
                    </td>
                    <td>
                      {t.result} {t.unit}
                    </td>
                    <td>{t.reference_range}</td>
                    <td className={`flag-${t.flag}`}>{t.flag === "n/a" ? "" : t.flag}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <Section title="Assessment / diagnosis">
          <p>
            <strong>{r.diagnosis.final}</strong>
          </p>
          {r.diagnosis.differentials.length > 0 && (
            <p className="muted">Differentials: {r.diagnosis.differentials.join(", ")}</p>
          )}
        </Section>
        <Section title="Plan">
          <p>{r.plan}</p>
        </Section>
      </div>
    </aside>
  );
}
