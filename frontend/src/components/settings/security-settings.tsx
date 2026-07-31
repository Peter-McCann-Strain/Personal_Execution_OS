import { type FormEvent, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut } from "lucide-react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { changeOwnerPassword, revokeAllOwnerSessions } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useChatStore } from "@/stores/chat";

const PASSWORD_MIN_LENGTH = 12;
const PASSWORD_MAX_LENGTH = 256;

function SecuritySettings() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const clearAuthenticatedState = () => {
    queryClient.clear();
    useChatStore.getState().clearMessages();
  };

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changeError, setChangeError] = useState<string | null>(null);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revokePassword, setRevokePassword] = useState("");
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const changeMutation = useMutation({
    mutationFn: () => changeOwnerPassword(currentPassword, newPassword),
    onSuccess: () => {
      clearAuthenticatedState();
      toast.success("Password changed. Every device has been signed out.");
      navigate("/login", { replace: true });
    },
    onError: (error) => {
      setChangeError(error instanceof Error ? error.message : "Unable to change password");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: () => revokeAllOwnerSessions(revokePassword),
    onSuccess: () => {
      setRevokeOpen(false);
      clearAuthenticatedState();
      toast.success("Every device has been signed out.");
      navigate("/login", { replace: true });
    },
    onError: (error) => {
      setRevokeError(error instanceof Error ? error.message : "Unable to revoke sessions");
    },
  });

  const handlePasswordChange = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChangeError(null);
    if (currentPassword.length < PASSWORD_MIN_LENGTH || newPassword.length < PASSWORD_MIN_LENGTH) {
      setChangeError("Current and new passwords must each be at least 12 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setChangeError("New password and confirmation do not match.");
      return;
    }
    changeMutation.mutate();
  };

  return (
    <div className="flex flex-col gap-4">
      <Card padding="lg">
        <div className="mb-4 flex items-start gap-3">
          <KeyRound className="mt-0.5 h-5 w-5 text-[var(--color-fg-tertiary)]" />
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
              Change owner password
            </h3>
            <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
              Changing the password immediately signs out every browser and device, including this
              one.
            </p>
          </div>
        </div>
        <form className="flex max-w-md flex-col gap-3" onSubmit={handlePasswordChange}>
          <label className="text-xs font-medium text-[var(--color-fg-secondary)]">
            Current password
            <Input
              className="mt-1"
              type="password"
              autoComplete="current-password"
              minLength={PASSWORD_MIN_LENGTH}
              maxLength={PASSWORD_MAX_LENGTH}
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-[var(--color-fg-secondary)]">
            New password
            <Input
              className="mt-1"
              type="password"
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              maxLength={PASSWORD_MAX_LENGTH}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-[var(--color-fg-secondary)]">
            Confirm new password
            <Input
              className="mt-1"
              type="password"
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              maxLength={PASSWORD_MAX_LENGTH}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
            />
          </label>
          {changeError ? (
            <p role="alert" className="text-xs text-[var(--color-error-500)]">
              {changeError}
            </p>
          ) : null}
          <div>
            <Button type="submit" loading={changeMutation.isPending}>
              Change password and sign out all devices
            </Button>
          </div>
        </form>
      </Card>

      <Card padding="lg">
        <div className="mb-4 flex items-start gap-3">
          <LogOut className="mt-0.5 h-5 w-5 text-[var(--color-fg-tertiary)]" />
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
              Revoke all sessions
            </h3>
            <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
              Signs out every browser and device without changing the owner password.
            </p>
          </div>
        </div>
        <Button
          variant="destructive"
          onClick={() => {
            setRevokeError(null);
            setRevokePassword("");
            setRevokeOpen(true);
          }}
        >
          Sign out every device
        </Button>
      </Card>

      <Dialog.Root
        open={revokeOpen}
        onOpenChange={(open) => {
          if (!revokeMutation.isPending) {
            setRevokeOpen(open);
            if (!open) setRevokeError(null);
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-xl)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6 shadow-2xl focus:outline-none">
            <Dialog.Title className="text-base font-semibold text-[var(--color-fg-primary)]">
              Sign out every device?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-[var(--color-fg-secondary)]">
              Enter the current owner password to revoke every active session. This includes the
              device you are using now.
            </Dialog.Description>
            <label className="mt-4 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Current password
              <Input
                className="mt-1"
                type="password"
                autoComplete="current-password"
                minLength={PASSWORD_MIN_LENGTH}
                maxLength={PASSWORD_MAX_LENGTH}
                value={revokePassword}
                onChange={(event) => setRevokePassword(event.target.value)}
              />
            </label>
            {revokeError ? (
              <p role="alert" className="mt-3 text-xs text-[var(--color-error-500)]">
                {revokeError}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={revokeMutation.isPending}
                onClick={() => setRevokeOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                loading={revokeMutation.isPending}
                disabled={revokePassword.length < PASSWORD_MIN_LENGTH}
                onClick={() => revokeMutation.mutate()}
              >
                Revoke sessions and sign out
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

export { SecuritySettings };
