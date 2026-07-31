import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

// Mock motion/react to avoid animation issues in tests
vi.mock("motion/react", () => ({
  motion: new Proxy(
    {},
    {
      get: (_target, prop) => {
        // Return a forwardRef component that renders the HTML element
        const Component = ({ children, ...props }: Record<string, unknown>) => {
          // Strip motion-specific props
          const htmlProps: Record<string, unknown> = {};
          for (const [key, value] of Object.entries(props)) {
            if (
              ![
                "initial",
                "animate",
                "exit",
                "transition",
                "variants",
                "whileHover",
                "whileTap",
                "whileInView",
                "viewport",
                "layout",
                "layoutId",
              ].includes(key)
            ) {
              htmlProps[key] = value;
            }
          }
          // Create element using the prop name as tag
          const tag = typeof prop === "string" ? prop : "div";
          const Element = tag as unknown as React.ElementType;
          return <Element {...htmlProps}>{children as React.ReactNode}</Element>;
        };
        Component.displayName = `motion.${String(prop)}`;
        return Component;
      },
    },
  ),
  AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
  useInView: () => true,
  useScroll: () => ({ scrollYProgress: { get: () => 0 } }),
  useTransform: () => 0,
}));

// Mock IntersectionObserver
class MockIntersectionObserver {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}
Object.defineProperty(window, "IntersectionObserver", {
  value: MockIntersectionObserver,
});

// Mock ResizeObserver
class MockResizeObserver {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}
Object.defineProperty(window, "ResizeObserver", {
  value: MockResizeObserver,
});

// Mock matchMedia
Object.defineProperty(window, "matchMedia", {
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
