import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatUsd, setUnauthorizedHandler } from "./api";
import AuthPage from "./components/AuthPage";
import ConditionStep from "./components/ConditionStep";
import DepartmentStep from "./components/DepartmentStep";
import MockCheckout from "./components/MockCheckout";
import MyDatasets from "./components/MyDatasets";
import OrderReview from "./components/OrderReview";
import ResultsView from "./components/ResultsView";
import type { Account, GenerateRequest, JobEvent, JobStatus, JobSummary, OrderView, Quote, Sample } from "./types";

interface ConditionList {
  department: string;
  conditions: string[];
  source: "seed" | "llm";
}

type Health = Awaited<ReturnType<typeof api.health>>;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  // undefined while checking the session, null when signed out
  const [account, setAccount] = useState<Account | null | undefined>(undefined);
  const [myJobs, setMyJobs] = useState<JobSummary[]>([]);

  const [conditionList, setConditionList] = useState<ConditionList | null>(null);
  const [review, setReview] = useState<{ request: GenerateRequest; quote: Quote } | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [mockOrder, setMockOrder] = useState<OrderView | null>(null);
  const [notice, setNotice] = useState<{ text: string; kind: "info" | "error" } | null>(null);

  const [job, setJob] = useState<JobStatus | null>(null);
  const [samples, setSamples] = useState<Map<number, Sample>>(new Map());
  const [errors, setErrors] = useState<Map<number, string>>(new Map());
  const unsubscribe = useRef<(() => void) | null>(null);
  const handledReturn = useRef(false);

  const refreshAccount = useCallback(() => {
    api.account().then(setAccount).catch(() => undefined);
    api.jobs().then(setMyJobs).catch(() => undefined);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setAccount(null));
    api.health().then(setHealth).catch(() => setHealth(null));
    api.me().then(setAccount).catch(() => setAccount(null));
    return () => unsubscribe.current?.();
  }, []);

  useEffect(() => {
    if (account) api.jobs().then(setMyJobs).catch(() => undefined);
  }, [account?.email]); // eslint-disable-line react-hooks/exhaustive-deps

  const running = job?.status === "planning" || job?.status === "running";

  const onEvent = useCallback(
    (event: JobEvent) => {
      switch (event.type) {
        case "status": {
          const { type: _, ...status } = event;
          setJob(status);
          break;
        }
        case "sample":
          setSamples((m) => new Map(m).set(event.index, event.sample));
          break;
        case "sample_error":
          setErrors((m) => new Map(m).set(event.index, event.error));
          break;
        case "done":
          setJob((j) => (j ? { ...j, status: event.status, error: event.error } : j));
          refreshAccount();
          break;
      }
    },
    [refreshAccount],
  );

  const openJob = useCallback(
    (jobId: string) => {
      unsubscribe.current?.();
      setNotice(null);
      setSamples(new Map());
      setErrors(new Map());
      setJob({ job_id: jobId, status: "planning", total: 0, completed: 0, failed: 0, error: null });
      unsubscribe.current = api.stream(jobId, onEvent);
      api.jobs().then(setMyJobs).catch(() => undefined);
    },
    [onEvent],
  );

  // Coming back from the payment page: /?order=…&checkout=success|cancelled, or the mock checkout.
  useEffect(() => {
    if (!account || handledReturn.current) return;
    const params = new URLSearchParams(window.location.search);
    const orderId = params.get("order");
    if (!orderId) return;
    handledReturn.current = true;
    window.history.replaceState(null, "", "/");

    (async () => {
      try {
        if (params.get("mock_checkout")) {
          const order = await api.order(orderId);
          if (order.status === "pending") setMockOrder(order);
          else if (order.job_id) openJob(order.job_id);
        } else if (params.get("checkout") === "cancelled") {
          await api.cancelOrder(orderId);
          setNotice({ text: "Payment cancelled. You were not charged.", kind: "info" });
          refreshAccount();
        } else if (params.get("checkout") === "success") {
          setNotice({ text: "Payment received. Starting generation…", kind: "info" });
          for (let i = 0; i < 30; i++) {
            const order = await api.order(orderId);
            if (order.job_id) {
              setNotice(null);
              openJob(order.job_id);
              refreshAccount();
              return;
            }
            if (order.status === "expired") break;
            await sleep(2000);
          }
          setNotice({
            text: "We haven't received confirmation of your payment yet. Check “My datasets” again in a minute.",
            kind: "error",
          });
        }
      } catch (e) {
        setNotice({ text: (e as Error).message, kind: "error" });
      }
    })();
  }, [account, openJob, refreshAccount]);

  async function startReview(request: GenerateRequest) {
    setReviewError(null);
    setNotice(null);
    try {
      setReview({ request, quote: await api.quote(request) });
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
  }

  async function confirmOrder() {
    if (!review) return;
    setReviewBusy(true);
    setReviewError(null);
    try {
      const order = await api.createOrder(review.request);
      if (order.job_id) {
        setReview(null);
        openJob(order.job_id);
        refreshAccount();
      } else if (order.checkout_url) {
        window.location.assign(order.checkout_url);
        return; // keep the button disabled while the browser navigates
      }
    } catch (e) {
      setReviewError((e as Error).message);
    }
    setReviewBusy(false);
  }

  async function mockPay(pay: boolean) {
    if (!mockOrder) return;
    setReviewBusy(true);
    try {
      if (pay) {
        const order = await api.mockPay(mockOrder.order_id);
        if (order.job_id) openJob(order.job_id);
      } else {
        await api.cancelOrder(mockOrder.order_id);
        setNotice({ text: "Payment cancelled. You were not charged.", kind: "info" });
      }
      setMockOrder(null);
      refreshAccount();
    } catch (e) {
      setNotice({ text: (e as Error).message, kind: "error" });
    }
    setReviewBusy(false);
  }

  async function logout() {
    unsubscribe.current?.();
    await api.logout().catch(() => undefined);
    setAccount(null);
    setJob(null);
    setReview(null);
    setConditionList(null);
    setMyJobs([]);
    setNotice(null);
    handledReturn.current = false;
  }

  if (account === undefined) {
    return <div className="page muted">Loading…</div>;
  }

  const orderedSamples = [...samples.entries()].sort(([a], [b]) => a - b).map(([, s]) => s);
  const orderedErrors = [...errors.entries()].sort(([a], [b]) => a - b).map(([index, error]) => ({ index, error }));

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Synthetic Patient Data Generator</h1>
          <p className="muted">
            Build labeled, fully synthetic patient records for evaluating LLMs.
            {health && (
              <>
                {" "}
                Model: <code>{health.mode === "mock" ? "mock (no API calls)" : health.model}</code>
              </>
            )}
          </p>
        </div>
        {account && (
          <div className="account">
            <span className="account-email">{account.email}</span>
            <span className="muted small">
              Free: {account.free_positive_left} positive, {account.free_negative_left} negative
              {account.sample_credits > 0 && ` · Credits: ${account.sample_credits}`} ·{" "}
              {formatUsd(account.price_per_sample_cents)}/sample after that
            </span>
            <button type="button" className="secondary small-button" onClick={logout}>
              Sign out
            </button>
          </div>
        )}
      </header>

      {!account ? (
        <AuthPage onSignedIn={setAccount} />
      ) : mockOrder ? (
        <MockCheckout order={mockOrder} busy={reviewBusy} onPay={() => mockPay(true)} onCancel={() => mockPay(false)} />
      ) : (
        <>
          {notice && <p className={notice.kind === "error" ? "error notice" : "notice"}>{notice.text}</p>}

          <DepartmentStep
            disabled={running || !!review}
            onLoaded={(department, conditions, source) => {
              setReview(null);
              setConditionList({ department, conditions, source });
            }}
          />

          {conditionList && (
            <ConditionStep
              key={`${conditionList.department}|${conditionList.conditions.join("|")}`}
              {...conditionList}
              disabled={running || !!review}
              maxSamples={health?.max_samples_per_job ?? 20}
              onGenerate={startReview}
            />
          )}

          {review && (
            <OrderReview
              {...review}
              busy={reviewBusy}
              error={reviewError}
              onConfirm={confirmOrder}
              onBack={() => setReview(null)}
            />
          )}

          {job && (
            <ResultsView
              status={job}
              samples={orderedSamples}
              errors={orderedErrors}
              onCancel={() => api.cancel(job.job_id).catch(() => undefined)}
              onReset={() => {
                unsubscribe.current?.();
                setJob(null);
              }}
            />
          )}

          <MyDatasets jobs={myJobs} activeJobId={job?.job_id ?? null} onOpen={openJob} />
        </>
      )}

      <footer className="muted small">
        All records are synthetic and generated by an LLM. They may contain clinical errors and must not be used
        for patient care.
      </footer>
    </div>
  );
}
