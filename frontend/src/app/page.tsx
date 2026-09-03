import BackendStatus from "@/components/BackendStatus";

/**
 * The console shell.
 *
 * Phase 0 produces no business behaviour, so this page shows the frame the later
 * phases fill: the four panels of PRD section 8.8, each labelled with the phase
 * that brings it to life, and a live link light for the backend. It is deliberately
 * a shell rather than a mockup — there is no fake recovered total and no sample
 * audit row, because a number on this screen has to mean something (PRD section
 * 13.4), and a placeholder that looks like data is the one thing this dashboard
 * must never show.
 */
export default function Home() {
  return (
    <div className="console-grid flex min-h-screen flex-col">
      <header className="border-b border-console-border bg-console-panel/70 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-5">
          <div className="flex items-baseline gap-3">
            <h1 className="text-xl font-semibold tracking-tight text-console-text">Recoup</h1>
            <span className="font-mono text-xs uppercase tracking-[0.2em] text-console-accent">
              Recovery Console
            </span>
          </div>
          <BackendStatus />
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">
        <section className="max-w-2xl">
          <p className="text-sm leading-6 text-console-muted">
            Recovery is a state machine, not a chatbot. The model diagnoses, the state machine
            decides, the constraint gate guards every money action, and the append-only audit log
            proves it.
          </p>
        </section>

        <section className="mt-10 grid gap-4 sm:grid-cols-2">
          {PANELS.map((panel) => (
            <article
              key={panel.title}
              className="rounded-lg border border-console-border bg-console-panel p-5"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-medium tracking-tight text-console-text">
                  {panel.title}
                </h2>
                <span className="rounded border border-console-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-console-muted">
                  {panel.phase}
                </span>
              </div>
              <p className="mt-2 text-sm leading-6 text-console-muted">{panel.description}</p>
            </article>
          ))}
        </section>

        <section className="mt-10 rounded-lg border border-console-border bg-console-panel p-5">
          <h2 className="text-sm font-medium tracking-tight text-console-text">Awaiting backend</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-console-muted">
            No work items, metrics or audit rows are shown because none exist yet. Start the
            FastAPI service and this console connects to it automatically; until then the link
            light above reports what it actually found.
          </p>
        </section>
      </main>

      <footer className="border-t border-console-border px-6 py-4">
        <p className="mx-auto w-full max-w-6xl font-mono text-[11px] text-console-muted">
          All money in integer paise · every action gated · every transition logged
        </p>
      </footer>
    </div>
  );
}

const PANELS = [
  {
    title: "Recovered total",
    phase: "Phase 10",
    description:
      "Rupees actually collected, counted from the audit log rather than from an assumption about what a retry did.",
  },
  {
    title: "Live audit trail",
    phase: "Phase 9",
    description:
      "Every state transition, appended and never edited, streaming in over the WebSocket with sequence-based backfill.",
  },
  {
    title: "Constraint rejections",
    phase: "Phase 6",
    description:
      "Where the gate said no, and against which limit. A gate that only ever says yes is a label, not a system.",
  },
  {
    title: "Escalation queue",
    phase: "Phase 6",
    description:
      "Work items handed to a person: a breached cap, a fraud flag, or retries exhausted without recovery.",
  },
] as const;
