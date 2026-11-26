import { formatUsd } from "../api";
import type { OrderView } from "../types";

interface Props {
  order: OrderView;
  busy: boolean;
  onPay: () => void;
  onCancel: () => void;
}

/** Stand-in for Stripe Checkout when the server runs with PAYMENT_MODE=mock (local development). */
export default function MockCheckout({ order, busy, onPay, onCancel }: Props) {
  return (
    <section className="card mock-checkout">
      <p className="badge">Test mode: no real payment</p>
      <h2>Checkout</h2>
      <p>
        {order.quote.paid_samples} synthetic patient record{order.quote.paid_samples === 1 ? "" : "s"} ×{" "}
        {formatUsd(order.quote.price_per_sample_cents)}
      </p>
      <p className="total">{formatUsd(order.quote.amount_cents)}</p>
      <div className="actions">
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" onClick={onPay} disabled={busy}>
          Pay {formatUsd(order.quote.amount_cents)}
        </button>
      </div>
    </section>
  );
}
