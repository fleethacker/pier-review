import type { AppDefinition } from '../scene/app';

/** One box per application built on the shared physics services. Clicking a box opens that application. */
export function Landing({ apps, onOpen }: { apps: AppDefinition[]; onOpen: (app: AppDefinition) => void }) {
  return (
    <main className="min-h-0 flex-1 overflow-y-auto p-6 md:p-10">
      <div className="mx-auto max-w-6xl">
        <h1 className="mil-label text-base text-white">Applications</h1>
        <p className="mt-2 max-w-3xl text-[12px] text-mil-dim">
          Each application below runs on the same modeling services: vessel and mooring physics, environment sources and the
          planning agents. Results use seed and demonstration data and are not for operational use.
        </p>
        <ul className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Applications">
          {apps.map((app) => (
            <li key={app.id} className="flex">
              <button
                onClick={() => onOpen(app)}
                className="glass-panel mil-brackets group flex w-full flex-col items-start gap-3 rounded-sm border border-mil-border p-5 text-left transition-colors hover:border-mil-cyan/60 focus:border-mil-cyan focus:outline-none"
                aria-label={`Open ${app.title}`}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="mil-label text-[13px] text-white group-hover:text-mil-cyan">{app.title}</span>
                  <span aria-hidden className="text-mil-cyan opacity-60 group-hover:opacity-100">
                    →
                  </span>
                </span>
                <span className="text-[12px] text-mil-text">{app.description}</span>
                {app.physics && app.physics.length > 0 && (
                  <span className="flex flex-wrap gap-1" aria-label="Physics used">
                    {app.physics.map((p) => (
                      <span key={p} className="rounded-sm border border-mil-border px-1.5 py-px text-[10px] uppercase tracking-wider text-mil-dim">
                        {p}
                      </span>
                    ))}
                  </span>
                )}
                {app.tabs && app.tabs.length > 1 && (
                  <span className="mt-auto text-[10px] text-mil-dim">{app.tabs.map((t) => t.label).join(' · ')}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
