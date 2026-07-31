import { Children, isValidElement, type ReactNode } from "react";

type ChartProps = {
  children?: ReactNode;
  [key: string]: unknown;
};

function passthrough({ children }: ChartProps) {
  const filteredChildren = Children.map(children as ReactNode, (child) => {
    if (isValidElement(child) && typeof child.type === "string") {
      return null;
    }
    return child;
  });
  return <div>{filteredChildren}</div>;
}

function mockAxis(props: ChartProps) {
  const tickFormatter = props.tickFormatter as ((value: number) => unknown) | undefined;

  tickFormatter?.(1234);
  tickFormatter?.(12.34);
  return null;
}

function mockTooltip(props: ChartProps) {
  const formatter = props.formatter as
    ((value: unknown, name?: string, entry?: unknown) => unknown) | undefined;
  const content = props.content as
    | ReactNode
    | ((payload: {
        active?: boolean;
        payload?: Array<{ value: number; name: string; color: string }>;
        label?: string;
      }) => ReactNode)
    | undefined;

  formatter?.(123.456, "value", { value: 123.456, name: "value" });
  formatter?.([123.456, "value"], "value", { value: [123.456, "value"], name: "value" });
  const tooltipProps = {
    active: true,
    label: "2026-04-01",
    payload: [
      { value: 6.5, name: "Mood", color: "#111" },
      { value: 4.2, name: "Energy", color: "#222" },
    ],
  };

  if (typeof content === "function") {
    return <div>{content(tooltipProps)}</div>;
  }

  if (isValidElement(content) && typeof content.type === "function") {
    const Content = content.type as (props: Record<string, unknown>) => ReactNode;
    return <div>{Content({ ...(content.props as object), ...tooltipProps })}</div>;
  }

  return null;
}

function mockLegend(props: ChartProps) {
  const formatter = props.formatter as ((value: string) => ReactNode) | undefined;
  formatter?.("Diary");
  return null;
}

function mockPie(props: ChartProps) {
  const label = props.label as
    ((payload: { name?: unknown; percent?: number }) => unknown) | undefined;

  label?.({ name: "diary", percent: 0.5 });
  label?.({ name: undefined, percent: undefined });
  return <div>{props.children as ReactNode}</div>;
}

function mockCell(props: ChartProps) {
  return <span data-testid="recharts-cell" data-fill={String(props.fill ?? "")} />;
}

export const rechartsMock = {
  ResponsiveContainer: passthrough,
  PieChart: passthrough,
  Pie: mockPie,
  Cell: mockCell,
  Tooltip: mockTooltip,
  Legend: mockLegend,
  AreaChart: passthrough,
  Area: passthrough,
  BarChart: passthrough,
  Bar: passthrough,
  XAxis: mockAxis,
  YAxis: mockAxis,
  CartesianGrid: () => null,
};
