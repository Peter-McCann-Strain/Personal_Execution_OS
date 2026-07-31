import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate } from "react-router";
import { RouterProvider } from "react-router/dom";
import { AuthGate } from "@/components/auth/auth-gate";
import { AppLayout } from "@/components/layout/app-layout";
import { ErrorBoundary } from "@/components/ui/error-boundary";

const LandingPage = lazy(() => import("@/pages/landing").then((m) => ({ default: m.LandingPage })));
const SetupPage = lazy(() => import("@/pages/setup").then((m) => ({ default: m.SetupPage })));
const LoginPage = lazy(() => import("@/pages/auth").then((m) => ({ default: m.LoginPage })));
const DashboardPage = lazy(() =>
  import("@/pages/dashboard").then((m) => ({ default: m.DashboardPage })),
);
const PulsePage = lazy(() => import("@/pages/pulse").then((m) => ({ default: m.PulsePage })));
const ChatPage = lazy(() => import("@/pages/chat").then((m) => ({ default: m.ChatPage })));
const DiaryPage = lazy(() => import("@/pages/diary").then((m) => ({ default: m.DiaryPage })));
const MemoryPage = lazy(() => import("@/pages/memory").then((m) => ({ default: m.MemoryPage })));
const WorkbenchPage = lazy(() =>
  import("@/pages/workbench").then((m) => ({ default: m.WorkbenchPage })),
);
const ProjectsPage = lazy(() =>
  import("@/pages/projects").then((m) => ({ default: m.ProjectsPage })),
);
const GoalsPage = lazy(() => import("@/pages/goals").then((m) => ({ default: m.GoalsPage })));
const ReviewsPage = lazy(() => import("@/pages/reviews").then((m) => ({ default: m.ReviewsPage })));
const ContactsPage = lazy(() =>
  import("@/pages/contacts").then((m) => ({ default: m.ContactsPage })),
);
const CalendarPage = lazy(() =>
  import("@/pages/calendar").then((m) => ({ default: m.CalendarPage })),
);
const EmailPage = lazy(() => import("@/pages/email").then((m) => ({ default: m.EmailPage })));
const NotificationsPage = lazy(() =>
  import("@/pages/notifications").then((m) => ({ default: m.NotificationsPage })),
);
const MonitoringPage = lazy(() =>
  import("@/pages/monitoring").then((m) => ({ default: m.MonitoringPage })),
);
const SettingsPage = lazy(() =>
  import("@/pages/settings").then((m) => ({ default: m.SettingsPage })),
);
const KnowledgeGraphPage = lazy(() =>
  import("@/pages/knowledge-graph").then((m) => ({ default: m.KnowledgeGraphPage })),
);
const NotesPage = lazy(() => import("@/pages/notes").then((m) => ({ default: m.NotesPage })));
const CommitmentsPage = lazy(() =>
  import("@/pages/commitments").then((m) => ({ default: m.CommitmentsPage })),
);
const HabitsPage = lazy(() => import("@/pages/habits").then((m) => ({ default: m.HabitsPage })));
const DecisionsPage = lazy(() =>
  import("@/pages/decisions").then((m) => ({ default: m.DecisionsPage })),
);
const TutorialsPage = lazy(() =>
  import("@/pages/tutorials").then((m) => ({ default: m.TutorialsPage })),
);

function PageSuspense({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense
        fallback={
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="w-8 h-8 border-2 border-[var(--color-border-default)] border-t-[var(--color-fg-secondary)] rounded-full animate-spin" />
          </div>
        }
      >
        {children}
      </Suspense>
    </ErrorBoundary>
  );
}

