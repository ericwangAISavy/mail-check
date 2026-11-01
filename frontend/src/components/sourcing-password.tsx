import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
export default function OwnPassword() {
  const [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <DialogContent>
      <DialogTitle>Change your password</DialogTitle>
      <DialogDescription>
        Other sessions using your old password will be signed out.
      </DialogDescription>
      <form
        className="sourcing-password-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          setMessage("");
          const form = e.currentTarget,
            data = new FormData(form);
          if (data.get("password") !== data.get("confirm")) {
            setError("Passwords do not match.");
            return;
          }
          setBusy(true);
          try {
            await api.post("/api/auth/password/self", {
              current_password: data.get("current_password"),
              password: data.get("password"),
            });
            form.reset();
            setMessage("Password changed.");
          } catch (e) {
            setError(
              e instanceof Error ? e.message : "Could not change password.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Current password
          <input
            type="password"
            name="current_password"
            required
            autoComplete="current-password"
            maxLength={256}
          />
        </label>
        <label>
          New password
          <input
            type="password"
            name="password"
            minLength={8}
            maxLength={256}
            required
            autoComplete="new-password"
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            name="confirm"
            minLength={8}
            maxLength={256}
            required
            autoComplete="new-password"
          />
        </label>
        {error && (
          <p role="alert" className="inline-error">
            {error}
          </p>
        )}
        {message && <p role="status">{message}</p>}
        <Button disabled={busy}>Change password</Button>
      </form>
    </DialogContent>
  );
}
