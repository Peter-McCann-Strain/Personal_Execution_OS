import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Smartphone, Trash2 } from "lucide-react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import {
  createCoreDataExport,
  downloadCoreDataExport,
  listCoreDataExports,
} from "@/api/account-data";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageError } from "@/components/ui/page-error";
import { clearThisDevice } from "@/lib/device-data";

function DataSettings() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [clearDeviceOpen, setClearDeviceOpen] = useState(false);
  const [unregisterServiceWorker, setUnregisterServiceWorker] = useState(false);
  const [clearingDevice, setClearingDevice] = useState(false);
  const [clearDeviceError, setClearDeviceError] = useState<string | null>(null);
  const exportsQuery = useQuery({
    queryKey: ["account", "core-data-exports"],
    queryFn: listCoreDataExports,
  });

  const exportMutation = useMutation({
    mutationFn: createCoreDataExport,
    onSuccess: async () => {
      toast.success("Core-data export queued");
      await queryClient.invalidateQueries({ queryKey: ["account", "core-data-exports"] });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Unable to request export");
    },
  });
  const downloadMutation = useMutation({
    mutationFn: downloadCoreDataExport,
    onSuccess: (payload) => {
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "personal-execution-os-core-data-export.json";
      anchor.click();
      URL.revokeObjectURL(url);
      void queryClient.invalidateQueries({ queryKey: ["account", "core-data-exports"] });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Unable to download export");
    },
  });

  const handleClearThisDevice = async () => {
    setClearingDevice(true);
    setClearDeviceError(null);
    try {
      const result = await clearThisDevice(queryClient, { unregisterServiceWorker });
      setClearDeviceOpen(false);
      if (result.warnings.length > 0) {
        toast.warning("Device data cleared with warnings", {
          description: result.warnings.join(" "),
        });
      } else {
        toast.success("This device has been cleared");
      }
      navigate("/login", { replace: true });
    } catch (error) {
      setClearDeviceError(error instanceof Error ? error.message : "Unable to clear this device");
    } finally {
      setClearingDevice(false);
    }
  };

  if (exportsQuery.isError) {
    const error = exportsQuery.error;
    return (
      <PageError
        message={error instanceof Error ? error.message : undefined}
        context="data controls"
        onRetry={() => {
          void exportsQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Card padding="lg">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
              Core-data export
            </h3>
            <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
              Downloads a documented subset: episodes, goals, notes, projects and tasks, contacts
              and interactions, reviews, habits, decisions, commitments, and saved memories. It is
              not a full account backup, provider-data export, or compliance archive.
            </p>
          </div>
          <Download className="h-5 w-5 text-[var(--color-fg-tertiary)]" />
        </div>
        <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
          Request core-data export
        </Button>
        <RequestList
          emptyLabel="No exports requested"
          loading={exportsQuery.isLoading}
          rows={(exportsQuery.data ?? []).map((row) => ({
            id: row.id,
            title: row.status,
            detail: row.expires_at
              ? `expires ${new Date(row.expires_at).toLocaleDateString("en-GB")}`
              : new Date(row.created_at).toLocaleDateString("en-GB"),
            actionLabel: row.status === "completed" ? "Download Again" : "Generate",
            onAction: () => downloadMutation.mutate(row.id),
            actionLoading: downloadMutation.isPending && downloadMutation.variables === row.id,
          }))}
        />
      </Card>

      <Card padding="lg">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
              Clear this device
            </h3>
            <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
              Removes this browser&apos;s session, in-memory chat, saved preferences, offline cache,
              and push subscription. It does not delete core records stored by the server.
            </p>
          </div>
          <Smartphone className="h-5 w-5 text-[var(--color-fg-tertiary)]" />
        </div>
        <Button
          variant="destructive"
          onClick={() => {
            setClearDeviceError(null);
            setClearDeviceOpen(true);
          }}
        >
          <Trash2 className="h-4 w-4" />
          Clear this device
        </Button>
      </Card>

      <Dialog.Root
        open={clearDeviceOpen}
        onOpenChange={(open) => {
          if (!clearingDevice) {
            setClearDeviceOpen(open);
            if (!open) setClearDeviceError(null);
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-xl)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6 shadow-2xl focus:outline-none">
            <Dialog.Title className="text-base font-semibold text-[var(--color-fg-primary)]">
              Clear data from this device?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-[var(--color-fg-secondary)]">
              You will be signed out. Local chat and browser caches cannot be recovered. Server-side
              goals, notes, projects, and other core records will remain.
            </Dialog.Description>
            <label className="mt-4 flex items-start gap-3 text-sm text-[var(--color-fg-secondary)]">
              <input
                type="checkbox"
                checked={unregisterServiceWorker}
                onChange={(event) => setUnregisterServiceWorker(event.target.checked)}
                className="mt-0.5 h-4 w-4"
              />
              <span>
                Also unregister the installed web-app worker. A later visit may install it again.
              </span>
            </label>
            {clearDeviceError ? (
              <p
                role="alert"
                className="mt-4 rounded-[var(--radius-md)] border border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10 p-3 text-xs text-[var(--color-error-500)]"
              >
                {clearDeviceError}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={clearingDevice}
                onClick={() => setClearDeviceOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                loading={clearingDevice}
                onClick={() => void handleClearThisDevice()}
              >
                Clear local data and sign out
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

function RequestList({
  rows,
  loading,
  emptyLabel,
}: {
  rows: Array<{
    id: string;
    title: string;
    detail: string;
    actionLabel?: string;
    onAction?: () => void;
    actionLoading?: boolean;
  }>;
  loading: boolean;
  emptyLabel: string;
}) {
  if (loading) {
    return <div className="mt-4 h-12 animate-pulse rounded bg-[var(--color-bg-overlay)]" />;
  }
  if (rows.length === 0) {
    return <p className="mt-4 text-sm text-[var(--color-fg-tertiary)]">{emptyLabel}</p>;
  }
  return (
    <div className="mt-4 divide-y divide-[var(--color-border-muted)] rounded-[var(--radius-md)] border border-[var(--color-border-default)]">
      {rows.map((row) => (
        <div key={row.id} className="flex items-center justify-between gap-3 px-3 py-2">
          <div>
            <div className="text-sm font-medium text-[var(--color-fg-primary)]">{row.title}</div>
            <div className="text-xs text-[var(--color-fg-tertiary)]">{row.detail}</div>
          </div>
          {row.onAction && row.actionLabel && (
            <Button size="sm" variant="outline" onClick={row.onAction} loading={row.actionLoading}>
              {row.actionLabel}
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}

export { DataSettings };
