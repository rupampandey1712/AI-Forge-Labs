/**
 * UI primitives.
 *
 * Kept in one file on purpose: these are ten small, stable components with no
 * internal dependencies, and a directory of ten two-line files costs more to
 * navigate than it saves. When one of them grows a real implementation
 * (Modal's focus trap did), it moves out.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { fadeIn } from '@/lib/motion';
import { AlertTriangle, Loader2, X } from 'lucide-react';
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';

// ── Button ──────────────────────────────────────────────────────────────────
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';
type ButtonSize = 'sm' | 'md' | 'lg';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-forge-950 font-semibold hover:bg-accent-soft shadow-glow hover:shadow-glow-lg',
  secondary: 'bg-forge-700 text-forge-100 hover:bg-forge-600 border border-forge-600',
  ghost: 'text-forge-200 hover:bg-forge-800 hover:text-forge-100',
  danger: 'bg-signal-danger text-white font-semibold hover:bg-signal-danger/85 shadow-danger',
  success: 'bg-signal-success text-forge-950 font-semibold hover:bg-signal-success/85',
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
  lg: 'h-12 px-6 text-base gap-2.5',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      // `loading` disables as well as `disabled`: a second click during an
      // in-flight submit is how duplicate attempts get recorded.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center rounded-lg transition-all duration-150',
        'disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none',
        'active:scale-[0.98]',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ── Card / Panel ────────────────────────────────────────────────────────────
// `title` is omitted from the DOM props: HTMLAttributes types it as a string
// (the tooltip attribute), and we want a ReactNode heading. Omitting it is
// clearer than fighting the collision with a cast.
export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  padded?: boolean;
  accent?: string;
}

export function Card({
  title,
  subtitle,
  actions,
  padded = true,
  accent,
  className,
  children,
  ...props
}: CardProps) {
  return (
    <section
      className={cn('panel relative overflow-hidden', className)}
      style={accent ? { borderTopColor: accent, borderTopWidth: 2 } : undefined}
      {...props}
    >
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-forge-700/70 px-5 py-3.5">
          <div className="min-w-0">
            {title && (
              <h2 className="truncate font-display text-sm font-semibold tracking-tight text-forge-100">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-xs text-forge-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(padded && 'p-5')}>{children}</div>
    </section>
  );
}

// ── Chip ────────────────────────────────────────────────────────────────────
export function Chip({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cn('chip border-forge-600 bg-forge-800/70 text-forge-300', className)} {...props}>
      {children}
    </span>
  );
}

// ── Progress ────────────────────────────────────────────────────────────────
export interface ProgressProps {
  value: number; // 0..1
  className?: string;
  barClassName?: string;
  showValue?: boolean;
  label?: string;
  height?: number;
  animate?: boolean;
  color?: string;
}

export function Progress({
  value,
  className,
  barClassName,
  showValue = false,
  label,
  height = 8,
  animate = true,
  color,
}: ProgressProps) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return (
    <div className={cn('w-full', className)}>
      {(label || showValue) && (
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          {label && <span className="text-xs text-forge-300">{label}</span>}
          {showValue && (
            <span className="font-mono text-xs tabular-nums text-forge-300">
              {(clamped * 100).toFixed(0)}%
            </span>
          )}
        </div>
      )}
      <div
        className="w-full overflow-hidden rounded-full bg-forge-800"
        style={{ height }}
        role="progressbar"
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <motion.div
          className={cn('h-full rounded-full bg-accent', barClassName)}
          style={color ? { backgroundColor: color } : undefined}
          initial={animate ? { width: 0 } : false}
          animate={{ width: `${clamped * 100}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 20 }}
        />
      </div>
    </div>
  );
}

// ── Spinner / Skeleton / Empty ──────────────────────────────────────────────
export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      className={cn('h-5 w-5 animate-spin text-accent', className)}
      aria-label="Loading"
      role="status"
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton h-4 w-full', className)} aria-hidden />;
}

export function LoadingPanel({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('panel space-y-3 p-5', className)}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? 'h-5 w-1/3' : 'h-4 w-full'} />
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      {icon && <div className="text-forge-500">{icon}</div>}
      <h3 className="font-display text-base font-semibold text-forge-200">{title}</h3>
      {description && <p className="max-w-sm text-sm text-forge-400">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorState({
  title = 'Something went wrong',
  description,
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <EmptyState
      icon={<AlertTriangle className="h-8 w-8 text-signal-warn" />}
      title={title}
      description={description}
      action={
        onRetry ? (
          <Button size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    />
  );
}

// ── Tabs ────────────────────────────────────────────────────────────────────
interface TabsContextValue {
  value: string;
  setValue: (value: string) => void;
  baseId: string;
}
const TabsContext = createContext<TabsContextValue | null>(null);

export function Tabs({
  defaultValue,
  value: controlled,
  onValueChange,
  children,
  className,
}: {
  defaultValue: string;
  value?: string;
  onValueChange?: (value: string) => void;
  children: ReactNode;
  className?: string;
}) {
  const [internal, setInternal] = useState(defaultValue);
  const baseId = useId();
  const value = controlled ?? internal;
  const setValue = (next: string) => {
    setInternal(next);
    onValueChange?.(next);
  };
  return (
    <TabsContext.Provider value={{ value, setValue, baseId }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      role="tablist"
      className={cn('flex gap-1 border-b border-forge-700 px-1', className)}
    >
      {children}
    </div>
  );
}

export function Tab({
  value,
  children,
  badge,
  icon,
}: {
  value: string;
  children: ReactNode;
  badge?: ReactNode;
  icon?: ReactNode;
}) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error('<Tab> must be inside <Tabs>');
  const active = ctx.value === value;
  return (
    <button
      role="tab"
      id={`${ctx.baseId}-tab-${value}`}
      aria-selected={active}
      aria-controls={`${ctx.baseId}-panel-${value}`}
      onClick={() => ctx.setValue(value)}
      className={cn(
        'relative flex items-center gap-2 px-3.5 py-2 text-sm font-medium transition-colors',
        active ? 'text-accent' : 'text-forge-400 hover:text-forge-200',
      )}
    >
      {icon}
      {children}
      {badge}
      {active && (
        <motion.span
          layoutId={`${ctx.baseId}-tab-underline`}
          className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent"
        />
      )}
    </button>
  );
}

export function TabPanel({ value, children }: { value: string; children: ReactNode }) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error('<TabPanel> must be inside <Tabs>');
  if (ctx.value !== value) return null;
  // `key` on the motion element re-mounts on every tab change, so the panel
  // animates in rather than swapping instantly. Without it React reconciles the
  // two panels as the same node and no transition ever runs.
  return (
    <motion.div
      key={value}
      role="tabpanel"
      id={`${ctx.baseId}-panel-${value}`}
      aria-labelledby={`${ctx.baseId}-tab-${value}`}
      className="pt-4"
      variants={fadeIn}
      initial="hidden"
      animate="show"
    >
      {children}
    </motion.div>
  );
}

// ── Modal ───────────────────────────────────────────────────────────────────
export function Modal({
  open,
  onClose,
  title,
  children,
  size = 'md',
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    // Move focus into the dialog so keyboard users are not left behind it.
    panelRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  const widths = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-3xl', xl: 'max-w-5xl' };

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-forge-950/80 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            ref={panelRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            className={cn(
              'panel relative z-10 max-h-[85vh] w-full overflow-y-auto outline-none',
              widths[size],
            )}
            initial={{ scale: 0.96, y: 12, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.97, y: 8, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 260, damping: 24 }}
          >
            <header className="flex items-center justify-between border-b border-forge-700 px-5 py-3.5">
              <h2 className="font-display text-sm font-semibold text-forge-100">{title}</h2>
              <button
                onClick={onClose}
                aria-label="Close"
                className="rounded-md p-1 text-forge-400 transition-colors hover:bg-forge-800 hover:text-forge-100"
              >
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="p-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

// ── Tooltip ─────────────────────────────────────────────────────────────────
export function Tooltip({ label, children }: { label: ReactNode; children: ReactNode }) {
  const [show, setShow] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      <AnimatePresence>
        {show && (
          <motion.span
            role="tooltip"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 2 }}
            transition={{ duration: 0.12 }}
            className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-2 w-max max-w-xs
                       -translate-x-1/2 rounded-lg border border-forge-600 bg-forge-850 px-2.5 py-1.5
                       text-xs text-forge-200 shadow-xl"
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

// ── Stat ────────────────────────────────────────────────────────────────────
export function Stat({
  label,
  value,
  hint,
  accent,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="panel px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <span className="stat-label">{label}</span>
        {icon && <span className="text-forge-500">{icon}</span>}
      </div>
      <div className="stat-value mt-1" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-forge-400">{hint}</div>}
    </div>
  );
}
