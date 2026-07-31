import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { SearchInput } from "@/components/memory/search-input";

describe("SearchInput", () => {
  it("autofocuses and submits on Enter when the query is non-empty", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onSubmit = vi.fn();

    renderWithProviders(
      <SearchInput value="rag evaluation" onChange={onChange} onSubmit={onSubmit} />,
    );

    const input = screen.getByPlaceholderText(
      "Ask anything about your notes, diary, or knowledge...",
    );

    expect(input).toHaveFocus();

    await user.type(input, "{enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("calls onChange when the user edits or clears the input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onSubmit = vi.fn();

    renderWithProviders(
      <SearchInput value="existing query" onChange={onChange} onSubmit={onSubmit} />,
    );

    const input = screen.getByPlaceholderText(
      "Ask anything about your notes, diary, or knowledge...",
    );

    await user.type(input, "!");
    expect(onChange).toHaveBeenCalledWith("existing query!");

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onChange).toHaveBeenCalledWith("");
    expect(input).toHaveFocus();
  });

  it("disables the search button when empty or loading", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onSubmit = vi.fn();

    const { rerender } = renderWithProviders(
      <SearchInput value="   " onChange={onChange} onSubmit={onSubmit} />,
    );

    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();

    rerender(
      <SearchInput value="find this" onChange={onChange} onSubmit={onSubmit} loading={true} />,
    );

    const searchButton = screen.getByRole("button", { name: "Search" });
    expect(searchButton).toBeDisabled();

    await user.click(searchButton);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
