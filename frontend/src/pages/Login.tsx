import { motion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui';
import { ApiRequestError } from '@/lib/api';
import { useAuth } from '@/stores/game';
import { cn } from '@/lib/utils';

export default function Login() {
  const [params] = useSearchParams();
  const [mode, setMode] = useState<'login' | 'register'>(
    params.get('mode') === 'register' ? 'register' : 'login',
  );
  const [identifier, setIdentifier] = useState('');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const status = useAuth((s) => s.status);
  const login = useAuth((s) => s.login);
  const register = useAuth((s) => s.register);

  if (status === 'authenticated') return <Navigate to="/app" replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      if (mode === 'login') {
        await login(identifier.trim(), password);
      } else {
        await register(email.trim(), username.trim(), password);
      }
    } catch (err) {
      if (err instanceof ApiRequestError) {
        // Field-level messages go next to their input; only the general
        // message goes in the banner. A 422 dumped into one blob is how forms
        // become unusable.
        const fields = err.fieldErrors;
        setFieldErrors(fields);
        setError(Object.keys(fields).length ? null : err.message);
      } else {
        setError('Could not reach the server. Is the backend running?');
      }
    } finally {
      setBusy(false);
    }
  }

  const isRegister = mode === 'register';

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="w-full max-w-md"
      >
        <Link to="/" className="mb-8 flex items-center justify-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-signal-xp">
            <span className="font-display text-sm font-bold text-forge-950">AF</span>
          </div>
          <span className="font-display text-lg font-semibold">AI Forge Labs</span>
        </Link>

        <div className="panel p-6">
          <div className="mb-6 flex gap-1 rounded-lg bg-forge-800/70 p-1">
            {(['login', 'register'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setMode(value);
                  setError(null);
                  setFieldErrors({});
                }}
                className={cn(
                  'relative flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  mode === value ? 'text-forge-950' : 'text-forge-300 hover:text-forge-100',
                )}
              >
                {mode === value && (
                  <motion.span
                    layoutId="auth-tab"
                    className="absolute inset-0 rounded-md bg-accent"
                    transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative">{value === 'login' ? 'Sign in' : 'New engineer'}</span>
              </button>
            ))}
          </div>

          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            {isRegister ? (
              <>
                <Field
                  label="Work email"
                  type="email"
                  value={email}
                  onChange={setEmail}
                  error={fieldErrors.email}
                  autoComplete="email"
                  placeholder="you@example.com"
                />
                <Field
                  label="Username"
                  value={username}
                  onChange={setUsername}
                  error={fieldErrors.username}
                  autoComplete="username"
                  placeholder="how you appear on the leaderboard"
                />
              </>
            ) : (
              <Field
                label="Email or username"
                value={identifier}
                onChange={setIdentifier}
                error={fieldErrors.identifier}
                autoComplete="username"
              />
            )}

            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              error={fieldErrors.password}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              hint={
                isRegister
                  ? '16+ characters, or at least 3 of: lowercase, uppercase, digit, symbol.'
                  : undefined
              }
            />

            {error && (
              <div
                role="alert"
                className="rounded-lg border border-signal-danger/40 bg-signal-danger/10 px-3 py-2 text-sm text-signal-danger"
              >
                {error}
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={busy}
              className="w-full"
              icon={busy ? undefined : <ArrowRight className="h-4 w-4" />}
            >
              {isRegister ? 'Join AI Forge Labs' : 'Sign in'}
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center text-xs leading-relaxed text-forge-500">
          Seeded a local database with <code className="text-forge-400">aiforge bootstrap</code>?
          <br />
          Sign in with{' '}
          <code className="text-forge-400">player@aiforge.dev</code> /{' '}
          <code className="text-forge-400">forge-me-2026</code>
        </p>
      </motion.div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  error,
  hint,
  autoComplete,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  error?: string;
  hint?: string;
  autoComplete?: string;
  placeholder?: string;
}) {
  const id = `field-${label.replace(/\s+/g, '-').toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-forge-300">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cn(
          'w-full rounded-lg border bg-forge-950/70 px-3 py-2 text-sm text-forge-100',
          'placeholder:text-forge-600 transition-colors',
          error
            ? 'border-signal-danger/60 focus:border-signal-danger'
            : 'border-forge-700 focus:border-accent',
        )}
      />
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-signal-danger">
          {error}
        </p>
      )}
      {!error && hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-forge-500">
          {hint}
        </p>
      )}
    </div>
  );
}
