import { useState } from "react";
import { Sun, Moon, Monitor } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAppStore } from "@/stores/app";

// ─── Timezone Options (common subset) ───────────────────────

const timezones = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Australia/Sydney",
  "Pacific/Auckland",
];

// ─── ProfileSettings Component ──────────────────────────────

function ProfileSettings() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const profileSettings = useAppStore((s) => s.profileSettings);
  const setProfileSettings = useAppStore((s) => s.setProfileSettings);

  const [displayName, setDisplayName] = useState(profileSettings.displayName);
  const [timezone, setTimezone] = useState(profileSettings.timezone);
  const [workStart, setWorkStart] = useState(profileSettings.workStart);
  const [workEnd, setWorkEnd] = useState(profileSettings.workEnd);

  const hasChanges =
    displayName !== profileSettings.displayName ||
    timezone !== profileSettings.timezone ||
    workStart !== profileSettings.workStart ||
    workEnd !== profileSettings.workEnd;

  const handleSave = () => {
    const nextSettings = {
      displayName: displayName.trim() || "Owner",
      timezone,
      workStart,
      workEnd,
    };
    setProfileSettings(nextSettings);
    setDisplayName(nextSettings.displayName);
    toast.success("Profile settings saved");
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Appearance */}
      <Card padding="lg">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">Appearance</h3>
        <div className="flex flex-col gap-4">
          <div>
            <label className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider mb-2 block">
              Theme
            </label>
            <div className="flex items-center gap-2">
              <ThemeButton
                icon={Moon}
                label="Dark"
                isActive={theme === "dark"}
                onClick={() => setTheme("dark")}
              />
              <ThemeButton
                icon={Sun}
                label="Light"
                isActive={theme === "light"}
                onClick={() => setTheme("light")}
              />
              <ThemeButton
                icon={Monitor}
                label="System"
                isActive={theme === "system"}
                onClick={() => setTheme("system")}
              />
            </div>
          </div>
        </div>
      </Card>

      {/* Profile */}
      <Card padding="lg">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">Profile</h3>
        <div className="flex flex-col gap-4">
          <div>
            <label
              htmlFor="profile-display-name"
              className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider mb-1.5 block"
            >
              Display Name
            </label>
            <Input
              id="profile-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={50}
              placeholder="Your name"
              className="max-w-xs"
            />
          </div>

          <div>
            <label
              htmlFor="profile-timezone"
              className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider mb-1.5 block"
            >
              Timezone
            </label>
            <select
              id="profile-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className="h-9 max-w-xs w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
            >
              {timezones.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {/* Working Hours */}
      <Card padding="lg">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)] mb-4">Working Hours</h3>
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-4">
            <div>
              <label
                htmlFor="profile-work-start"
                className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider mb-1.5 block"
              >
                Start
              </label>
              <Input
                id="profile-work-start"
                type="time"
                value={workStart}
                onChange={(e) => setWorkStart(e.target.value)}
                className="w-32"
              />
            </div>
            <div>
              <label
                htmlFor="profile-work-end"
                className="text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider mb-1.5 block"
              >
                End
              </label>
              <Input
                id="profile-work-end"
                type="time"
                value={workEnd}
                onChange={(e) => setWorkEnd(e.target.value)}
                className="w-32"
              />
            </div>
          </div>
          <p className="text-xs text-[var(--color-fg-tertiary)]">
            Used to frame daily planning and briefing schedules.
          </p>
        </div>
      </Card>

      {/* Save */}
      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={!hasChanges}>
          Save Changes
        </Button>
      </div>
    </div>
  );
}

// ─── ThemeButton ────────────────────────────────────────────

interface ThemeButtonProps {
  icon: LucideIcon;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

function ThemeButton({ icon: Icon, label, isActive, onClick }: ThemeButtonProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 px-4 py-2.5 rounded-[var(--radius-md)] border text-sm font-medium transition-colors",
        isActive
          ? "border-[var(--color-info-500)] bg-[var(--color-info-50)] text-[var(--color-fg-primary)]"
          : "border-[var(--color-border-default)] text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-secondary)]",
      )}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

export { ProfileSettings };
