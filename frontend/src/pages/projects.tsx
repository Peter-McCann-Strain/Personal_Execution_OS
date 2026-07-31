import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownAZ,
  ArrowUpAZ,
  FolderKanban,
  FolderOpen,
  Layers,
  Plus,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { EmptyState } from "@/components/ui/empty-state";
import { ProjectCard } from "@/components/projects/project-card";
import { ProjectTree } from "@/components/projects/project-tree";
import {
  applyProjectDraft,
  createProject,
  getProjectDrafts,
  getProjects,
  updateTask,
  type CreateProjectData,
  type ProjectQueryParams,
} from "@/api/projects";
import { FilterSelect } from "@/components/ui/filter-select";
import type { Appetite, Project, ProjectDraft, ProjectStatus, TaskStatus } from "@/types";

type SortField = "deadline" | "progress" | "title" | "created_at";

const STATUS_OPTIONS: { value: ProjectStatus | "all"; label: string }[] = [
  { value: "all", label: "All Statuses" },
  { value: "planning", label: "Planning" },
  { value: "in-progress", label: "In Progress" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

const APPETITE_OPTIONS: { value: Appetite | "all"; label: string }[] = [
  { value: "all", label: "All Appetites" },
  { value: "small", label: "Small (1 wk)" },
  { value: "medium", label: "Medium (2 wk)" },
  { value: "large", label: "Large (6 wk)" },
];

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "deadline", label: "Deadline" },
  { value: "title", label: "Name" },
  { value: "created_at", label: "Created" },
];

function sortProjects(projects: Project[], field: SortField, ascending: boolean): Project[] {
  const sorted = [...projects].sort((a, b) => {
    switch (field) {
      case "deadline":
        if (!a.deadline && !b.deadline) return 0;
        if (!a.deadline) return 1;
        if (!b.deadline) return -1;
        return new Date(a.deadline).getTime() - new Date(b.deadline).getTime();
      case "title":
        return a.title.localeCompare(b.title);
      case "created_at":
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      default:
        return 0;
    }
  });
  return ascending ? sorted : sorted.reverse();
}

function ProjectDraftCard({
  draft,
  onApply,
  applying,
}: {
  draft: ProjectDraft;
  onApply: () => void;
  applying: boolean;
}) {
  return (
    <Card padding="lg" className="gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">{draft.title}</h3>
          <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
            {draft.milestone_count} milestones • {draft.total_estimated_hours ?? 0}h
          </p>
        </div>
        <Badge size="sm" variant={draft.status === "applied" ? "success" : "warning"}>
          {draft.status}
        </Badge>
      </div>
      {draft.project_summary && (
        <p className="text-sm text-[var(--color-fg-secondary)]">{draft.project_summary}</p>
      )}
      {draft.critical_path.length > 0 && (
        <p className="text-xs text-[var(--color-fg-tertiary)]">
          Critical path: {draft.critical_path.join(", ")}
        </p>
      )}
      <div className="flex items-center justify-end">
        <Button
          size="sm"
          className="gap-1.5"
          loading={applying}
          disabled={draft.status === "applied"}
          onClick={onApply}
        >
          <Sparkles className="h-4 w-4" />
          Apply Draft
        </Button>
      </div>
    </Card>
  );
}

