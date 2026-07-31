# First ten minutes

This walkthrough starts with an empty local installation and every optional
provider disabled. It creates a small fictional workspace so you can see how
the main records fit together without entering personal information.

## Before you start

Complete the local setup in [SETUP.md](SETUP.md), then open
[http://localhost:8080/setup](http://localhost:8080/setup). Create the owner
password and sign in.

Keep this first run disposable. The project is a public preview, and you should
test backup restoration before storing anything you cannot replace.

## 1. Create an outcome

Open **Goals**, select **New Goal**, and enter:

- Title: `Run the Example Garden open day`
- Type: `Monthly`
- Priority: `7`
- Deadline: choose a date about one month from today

Select **Create Goal**. Goals record the outcome and its importance; they do not
replace the work needed to reach it.

## 2. Create the project

Open **Projects**, select **New Project**, and enter:

- Title: `Example Garden open-day checklist`
- Description: `Ready when the fictional venue, volunteers, and printed guide are confirmed.`
- Appetite: `Small`
- Deadline: use the same date as the goal

Select **Create Project**. The project now gives the example outcome a bounded
piece of work. Goal and project records are separate in this release, so this
walkthrough uses matching names rather than claiming an automatic link.

## 3. Add a project brief

Open **Notes**, select **New Note**, and choose the **Project brief** template.
Change the title to `Example Garden open-day brief`, then replace the template
prompts with:

```markdown
# Outcome

A short fictional open day with a clear schedule and visitor guide.

# Constraints

- No real names, addresses, or contact details
- Keep the example small enough to finish this week

# Critical path

1. Draft the schedule
2. Review the visitor guide

# Risks

- The example scope grows beyond one afternoon
```

Keep the note in the **Project** PARA category and save it. This is a local
record; creating it does not call a model or external service.

## 4. Add a routine

Open **Habits**, select **New Habit**, and enter:

- Name: `Review the open-day next action`
- Description: `Check the fictional project and choose one next action.`
- Frequency: `Daily`
- Tag: `example-garden`

Create the habit, then mark it complete once. The Habits page records the
completion and updates the local routine state.

## 5. Inspect the working views

Open **Workbench** and select its **All** saved view. It assembles the local
records that its data sources can load. Switch to **Today** to narrow the list
to due work, today's schedule, and active routines. With providers still
disabled, external calendar and mail context should remain unavailable rather
than showing invented data.

Open **Today** from the primary navigation as well. A new workspace will still
look sparse. Its summaries become more useful after you add deadlines,
commitments, routine completions, and diary records over time.

## 6. Confirm the safety boundary

Open **Settings**, then **Integrations**. Confirm that Anthropic, Google
Workspace, Tavily, Sentry, and PostHog do not report a configured or connected
provider unless you deliberately changed the example configuration.

The local records above do not need a model API key. Chat, model classification,
web research, external sync, and other provider-backed behavior remain
unavailable until their required service is configured. The
[capability matrix](CAPABILITIES.md) explains each boundary.

## 7. Make a test backup

From the repository root, run:

```sh
./scripts/backup-database.sh
```

The script writes a PostgreSQL dump and matching SHA-256 file under `backups/`
unless you supply another path. Treat both files as sensitive. This database
archive does not include `.env`, `config/IDENTITY.local.md`, Redis, or the
`app-data` volume; [SETUP.md](SETUP.md) describes complete backup coverage and
the destructive restore command.

You now have a small local execution loop: an outcome, a project, a supporting
note, a repeatable check, and a verified database archive. Delete the fictional
records when you are ready to start with your own data.