const router = createBrowserRouter([
  // Landing page — standalone, no app layout
  {
    path: "/welcome",
    element: (
      <ErrorBoundary>
        <Suspense fallback={<div className="min-h-screen bg-[var(--color-bg-base)]" />}>
          <LandingPage />
        </Suspense>
      </ErrorBoundary>
    ),
  },
  // First-run setup — standalone, public, no auth guard
  {
    path: "/setup",
    element: (
      <ErrorBoundary>
        <Suspense fallback={<div className="min-h-screen bg-[var(--color-bg-base)]" />}>
          <SetupPage />
        </Suspense>
      </ErrorBoundary>
    ),
  },
  {
    path: "/login",
    element: (
      <ErrorBoundary>
        <Suspense fallback={<div className="min-h-screen bg-[var(--color-bg-base)]" />}>
          <LoginPage />
        </Suspense>
      </ErrorBoundary>
    ),
  },
  {
    path: "/sign-in/*",
    element: <Navigate to="/login" replace />,
  },
  {
    path: "/sign-up/*",
    element: <Navigate to="/login" replace />,
  },
  // App routes — wrapped in AppLayout (sidebar, header)
  {
    path: "/",
    element: (
      <AuthGate>
        <AppLayout />
      </AuthGate>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      {
        path: "dashboard",
        element: (
          <PageSuspense>
            <DashboardPage />
          </PageSuspense>
        ),
      },
      {
        path: "pulse",
        element: (
          <PageSuspense>
            <PulsePage />
          </PageSuspense>
        ),
      },
      {
        path: "chat",
        element: (
          <PageSuspense>
            <ChatPage />
          </PageSuspense>
        ),
      },
      {
        path: "diary",
        element: (
          <PageSuspense>
            <DiaryPage />
          </PageSuspense>
        ),
      },
      {
        path: "memory",
        element: (
          <PageSuspense>
            <MemoryPage />
          </PageSuspense>
        ),
      },
      {
        path: "knowledge-graph",
        element: (
          <PageSuspense>
            <KnowledgeGraphPage />
          </PageSuspense>
        ),
      },
      {
        path: "notes",
        element: (
          <PageSuspense>
            <NotesPage />
          </PageSuspense>
        ),
      },
      {
        path: "workbench",
        element: (
          <PageSuspense>
            <WorkbenchPage />
          </PageSuspense>
        ),
      },
      {
        path: "projects",
        element: (
          <PageSuspense>
            <ProjectsPage />
          </PageSuspense>
        ),
      },
      {
        path: "goals",
        element: (
          <PageSuspense>
            <GoalsPage />
          </PageSuspense>
        ),
      },
      {
        path: "reviews",
        element: (
          <PageSuspense>
            <ReviewsPage />
          </PageSuspense>
        ),
      },
      {
        path: "habits",
        element: (
          <PageSuspense>
            <HabitsPage />
          </PageSuspense>
        ),
      },
      {
        path: "commitments",
        element: (
          <PageSuspense>
            <CommitmentsPage />
          </PageSuspense>
        ),
      },
      {
        path: "decisions",
        element: (
          <PageSuspense>
            <DecisionsPage />
          </PageSuspense>
        ),
      },
      {
        path: "contacts",
        element: (
          <PageSuspense>
            <ContactsPage />
          </PageSuspense>
        ),
      },
      {
        path: "calendar",
        element: (
          <PageSuspense>
            <CalendarPage />
          </PageSuspense>
        ),
      },
      {
        path: "email",
        element: (
          <PageSuspense>
            <EmailPage />
          </PageSuspense>
        ),
      },
      {
        path: "tutorials",
        element: (
          <PageSuspense>
            <TutorialsPage />
          </PageSuspense>
        ),
      },
      {
        path: "notifications",
        element: (
          <PageSuspense>
            <NotificationsPage />
          </PageSuspense>
        ),
      },
      {
        path: "monitoring",
        element: (
          <PageSuspense>
            <MonitoringPage />
          </PageSuspense>
        ),
      },
      {
        path: "settings",
        element: (
          <PageSuspense>
            <SettingsPage />
          </PageSuspense>
        ),
      },
      // Catch-all — redirect unknown paths to dashboard
      { path: "*", element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
