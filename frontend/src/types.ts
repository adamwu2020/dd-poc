export type Label = "positive" | "negative";
export type NegativeType = "hard" | "easy";

export interface TestResult {
  name: string;
  category: string;
  result: string;
  unit: string;
  reference_range: string;
  flag: "high" | "low" | "normal" | "abnormal" | "n/a";
}

export interface PatientRecord {
  demographics: { age: number; sex: "male" | "female" };
  chief_complaint: string;
  history_of_present_illness: string;
  past_medical_history: string[];
  medications: string[];
  allergies: string[];
  family_history: string;
  social_history: string;
  review_of_systems: string;
  physical_exam: {
    vitals: {
      blood_pressure: string;
      heart_rate: number;
      respiratory_rate: number;
      temperature_c: number;
      spo2: number;
    };
    findings: string;
  };
  test_results: TestResult[];
  diagnosis: { final: string; differentials: string[] };
  plan: string;
}

export interface Sample {
  id: string;
  department: string;
  target_condition: string;
  label: Label;
  negative_type: NegativeType | null;
  intended_diagnosis: string;
  record: PatientRecord;
}

export type JobState = "planning" | "running" | "completed" | "failed" | "cancelled";

export interface JobStatus {
  job_id: string;
  status: JobState;
  total: number;
  completed: number;
  failed: number;
  error: string | null;
}

export interface GenerationOptions {
  negative_strategy: "hard" | "easy" | "mixed";
  severity: "mild" | "moderate" | "severe" | "mixed";
  age_min: number;
  age_max: number;
  sex: "mixed" | "male" | "female";
  language: string;
  seed: number | null;
}

export interface GenerateRequest {
  department: string;
  conditions: string[];
  positive_count: number;
  negative_count: number;
  options: GenerationOptions;
}

export type JobEvent =
  | ({ type: "status" } & JobStatus)
  | { type: "sample"; index: number; sample: Sample }
  | { type: "sample_error"; index: number; error: string }
  | { type: "done"; status: JobState; error: string | null };
