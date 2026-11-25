import { useState } from "react";
import type { GenerateRequest, GenerationOptions } from "../types";

interface Props {
  department: string;
  conditions: string[];
  source: "seed" | "llm";
  disabled: boolean;
  maxSamples: number;
  onGenerate: (req: GenerateRequest) => void;
}

const DEFAULT_OPTIONS: GenerationOptions = {
  negative_strategy: "mixed",
  severity: "mixed",
  age_min: 18,
  age_max: 85,
  sex: "mixed",
  language: "English",
  seed: null,
};

export default function ConditionStep({
  department,
  conditions,
  source,
  disabled,
  maxSamples,
  onGenerate,
}: Props) {
  const [available, setAvailable] = useState(conditions);
  const [selected, setSelected] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [positive, setPositive] = useState(10);
  const [negative, setNegative] = useState(10);
  const [options, setOptions] = useState(DEFAULT_OPTIONS);

  const total = (positive + negative) * selected.length;
  const tooMany = total > maxSamples;
  const ageInvalid = options.age_min > options.age_max;
  const canGenerate = selected.length > 0 && total > 0 && !tooMany && !ageInvalid && !disabled;

  function toggle(c: string) {
    setSelected((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]));
  }

  function addCustom() {
    const c = custom.trim();
    if (!c) return;
    if (!available.includes(c)) setAvailable((a) => [...a, c]);
    if (!selected.includes(c)) setSelected((s) => [...s, c]);
    setCustom("");
  }

  function set<K extends keyof GenerationOptions>(key: K, value: GenerationOptions[K]) {
    setOptions((o) => ({ ...o, [key]: value }));
  }

  return (
    <section className="card">
      <h2>
        <span className="step">2</span> Conditions for {department}
      </h2>
      {source === "llm" && <p className="hint">Suggested by the model. Check them before generating.</p>}

      <div className="chips">
        {available.map((c) => (
          <button
            key={c}
            type="button"
            className={`chip ${selected.includes(c) ? "selected" : ""}`}
            aria-pressed={selected.includes(c)}
            disabled={disabled}
            onClick={() => toggle(c)}
          >
            {c}
          </button>
        ))}
      </div>

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          addCustom();
        }}
      >
        <input
          placeholder="Add another disease or symptom"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          disabled={disabled}
          aria-label="Custom condition"
        />
        <button type="submit" className="secondary" disabled={disabled || !custom.trim()}>
          Add
        </button>
      </form>

      <div className="grid">
        <label>
          Positive samples per condition
          <input
            type="number"
            min={0}
            max={500}
            value={positive}
            disabled={disabled}
            onChange={(e) => setPositive(Math.max(0, Number(e.target.value)))}
          />
        </label>
        <label>
          Negative samples per condition
          <input
            type="number"
            min={0}
            max={500}
            value={negative}
            disabled={disabled}
            onChange={(e) => setNegative(Math.max(0, Number(e.target.value)))}
          />
        </label>
      </div>

      <details>
        <summary>Advanced options</summary>
        <div className="grid">
          <label>
            Negative samples
            <select
              value={options.negative_strategy}
              disabled={disabled}
              onChange={(e) => set("negative_strategy", e.target.value as GenerationOptions["negative_strategy"])}
            >
              <option value="mixed">Mixed (mostly similar presentations)</option>
              <option value="hard">Hard: similar presentation, different diagnosis</option>
              <option value="easy">Easy: unrelated diagnosis</option>
            </select>
          </label>
          <label>
            Severity
            <select
              value={options.severity}
              disabled={disabled}
              onChange={(e) => set("severity", e.target.value as GenerationOptions["severity"])}
            >
              <option value="mixed">Mixed</option>
              <option value="mild">Mild</option>
              <option value="moderate">Moderate</option>
              <option value="severe">Severe</option>
            </select>
          </label>
          <label>
            Sex
            <select
              value={options.sex}
              disabled={disabled}
              onChange={(e) => set("sex", e.target.value as GenerationOptions["sex"])}
            >
              <option value="mixed">Mixed</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
          </label>
          <label>
            Age range
            <span className="row tight">
              <input
                type="number"
                min={0}
                max={110}
                value={options.age_min}
                disabled={disabled}
                onChange={(e) => set("age_min", Number(e.target.value))}
                aria-label="Minimum age"
              />
              <span>to</span>
              <input
                type="number"
                min={0}
                max={110}
                value={options.age_max}
                disabled={disabled}
                onChange={(e) => set("age_max", Number(e.target.value))}
                aria-label="Maximum age"
              />
            </span>
          </label>
          <label>
            Language
            <input
              value={options.language}
              disabled={disabled}
              onChange={(e) => set("language", e.target.value)}
            />
          </label>
          <label>
            Random seed (optional)
            <input
              type="number"
              value={options.seed ?? ""}
              disabled={disabled}
              onChange={(e) => set("seed", e.target.value === "" ? null : Number(e.target.value))}
            />
          </label>
        </div>
        <p className="hint">The seed fixes the patient profiles and diagnosis mix. The record text still varies between runs.</p>
      </details>

      <div className="actions">
        <span className={tooMany || ageInvalid ? "error" : "hint"}>
          {ageInvalid
            ? "Minimum age must not be above maximum age."
            : selected.length === 0
              ? "Select at least one condition."
              : `${total} samples (${selected.length} condition${selected.length > 1 ? "s" : ""} × ${positive + negative})` +
                (tooMany ? `, which is over the limit of ${maxSamples}` : "")}
        </span>
        <button
          type="button"
          disabled={!canGenerate}
          onClick={() =>
            onGenerate({
              department,
              conditions: selected,
              positive_count: positive,
              negative_count: negative,
              options,
            })
          }
        >
          Generate
        </button>
      </div>
    </section>
  );
}
