import { describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { SortMenu } from "@/components/ui/sort-menu";

describe("SortMenu", () => {
  it("opens, selects an option, and closes again", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    renderWithProviders(
      <SortMenu
        value="newest"
        options={[
          { value: "newest", label: "Newest first" },
          { value: "oldest", label: "Oldest first" },
        ]}
        onChange={onChange}
        buttonLabel="Newest first"
        buttonAriaLabel="Sort notes"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Sort notes" }));
    expect(screen.getByRole("listbox", { name: "Sort options" })).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: "Oldest first" }));
    expect(onChange).toHaveBeenCalledWith("oldest");
    expect(screen.queryByRole("listbox", { name: "Sort options" })).not.toBeInTheDocument();
  });

  it("closes on escape and overlay click", async () => {
    const user = userEvent.setup();

    const { container } = renderWithProviders(
      <SortMenu
        value="name"
        options={[
          { value: "name", label: "Name" },
          { value: "score", label: "Score" },
        ]}
        onChange={vi.fn()}
        buttonLabel="Name"
        buttonAriaLabel="Sort contacts"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Sort contacts" }));
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "Sort options" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Sort contacts" }));
    const overlay = container.querySelector(".fixed.inset-0.z-40");
    expect(overlay).not.toBeNull();
    if (overlay instanceof HTMLElement) {
      act(() => {
        overlay.click();
      });
    }
    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "Sort options" })).not.toBeInTheDocument();
    });
  });

  it("uses the custom menu label and closes from the menu keydown handler", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <SortMenu
        value="newest"
        options={[
          { value: "newest", label: "Newest first" },
          { value: "oldest", label: "Oldest first" },
        ]}
        onChange={vi.fn()}
        buttonLabel="Newest first"
        buttonAriaLabel="Sort entries"
        menuLabel="Diary sort options"
        widthClassName="w-56"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Sort entries" }));
    const listbox = screen.getByRole("listbox", { name: "Diary sort options" });
    expect(listbox).toHaveClass("w-56");
    expect(screen.getByRole("option", { name: "Newest first" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    act(() => {
      listbox.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });

    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "Diary sort options" })).not.toBeInTheDocument();
    });
  });

  it("keeps the menu open for non-escape keys and removes listeners on unmount", async () => {
    const user = userEvent.setup();
    const addEventListenerSpy = vi.spyOn(window, "addEventListener");
    const removeEventListenerSpy = vi.spyOn(window, "removeEventListener");

    const { unmount } = renderWithProviders(
      <SortMenu
        value="name"
        options={[
          { value: "name", label: "Name" },
          { value: "score", label: "Score" },
        ]}
        onChange={vi.fn()}
        buttonLabel="Name"
        buttonAriaLabel="Sort entities"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Sort entities" }));
    const listbox = screen.getByRole("listbox", { name: "Sort options" });

    act(() => {
      listbox.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });

    expect(screen.getByRole("listbox", { name: "Sort options" })).toBeInTheDocument();
    expect(addEventListenerSpy).toHaveBeenCalledWith("keydown", expect.any(Function));

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  });
});
