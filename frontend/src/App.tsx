import { lazy, Suspense, useEffect } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { Spinner } from '@/components/ui';
import { onAuthFailure } from '@/lib/api';
import { useAuth } from '@/stores/game';

// Route-level code splitting. Monaco alone is ~2MB; loading it on the landing
// page would make first paint dramatically worse for a screen that has no
// editor on it.
const Landing = lazy(() => import('@/pages/Landing'));
const Login = lazy(() => import('@/pages/Login'));
const Dashboard = lazy(() => import('@/pages/Dashboard'));
const WorldMap = lazy(() => import('@/pages/WorldMap'));
const Daily = lazy(() => import('@/pages/Daily'));
const Missions = lazy(() => import('@/pages/Missions'));
const MissionRun = lazy(() => import('@/pages/MissionRun'));
const Practice = lazy(() => import('@/pages/Practice'));
const Workbench = lazy(() => import('@/pages/Workbench'));
const Concepts = lazy(() => import('@/pages/Concepts'));
const ConceptDetail = lazy(() => import('@/pages/ConceptDetail'));
const Interview = lazy(() => import('@/pages/Interview'));
const Retention = lazy(() => import('@/pages/Retention'));
const Skills = lazy(() => import('@/pages/Skills'));
const Mistakes = lazy(() => import('@/pages/Mistakes'));
const Analytics = lazy(() => import('@/pages/Analytics'));
const Achievements = lazy(() => import('@/pages/Achievements'));

function FullPageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner className="h-8 w-8" />
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const status = useAuth((s) => s.status);
  if (status === 'unknown') return <FullPageLoader />;
  if (status === 'anonymous') return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const resolve = useAuth((s) => s.resolve);
  const forceAnonymous = useAuth((s) => s.forceAnonymous);
  const navigate = useNavigate();

  useEffect(() => {
    void resolve();
  }, [resolve]);

  // The API client owns token refresh; when it gives up, the app redirects
  // exactly once rather than every failing component doing its own thing.
  useEffect(
    () =>
      onAuthFailure(() => {
        forceAnonymous();
        navigate('/login', { replace: true });
      }),
    [forceAnonymous, navigate],
  );

  return (
    <Suspense fallback={<FullPageLoader />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="world" element={<WorldMap />} />
          <Route path="daily" element={<Daily />} />
          <Route path="missions" element={<Missions />} />
          <Route path="missions/:slug" element={<MissionRun />} />
          <Route path="practice" element={<Practice />} />
          <Route path="challenge/:slug" element={<Workbench />} />
          <Route path="concepts" element={<Concepts />} />
          <Route path="concepts/:slug" element={<ConceptDetail />} />
          <Route path="interview" element={<Interview />} />
          <Route path="interview/:sessionId" element={<Interview />} />
          <Route path="retention" element={<Retention />} />
          <Route path="skills" element={<Skills />} />
          <Route path="skills/:slug" element={<Skills />} />
          <Route path="mistakes" element={<Mistakes />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="achievements" element={<Achievements />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
