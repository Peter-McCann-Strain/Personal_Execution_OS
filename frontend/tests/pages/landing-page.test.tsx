import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, within } from "../test-utils";
import { LandingPage } from "@/pages/landing";

const mocks = vi.hoisted(() => ({
  useInView: vi.fn(() => false),
}));

vi.mock("motion/react", async () => {
  const React = await vi.importActual<typeof import("react")>("react");
  const motionPropNames = new Set([
    "animate",
    "initial",
    "transition",
    "viewport",
    "whileHover",
    "whileInView",
  ]);

  const motion = new Proxy(
    {},
    {
      get: (_, tag: string) =>
        React.forwardRef<HTMLElement, React.HTMLAttributes<HTMLElement>>(
          ({ children, ...props }, ref) => {
            const domProps = Object.fromEntries(
              Object.entries(props).filter(([name]) => !motionPropNames.has(name)),
            );
            return React.createElement(tag, { ...domProps, ref }, children);
          },
        ),
    },
  );

  return {
    motion,
    useInView: mocks.useInView,
    useScroll: () => ({ scrollYProgress: 0 }),
    useTransform: () => 0,
  };
});

describe("LandingPage", () => {
  beforeEach(() => {
    mocks.useInView.mockReset();
    mocks.useInView.mockReturnValue(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the primary sections, navigation, and CTA links", () => {
    renderWithProviders(<LandingPage />);

    expect(screen.getByRole("link", { name: "Execution OS" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Personal Execution OS/ })).toBeInTheDocument();
    expect(screen.getByText(/One private workspace to capture what matters/i)).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Three Steps to a Calmer Mind" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "8 Focused Workflows, One Workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "An Inspectable Local Data Flow",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "A Modern, Inspectable Stack" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Ready to extend your mind?")).toBeInTheDocument();

    const dashboardLinks = screen.getAllByRole("link", { name: /Go to Dashboard|Dashboard/i });
    expect(dashboardLinks[0]).toHaveAttribute("href", "/dashboard");

    const settingsLinks = screen.getAllByRole("link", { name: /Settings/i });
    expect(settingsLinks[0]).toHaveAttribute("href", "/settings");

    const footer = screen.getByRole("contentinfo");
    expect(within(footer).queryByRole("link", { name: "Source" })).not.toBeInTheDocument();
    expect(
      within(footer).getByText("Personal Execution OS -- self-hosted workspace"),
    ).toBeInTheDocument();

    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Features" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Agents" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Architecture" })).toBeInTheDocument();
  });

  it("animates the hero counters when the stats enter view", async () => {
    mocks.useInView.mockReturnValue(true);
    vi.spyOn(performance, "now").mockReturnValue(0);

    const raf = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback: FrameRequestCallback) => {
        Promise.resolve().then(() => callback(3_000));
        return 1;
      });

    renderWithProviders(<LandingPage />);

    expect(await screen.findByText("8")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(raf).toHaveBeenCalled();
  });
});
