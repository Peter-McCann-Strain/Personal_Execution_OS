import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

const createBrowserRouterMock = vi.fn(() => "router-instance");
const routerProviderMock = vi.fn(({ router }: { router: unknown }) => (
  <div>Router provider {String(router)}</div>
));
const navigateMock = vi.fn(({ to }: { to: string }) => <div>Navigate to {to}</div>);

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    Navigate: (props: { to: string }) => navigateMock(props),
    createBrowserRouter: (routes: unknown) => createBrowserRouterMock(routes),
  };
});

vi.mock("react-router/dom", () => ({
  RouterProvider: (props: { router: unknown }) => routerProviderMock(props),
}));

vi.mock("@/components/layout/app-layout", () => ({
  AppLayout: () => <div>App layout</div>,
}));

vi.mock("@/components/ui/error-boundary", () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe("AppRouter runtime", () => {
  it("builds the browser router with the expected route tree and renders the provider", async () => {
    const { AppRouter } = await import("@/router");

    expect(createBrowserRouterMock).toHaveBeenCalledTimes(1);
    const routes = createBrowserRouterMock.mock.calls[0]?.[0] as Array<{
      path: string;
      children?: Array<{ path?: string; index?: boolean }>;
    }>;

    expect(routes).toHaveLength(6);
    expect(routes[0]?.path).toBe("/welcome");
    expect(routes[1]?.path).toBe("/setup");
    expect(routes[2]?.path).toBe("/login");
    expect(routes[3]?.path).toBe("/sign-in/*");
    expect(routes[4]?.path).toBe("/sign-up/*");
    expect(routes[5]?.path).toBe("/");
    expect(routes[5]?.children).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ index: true }),
        expect.objectContaining({ path: "dashboard" }),
        expect.objectContaining({ path: "chat" }),
        expect.objectContaining({ path: "notes" }),
        expect.objectContaining({ path: "workbench" }),
        expect.objectContaining({ path: "tutorials" }),
        expect.objectContaining({ path: "*" }),
      ]),
    );

    render(<AppRouter />);

    expect(routerProviderMock).toHaveBeenCalledWith(
      expect.objectContaining({ router: "router-instance" }),
    );
  });
});
