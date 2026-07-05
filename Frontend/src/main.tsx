import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import * as Sentry from '@sentry/react'
import './index.css'
import App from './App.tsx'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Optional — only active when VITE_SENTRY_DSN is set (e.g. unset in local
// dev). environment distinguishes prod vs staging within the same Sentry
// project rather than needing separate projects per environment.
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'development',
  })

  // TEMPORARY - remove after confirming Sentry captures this. Calls
  // captureException directly (bypassing window.onerror entirely) so a
  // console-eval'd throw not propagating to the global handler can't be
  // mistaken for a broken integration. Visit ?sentry-test=1 to trigger.
  if (new URLSearchParams(window.location.search).get('sentry-test')) {
    Sentry.captureException(new Error('Sentry frontend test - safe to ignore, temporary'))
  }
}

const queryClient = new QueryClient();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)

