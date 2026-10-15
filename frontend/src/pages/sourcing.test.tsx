import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import SourcingPage from "./sourcing";
import { api } from "@/lib/api";
vi.mock("@/components/auth", () => ({ useAuth: () => ({ role: "admin" }) }));
vi.mock("@/components/sourcing-grid", () => ({
  SheetGrid: ({
    snapshot,
    changes,
    onChange,
    disabled,
    onEditingChange,
  }: {
    snapshot: { rows: { value: string }[][] };
    changes: { value: string }[];
    onChange: (changes: unknown[]) => void;
    disabled: boolean;
    onEditingChange?: (active: boolean) => void;
  }) => (
    <div>
      <output aria-label="Saved company">{snapshot.rows[1]?.[0]?.value}</output>
      <output aria-label="Draft value">
        {changes[0]?.value || "No draft"}
      </output>
      <button
        disabled={disabled}
        onClick={() => onChange([{ row: 1, col: 0, value: "New company" }])}
      >
        Edit company
      </button>
      <button
        disabled={disabled}
        onClick={() => onChange([{ row: 1, col: 1, value: "Engineer" }])}
      >
        Edit role
      </button>
      <button onClick={() => onEditingChange?.(true)}>Start typing</button>
    </div>
  ),
}));
const snapshot = {
  row_ids: ["", "row-one"],
  columns: [{ id: "company", title: "Company", kind: "company", width: 220 }],
  structure_revision: 1,
  rows: [
    [],
    [
      {
        value: "Acme",
        display: "Acme",
        formula: false,
        link: "",
        version: 1,
        style: {},
      },
    ],
  ],
  title: "Profile",
  revision: "one",
  refreshed_at: 1,
  properties: { gridProperties: { rowCount: 2, columnCount: 1 } },
};
const index = {
  books: [
    {
      id: 1,
      bidder_id: 1,
      name: "Alex",
      title: "Applications",
      tabs: [{ id: 1, account_id: 1, title: "Profile", header_row: 1 }],
    },
  ],
};
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => (url === "/api/sourcing" ? index : snapshot),
    })),
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((c) => c.clear());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SourcingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it("keeps failed-save drafts visible and prevents tab changes", async () => {
  vi.spyOn(api, "post").mockRejectedValue(
    new Error("Another person changed this cell."),
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit company" }));
  await screen.findByText(
    /Another person changed this cell/,
    {},
    { timeout: 3000 },
  );
  expect(screen.getByLabelText("Draft value").textContent).toBe("New company");
  expect(
    screen.getByRole("tab", { name: "Profile" }).hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen
      .getByRole("button", { name: "Edit company" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(screen.getByRole("button", { name: "Download draft" })).toBeTruthy();
});
it("undoes an acknowledged edit through another revision-checked write", async () => {
  const post = vi
    .spyOn(api, "post")
    .mockResolvedValue({
      ...snapshot,
      revision: "two",
      rows: [
        [],
        [
          {
            value: "New company",
            display: "New company",
            formula: false,
            link: "",
            version: 2,
            style: {},
          },
        ],
      ],
    });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit company" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1), { timeout: 2500 });
  await screen.findByText("Saved");
  fireEvent.click(screen.getByRole("button", { name: "Undo edit" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2), { timeout: 2500 });
  expect(post.mock.calls[1][1]).toMatchObject({
    changes: [
      {
        row_id: "row-one",
        column_id: "company",
        expected_version: 2,
        value: "Acme",
      },
    ],
  });
});
it("clears undo when a clean refresh brings external changes", async () => {
  vi.spyOn(api, "post").mockResolvedValue({
    ...snapshot,
    revision: "two",
    rows: [
      [],
      [
        {
          value: "New company",
          display: "New company",
          formula: false,
          link: "",
          version: 2,
          style: {},
        },
      ],
    ],
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit company" }));
  await screen.findByText("Saved", {}, { timeout: 3000 });
  expect(
    screen.getByRole("button", { name: "Undo edit" }).hasAttribute("disabled"),
  ).toBe(false);
  vi.mocked(fetch).mockImplementation(
    async () =>
      ({
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({
          ...snapshot,
          revision: "external-sort",
          rows: [
            [],
            [
              {
                value: "Another job",
                display: "Another job",
                formula: false,
                link: "",
                version: 1,
                style: {},
              },
            ],
          ],
        }),
      }) as Response,
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh sheet" }));
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Undo edit" })
        .hasAttribute("disabled"),
    ).toBe(true),
  );
});

it("saves a native cell using its stable row and column identity", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue(snapshot);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit company" }));
  await waitFor(() => expect(post).toHaveBeenCalled(), { timeout: 2500 });
  expect(post.mock.calls[0][1]).toMatchObject({
    changes: [
      {
        row_id: "row-one",
        column_id: "company",
        expected_version: 1,
        value: "New company",
      },
    ],
  });
});

it("does not replace an acknowledged save with an older pending refresh", async () => {
  const result = {
    ...snapshot,
    revision: "two",
    rows: [
      [],
      [
        {
          ...snapshot.rows[1][0],
          value: "New company",
          display: "New company",
          version: 2,
        },
      ],
    ],
  };
  vi.spyOn(api, "post").mockResolvedValue(result);
  mount();
  await screen.findByRole("button", { name: "Edit company" });
  let finish: ((value: Response) => void) | undefined;
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent(window, new Event("focus"));
  await waitFor(() => expect(finish).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "Edit company" }));
  await waitFor(
    () =>
      expect(screen.getByLabelText("Saved company").textContent).toBe(
        "New company",
      ),
    { timeout: 2500 },
  );
  await act(async () => {
    finish!({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => snapshot,
    } as Response);
  });
  expect(screen.getByLabelText("Saved company").textContent).toBe(
    "New company",
  );
});
it("clears unsafe undo when a merged save brings another person’s cell edit", async () => {
  const columns = [
    ...snapshot.columns,
    { id: "role", title: "Role", kind: "role", width: 220 },
  ];
  const initial = {
    ...snapshot,
    columns,
    rows: [
      [],
      [snapshot.rows[1][0], { value: "", display: "", version: 0, style: {} }],
    ],
  };
  vi.mocked(fetch).mockImplementation(
    async (url) =>
      ({
        ok: true,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => (url === "/api/sourcing" ? index : initial),
      }) as Response,
  );
  const saved = {
    ...initial,
    revision: "two",
    rows: [
      [],
      [
        { ...snapshot.rows[1][0], value: "New company", version: 2 },
        initial.rows[1][1],
      ],
    ],
  };
  const merged = {
    ...initial,
    revision: "four",
    rows: [
      [],
      [
        { ...snapshot.rows[1][0], value: "Remote company", version: 3 },
        { ...initial.rows[1][1], value: "Engineer", version: 1 },
      ],
    ],
  };
  const post = vi
    .spyOn(api, "post")
    .mockResolvedValueOnce(saved)
    .mockResolvedValueOnce(merged);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit company" }));
  await waitFor(
    () =>
      expect(screen.getByLabelText("Saved company").textContent).toBe(
        "New company",
      ),
    { timeout: 2500 },
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit role" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2), { timeout: 2500 });
  await waitFor(() =>
    expect(screen.getByLabelText("Saved company").textContent).toBe(
      "Remote company",
    ),
  );
  expect(
    screen.getByRole("button", { name: "Undo edit" }).hasAttribute("disabled"),
  ).toBe(true);
});
it("protects active uncommitted typing from refresh and navigation", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Start typing" }));
  expect(
    screen
      .getByRole("button", { name: "Refresh sheet" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(
    screen.getByRole("tab", { name: "Profile" }).hasAttribute("disabled"),
  ).toBe(true);
  const requests = vi.mocked(fetch).mock.calls.length;
  fireEvent(window, new Event("focus"));
  await act(async () => {});
  expect(vi.mocked(fetch).mock.calls.length).toBe(requests);
});
it("keeps original row identity and revision in a deletion confirmation", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue(snapshot);
  mount();
  await screen.findByRole("button", { name: "Edit company" });
  fireEvent.change(screen.getByLabelText("Row and column actions"), {
    target: { value: "delete_rows" },
  });
  const refreshed = {
    ...snapshot,
    revision: "inserted",
    structure_revision: 2,
    row_ids: ["", "new-row", "row-one"],
    rows: [
      [],
      [{ ...snapshot.rows[1][0], value: "Inserted" }],
      snapshot.rows[1],
    ],
  };
  vi.mocked(fetch).mockResolvedValue({
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => refreshed,
  } as Response);
  fireEvent(window, new Event("focus"));
  await waitFor(() =>
    expect(screen.getByLabelText("Saved company").textContent).toBe("Inserted"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(post.mock.calls[0][1]).toMatchObject({
    revision: "one",
    ids: ["row-one"],
  });
});

it("waits to autosave committed cells while another cell is still being typed", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue(snapshot);
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit company" }));
  fireEvent.click(screen.getByRole("button", { name: "Start typing" }));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 1400));
  });
  expect(post).not.toHaveBeenCalled();
});

it("confirms discarding pasted append rows and unlocks the sheet after closing", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  mount();
  await screen.findByRole("button", { name: "Edit company" });
  fireEvent.change(screen.getByLabelText("Row and column actions"), {
    target: { value: "append_jobs" },
  });
  fireEvent.change(screen.getByLabelText("Job rows to append"), {
    target: { value: "Draft company\tEngineer" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByLabelText("Job rows to append")).toBeTruthy();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() =>
    expect(screen.queryByLabelText("Job rows to append")).toBeNull(),
  );
  expect(
    screen.getByLabelText("Row and column actions").hasAttribute("disabled"),
  ).toBe(false);
});
