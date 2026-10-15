import { useState } from "react";
import { api } from "@/lib/api";
import type { Index } from "@/lib/sourcing";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
export default function SourcingSettings({
  index,
  refresh,
}: {
  index: Index;
  refresh: () => void;
}) {
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<unknown>, success = "Saved") => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      refresh();
      setMessage(success);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <DialogContent className="sourcing-settings">
      <DialogTitle>Job sourcing settings</DialogTitle>
      <DialogDescription>
        Manage bidder workbooks, profile sheets and individual sign-in.
      </DialogDescription>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <section>
        <h3>Workbooks</h3>
        <p>
          Each bidder has one workbook. Sheets are saved directly in mail-check.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            void run(
              () =>
                api.post("/api/sourcing/books", {
                  bidder_id: Number(data.get("bidder_id")),
                  title: data.get("title"),
                }),
              "Workbook created",
            );
          }}
        >
          <label>
            Bidder
            <select required name="bidder_id">
              <option value="">Choose bidder</option>
              {index.bidders
                ?.filter(
                  (b) => !index.books.some((book) => book.bidder_id === b.id),
                )
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Workbook name
            <input
              name="title"
              defaultValue="Applications"
              maxLength={100}
              required
            />
          </label>
          <Button disabled={busy}>Create workbook</Button>
        </form>
        {index.books.map((book) => (
          <details className="book-mapping" key={book.id}>
            <summary>
              {book.name} · {book.title}
            </summary>
            {book.tabs.map((tab) => (
              <div className="sheet-actions" key={tab.id}>
                <div>
                  <strong>{tab.title}</strong>
                  <p>
                    {tab.account_label || "Historical profile"}
                    {tab.archived ? " · Archived" : ""}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    if (
                      !tab.archived &&
                      !window.confirm(
                        "Archive this sheet? Its jobs stay saved and can be restored here.",
                      )
                    )
                      return;
                    void run(
                      () =>
                        api.post(`/api/sourcing/tabs/${tab.id}/archive`, {
                          archived: !tab.archived,
                        }),
                      tab.archived ? "Sheet restored" : "Sheet archived",
                    );
                  }}
                >
                  {tab.archived ? "Restore" : "Archive"}
                </Button>
              </div>
            ))}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const data = new FormData(e.currentTarget);
                void run(
                  () =>
                    api.post(`/api/sourcing/books/${book.id}/tabs`, {
                      account_id: Number(data.get("account_id")),
                      title: data.get("title"),
                    }),
                  "Profile sheet created",
                );
              }}
            >
              <label>
                Assigned profile
                <select required name="account_id">
                  <option value="">Choose profile</option>
                  {index.accounts
                    ?.filter(
                      (a) =>
                        !book.tabs.some((t) => t.account_id === a.id) &&
                        index.assignments?.some(
                          (s) =>
                            s.bidder_id === book.bidder_id &&
                            s.account_id === a.id,
                        ),
                    )
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.email}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Sheet name
                <input
                  name="title"
                  placeholder="Engineering applications"
                  maxLength={100}
                />
              </label>
              <Button disabled={busy}>Create profile sheet</Button>
            </form>
          </details>
        ))}
      </section>
      <section>
        <h3>Bidder sign-in</h3>
        <p>
          Create bidders and assign profiles on Bidder payments first. Passwords
          need at least 8 characters.
        </p>
        {index.bidders?.map((b) => (
          <form
            key={b.id}
            className="bidder-password-row"
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              void run(
                () =>
                  api.post(`/api/auth/bidders/${b.id}/password`, {
                    password: data.get("password"),
                    enabled: true,
                  }),
                `${b.name} password updated`,
              );
            }}
          >
            <strong>{b.name}</strong>
            <input
              aria-label={`New password for ${b.name}`}
              name="password"
              type="password"
              minLength={8}
              maxLength={256}
              required
              autoComplete="new-password"
            />
            <Button disabled={busy}>
              {b.login_enabled ? "Reset password" : "Enable sign-in"}
            </Button>
            {Boolean(b.login_enabled) && (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  void run(
                    () =>
                      api.post(`/api/auth/bidders/${b.id}/password`, {
                        enabled: false,
                      }),
                    `${b.name} sign-in disabled`,
                  )
                }
              >
                Disable
              </Button>
            )}
          </form>
        ))}
      </section>
    </DialogContent>
  );
}
