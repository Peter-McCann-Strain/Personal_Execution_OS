import { lazy, Suspense, useState } from "react";
import { Settings, User, Plug, Key, Database, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { ProfileSettings } from "@/components/settings/profile-settings";
import { IntegrationSettings } from "@/components/settings/integration-settings";
import { DataSettings } from "@/components/settings/data-settings";
import { SecuritySettings } from "@/components/settings/security-settings";
import { isLegacyDevAuthEnabled } from "@/lib/auth-mode";

// ─── Section Config ─────────────────────────────────────────

interface SettingsSection {
  id: string;
  label: string;
  icon: LucideIcon;
}

const sections: SettingsSection[] = [
  { id: "profile", label: "Profile", icon: User },
  { id: "integrations", label: "Integrations", icon: Plug },
  { id: "security", label: "Security", icon: ShieldCheck },
  { id: "data", label: "Data", icon: Database },
  ...(isLegacyDevAuthEnabled ? [{ id: "api-keys", label: "API Keys", icon: Key }] : []),
];

const LegacyApiKeySettings = isLegacyDevAuthEnabled
  ? lazy(() =>
      import("@/components/settings/api-key-settings").then((module) => ({
        default: module.ApiKeySettings,
      })),
    )
  : null;

// ─── SettingsPage Component ─────────────────────────────────

function SettingsPage() {
  const [activeSection, setActiveSection] = useState("profile");

  return (
    <PageTransition>
      <div className="flex flex-col gap-6 p-6">
        {/* Header */}
        <PageHeader title="Settings" subtitle="Configure your workspace" icon={Settings} />

        {/* Layout: Sidebar + Content */}
        <div className="flex min-h-[600px] flex-col gap-6 lg:flex-row">
          {/* Sidebar Navigation */}
          <nav className="w-full min-w-0 lg:w-48 lg:shrink-0">
            <div
              className="flex gap-0.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0"
              role="tablist"
              aria-label="Settings sections"
            >
              {sections.map((section) => {
                const Icon = section.icon;
                const isActive = activeSection === section.id;

                return (
                  <button
                    key={section.id}
                    onClick={() => setActiveSection(section.id)}
                    role="tab"
                    aria-selected={isActive}
                    tabIndex={isActive ? 0 : -1}
                    className={cn(
                      "flex shrink-0 items-center gap-2.5 rounded-[var(--radius-md)] px-3 py-2 text-left text-sm font-medium transition-colors",
                      isActive
                        ? "bg-[var(--color-bg-overlay)] text-[var(--color-fg-primary)]"
                        : "text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {section.label}
                  </button>
                );
              })}
            </div>
          </nav>

          {/* Content */}
          <div className="min-w-0 max-w-2xl flex-1">
            {activeSection === "profile" && <ProfileSettings />}

            {activeSection === "integrations" && <IntegrationSettings />}

            {activeSection === "security" && <SecuritySettings />}

            {activeSection === "data" && <DataSettings />}

            {activeSection === "api-keys" && LegacyApiKeySettings && (
              <Suspense
                fallback={
                  <div className="h-40 rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)]" />
                }
              >
                <LegacyApiKeySettings />
              </Suspense>
            )}
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

export { SettingsPage };
