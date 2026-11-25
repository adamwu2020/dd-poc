import { useEffect, useState } from "react";
import { api } from "../api";

interface Props {
  disabled: boolean;
  onLoaded: (department: string, conditions: string[], source: "seed" | "llm") => void;
}

export default function DepartmentStep({ disabled, onLoaded }: Props) {
  const [departments, setDepartments] = useState<string[]>([]);
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.departments().then(setDepartments).catch(() => setDepartments([]));
  }, []);

  async function load(department: string) {
    const name = department.trim();
    if (!name) return;
    setValue(name);
    setLoading(true);
    setError(null);
    try {
      const res = await api.conditions(name);
      onLoaded(res.department, res.conditions, res.source);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h2>
        <span className="step">1</span> Hospital department
      </h2>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          load(value);
        }}
      >
        <input
          list="departments"
          placeholder="e.g. Cardiology, or any other department"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={disabled || loading}
          aria-label="Department"
        />
        <datalist id="departments">
          {departments.map((d) => (
            <option key={d} value={d} />
          ))}
        </datalist>
        <button type="submit" disabled={disabled || loading || !value.trim()}>
          {loading ? "Loading…" : "Show conditions"}
        </button>
      </form>
      <div className="chips">
        {departments.map((d) => (
          <button
            key={d}
            type="button"
            className="chip"
            disabled={disabled || loading}
            onClick={() => load(d)}
          >
            {d}
          </button>
        ))}
      </div>
      <p className="hint">
        Departments not in this list are sent to the model, which suggests common conditions for them.
      </p>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
