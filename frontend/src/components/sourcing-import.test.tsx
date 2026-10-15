import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { Dialog } from "@/components/ui/dialog";
import SourcingImport from "./sourcing-import";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("protects a pending file read and ignores its completion after unmount", async () => {
  const onDirty = vi.fn(),
    onBusy = vi.fn();
  let finish: ((text: string) => void) | undefined;
  const file = new File(["jobs"], "jobs.csv", { type: "text/csv" });
  Object.defineProperty(file, "text", {
    value: () =>
      new Promise<string>((resolve) => {
        finish = resolve;
      }),
  });
  const view = render(
    <Dialog open>
      <SourcingImport
        snapshot={{ id: 1, revision: "1", columns: [] } as any}
        onSaved={vi.fn()}
        onDirty={onDirty}
        onBusy={onBusy}
      />
    </Dialog>,
  );
  fireEvent.change(screen.getByLabelText("CSV file"), {
    target: { files: [file] },
  });
  expect(onDirty).toHaveBeenCalledWith(true);
  expect(onBusy).toHaveBeenCalledWith(true);
  view.unmount();
  const calls = onDirty.mock.calls.length;
  await act(async () => {
    finish!("Company,Role,Job link\nAcme,Engineer,url");
  });
  expect(onDirty.mock.calls.length).toBe(calls);
});
