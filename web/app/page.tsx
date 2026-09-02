import { Verdict } from "@/components/Verdict";
import { api, ApiError } from "@/lib/api";

/**
 * Server component: the verdict is fetched on the server and arrives in the initial
 * HTML. A demo where the numbers flash in a moment after load reads as slow, and the
 * whole promise is a two-minute Monday glance — so the numbers must simply be there.
 *
 * The engine runs in ~10ms, so there is no cost to waiting for it server-side.
 */
export const dynamic = "force-dynamic";

export default async function Home() {
  try {
    const data = await api.verdict("demo");
    return <Verdict data={data} />;
  } catch (e) {
    const message =
      e instanceof ApiError ? e.message : "Something went wrong.";
    return (
      <main className="mx-auto max-w-2xl px-6 py-24">
        <h1 className="mb-3 text-sm font-medium text-[var(--color-ink-faint)]">
          Where did my money go?
        </h1>
        <p className="text-sm text-[var(--color-attention)]">{message}</p>
      </main>
    );
  }
}
