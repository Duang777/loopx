import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  LockKeyhole,
  ShieldCheck,
  WifiOff,
} from "lucide-react";

import { cn } from "../../lib/utils";

export type ConsoleTone = "neutral" | "positive" | "warning" | "danger" | "info";

export function ConsolePanel({
  children,
  className,
  description,
  eyebrow,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  description?: string;
  eyebrow?: string;
  title?: string;
}) {
  return (
    <section className={cn("operator-panel", className)}>
      {(eyebrow || title || description) && (
        <header className="operator-panel__header">
          <div>
            {eyebrow && <p className="operator-eyebrow">{eyebrow}</p>}
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
        </header>
      )}
      {children}
    </section>
  );
}

export function ConsoleBadge({
  children,
  className,
  tone = "neutral",
}: {
  children: React.ReactNode;
  className?: string;
  tone?: ConsoleTone;
}) {
  return <span className={cn("operator-badge", `operator-badge--${tone}`, className)}>{children}</span>;
}

export function Metric({
  detail,
  label,
  tone = "neutral",
  value,
}: {
  detail?: string;
  label: string;
  tone?: ConsoleTone;
  value: React.ReactNode;
}) {
  return (
    <div className={cn("operator-metric", `operator-metric--${tone}`)}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

export function Field({
  children,
  hint,
  label,
}: {
  children: React.ReactNode;
  hint?: string;
  label: string;
}) {
  return (
    <label className="operator-field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function ActionGate({
  available,
  isOperator,
  reason,
  requiresOperator = true,
}: {
  available: boolean;
  isOperator: boolean;
  reason?: string | null;
  requiresOperator?: boolean;
}) {
  if (available && (!requiresOperator || isOperator)) {
    return (
      <div className="operator-action-gate operator-action-gate--ready">
        <ShieldCheck aria-hidden="true" size={15} />
        {requiresOperator
          ? "Operator authority and server capability are ready."
          : "Read capability is ready; operator authority is not required."}
      </div>
    );
  }
  return (
    <div className="operator-action-gate">
      <LockKeyhole aria-hidden="true" size={15} />
      {!available ? reason ?? "This capability is unavailable in the active server profile." : "Acquire the operator role to enable this action."}
    </div>
  );
}

export function Freshness({
  hidden,
  lastUpdated,
  stale,
}: {
  hidden: boolean;
  lastUpdated: number;
  stale: boolean;
}) {
  const label = lastUpdated > 0
    ? new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(lastUpdated)
    : "Waiting for data";
  return (
    <div className={cn("operator-freshness", stale && "operator-freshness--stale")} data-testid="operator-freshness">
      {stale ? <WifiOff aria-hidden="true" size={15} /> : <Clock3 aria-hidden="true" size={15} />}
      <span>{stale ? "Stale" : "Live"} · {label}</span>
      <small>{hidden ? "background polling slowed" : "3s conditional polling"}</small>
    </div>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }
  const code = error && typeof error === "object" && "code" in error
    ? String((error as { code: unknown }).code)
    : "request_failed";
  const message = error instanceof Error ? error.message : "The operation could not be completed.";
  return (
    <div className="operator-notice operator-notice--danger" role="alert">
      <AlertTriangle aria-hidden="true" size={16} />
      <div><strong>{code}</strong><span>{message}</span></div>
    </div>
  );
}

export function SuccessNotice({ children }: { children: React.ReactNode }) {
  return (
    <div className="operator-notice operator-notice--success" role="status">
      <CheckCircle2 aria-hidden="true" size={16} />
      <span>{children}</span>
    </div>
  );
}
