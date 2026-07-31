import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../test-utils";
import { SettingsPage } from "@/pages/settings";

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ title, subtitle }: { title: string; subtitle: string }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

vi.mock("@/components/settings/profile-settings", () => ({
  ProfileSettings: () => <div>Profile Settings Panel</div>,
}));

vi.mock("@/components/settings/integration-settings", () => ({
  IntegrationSettings: () => <div>Integration Settings Panel</div>,
}));

vi.mock("@/components/settings/api-key-settings", () => ({
  ApiKeySettings: () => <div>API Key Settings Panel</div>,
}));

vi.mock("@/components/settings/data-settings", () => ({
  DataSettings: () => <div>Data Settings Panel</div>,
}));

vi.mock("@/components/settings/security-settings", () => ({
  SecuritySettings: () => <div>Security Settings Panel</div>,
}));

describe("SettingsPage", () => {
  it("renders settings sections and switches between tabs", async () => {
    const user = userEvent.setup();

    renderWithProviders(<SettingsPage />);

    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("Configure your workspace")).toBeInTheDocument();
    expect(screen.getByText("Profile Settings Panel")).toBeInTheDocument();

    expect(screen.queryByRole("tab", { name: "AI Agents" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Notifications" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Integrations" }));
    expect(screen.getByText("Integration Settings Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Security" }));
    expect(screen.getByText("Security Settings Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Data" }));
    expect(screen.getByText("Data Settings Panel")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "API Keys" }));
    expect(await screen.findByText("API Key Settings Panel")).toBeInTheDocument();
  });
});
