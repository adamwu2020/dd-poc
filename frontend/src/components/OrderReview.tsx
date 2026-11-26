import { formatUsd } from "../api";
import type { GenerateRequest, Quote } from "../types";

interface Props {
  request: GenerateRequest;
  quote: Quote;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onBack: () => void;
}

/** The payment page: what will be generated and what it costs, before paying. */
export default function OrderReview({ request, quote, busy, error, onConfirm, onBack }: Props) {
  const free = quote.free_positive + quote.free_negative;
  const price = quote.price_per_sample_cents;

  return (
    <section className="card" aria-labelledby="review-title">
      <h2 id="review-title">
        <span className="step">3</span> Review and pay
      </h2>

      <dl className="summary">
        <dt>Department</dt>
        <dd>{request.department}</dd>
        <dt>Conditions</dt>
        <dd>{request.conditions.join(", ")}</dd>
        <dt>Samples</dt>
        <dd>
          {quote.positive_samples} positive + {quote.negative_samples} negative = {quote.total_samples}
        </dd>
      </dl>

      <table className="invoice">
        <tbody>
          <tr>
            <td>
              {quote.total_samples} sample{quote.total_samples === 1 ? "" : "s"} × {formatUsd(price)}
            </td>
            <td className="num">{formatUsd(quote.total_samples * price)}</td>
          </tr>
          {free > 0 && (
            <tr>
              <td>
                Free samples ({quote.free_positive} positive, {quote.free_negative} negative)
              </td>
              <td className="num">−{formatUsd(free * price)}</td>
            </tr>
          )}
          {quote.credits_used > 0 && (
            <tr>
              <td>Account credits ({quote.credits_used})</td>
              <td className="num">−{formatUsd(quote.credits_used * price)}</td>
            </tr>
          )}
        </tbody>
        <tfoot>
          <tr>
            <th>Total due</th>
            <th className="num">{formatUsd(quote.amount_cents)}</th>
          </tr>
        </tfoot>
      </table>

      <p className="hint">
        {quote.amount_cents > 0
          ? "You'll pay on a secure Stripe page, and generation starts as soon as the payment is confirmed. "
          : "This is covered by your free samples and credits. "}
        You're only charged for delivered samples. Any that fail are added back to your account as credits.
      </p>
      {error && <p className="error">{error}</p>}

      <div className="actions">
        <button type="button" className="secondary" onClick={onBack} disabled={busy}>
          Back
        </button>
        <button type="button" onClick={onConfirm} disabled={busy}>
          {busy
            ? "Please wait…"
            : quote.amount_cents > 0
              ? `Pay ${formatUsd(quote.amount_cents)} and generate`
              : "Generate for free"}
        </button>
      </div>
    </section>
  );
}