function CreateProjectModal({
  open,
  onClose,
  onCreate,
  isCreating,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (data: CreateProjectData) => void;
  isCreating: boolean;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [appetite, setAppetite] = useState<Appetite | "">("");
  const [deadline, setDeadline] = useState("");

  if (!open) return null;

  const resetAndClose = () => {
    setTitle("");
    setDescription("");
    setAppetite("");
    setDeadline("");
    onClose();
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!title.trim()) return;

    onCreate({
      title: title.trim(),
      description: description.trim() || undefined,
      appetite: appetite || undefined,
      deadline: deadline ? `${deadline}T00:00:00` : undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={resetAndClose}
        aria-label="Close new project dialog"
      />
      <div className="relative z-10 w-full max-w-lg rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-5 py-4">
          <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">New Project</h2>
          <button
            type="button"
            onClick={resetAndClose}
            className="rounded-[var(--radius-md)] p-1.5 text-[var(--color-fg-tertiary)] transition-colors hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Title <span className="text-[var(--color-error-500)]">*</span>
            </label>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. Personal OS launch"
              autoFocus
              required
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Description
            </label>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What does done look like?"
              rows={3}
              className="flex w-full resize-none rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-fg-primary)] shadow-sm transition-colors placeholder:text-[var(--color-fg-tertiary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-base)]"
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                Appetite
              </label>
              <select
                value={appetite}
                onChange={(event) => setAppetite(event.target.value as Appetite | "")}
                className="h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)]"
              >
                <option value="">Unset</option>
                <option value="small">Small</option>
                <option value="medium">Medium</option>
                <option value="large">Large</option>
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                Deadline
              </label>
              <Input
                type="date"
                value={deadline}
                onChange={(event) => setDeadline(event.target.value)}
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 border-t border-[var(--color-border-subtle)] pt-4">
            <Button type="button" variant="ghost" onClick={resetAndClose}>
              Cancel
            </Button>
            <Button type="submit" loading={isCreating} disabled={!title.trim()}>
              Create Project
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ProjectsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<ProjectStatus | "all">("all");
  const [appetiteFilter, setAppetiteFilter] = useState<Appetite | "all">("all");
  const [sortField, setSortField] = useState<SortField>("deadline");
  const [sortAsc, setSortAsc] = useState(true);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  const queryParams: ProjectQueryParams = useMemo(() => {
    const params: ProjectQueryParams = { limit: 50 };
    if (statusFilter !== "all") params.status = statusFilter;
    if (appetiteFilter !== "all") params.appetite = appetiteFilter;
    return params;
  }, [statusFilter, appetiteFilter]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["projects", queryParams],
    queryFn: () => getProjects(queryParams),
  });

  const draftsQuery = useQuery({
    queryKey: ["project-drafts"],
    queryFn: () => getProjectDrafts({ limit: 20, offset: 0 }),
  });

  const taskMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) => updateTask(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const applyDraftMutation = useMutation({
    mutationFn: (draftId: string) => applyProjectDraft(draftId),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["project-drafts"] });
      setSelectedProject(project);
    },
  });

  const createProjectMutation = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setSelectedProject(project);
      setCreateModalOpen(false);
      toast.success("Project created");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to create project");
    },
  });

  const projects = useMemo(() => {
    if (!data?.items) return [];
    return sortProjects(data.items, sortField, sortAsc);
  }, [data, sortField, sortAsc]);

  const drafts = draftsQuery.data?.items ?? [];

  return (
    <PageTransition>
      <div className="mx-auto max-w-7xl space-y-6 p-6">
        <PageHeader
          title="Projects"
          subtitle="Draft-first planning with explicit apply flow"
          icon={FolderKanban}
          agentColor="project"
        >
          <Button size="sm" onClick={() => setCreateModalOpen(true)}>
            <Plus className="h-4 w-4" />
            New Project
          </Button>
        </PageHeader>

        {drafts.length > 0 && !selectedProject && (
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-[var(--color-info-500)]" />
              <h2 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                Project Drafts
              </h2>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              {drafts.map((draft) => (
                <ProjectDraftCard
                  key={draft.id}
                  draft={draft}
                  applying={applyDraftMutation.isPending}
                  onApply={() => applyDraftMutation.mutate(draft.id)}
                />
              ))}
            </div>
          </section>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <FilterSelect
            ariaLabel="Filter projects by status"
            value={statusFilter}
            options={STATUS_OPTIONS}
            onChange={setStatusFilter}
          />
          <FilterSelect
            ariaLabel="Filter projects by appetite"
            value={appetiteFilter}
            options={APPETITE_OPTIONS}
            onChange={setAppetiteFilter}
          />
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-[var(--color-fg-tertiary)]">Sort:</span>
            <FilterSelect
              ariaLabel="Sort projects"
              value={sortField}
              options={SORT_OPTIONS}
              onChange={setSortField}
            />
            <button
              type="button"
              onClick={() => setSortAsc((prev) => !prev)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)] transition-colors"
              title={sortAsc ? "Ascending" : "Descending"}
              aria-label={sortAsc ? "Sort ascending" : "Sort descending"}
            >
              {sortAsc ? <ArrowUpAZ className="h-4 w-4" /> : <ArrowDownAZ className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {isLoading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-48 w-full" />
            ))}
          </div>
        )}

        {isError && (
          <PageError
            message={error?.message ?? "Failed to load projects"}
            onRetry={() => refetch()}
            context="your projects"
            icon={FolderKanban}
          />
        )}

        {!isLoading && !isError && projects.length === 0 && !selectedProject && (
          <EmptyState
            icon={FolderOpen}
            title="No projects yet"
            description="Create or apply a draft to get started."
            action={{
              label: "New Project",
              onClick: () => setCreateModalOpen(true),
            }}
          />
        )}

        {!isLoading && !isError && projects.length > 0 && !selectedProject && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onClick={() => setSelectedProject(project)}
              />
            ))}
          </div>
        )}

        {selectedProject && (
          <div>
            <button
              type="button"
              onClick={() => setSelectedProject(null)}
              className="mb-4 flex items-center gap-1 text-sm text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors"
            >
              <Layers className="h-4 w-4" />
              Back to all projects
            </button>
            <div className="mb-4">
              <h2 className="text-xl font-bold text-[var(--color-fg-primary)]">
                {selectedProject.title}
              </h2>
              {selectedProject.description && (
                <p className="mt-1 text-sm text-[var(--color-fg-secondary)]">
                  {selectedProject.description}
                </p>
              )}
            </div>
            <ProjectTree
              project={selectedProject}
              onTaskStatusChange={(taskId, status) => taskMutation.mutate({ id: taskId, status })}
            />
          </div>
        )}
        <CreateProjectModal
          open={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onCreate={(project) => createProjectMutation.mutate(project)}
          isCreating={createProjectMutation.isPending}
        />
      </div>
    </PageTransition>
  );
}

export { ProjectsPage };
