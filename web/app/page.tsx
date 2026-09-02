import { Audit } from "@/components/Audit";
import { Correlation } from "@/components/Correlation";
import { Verdict } from "@/components/Verdict";
import { api, ApiError } from "@/lib/api";

/**
 * One page, three depths — the layering the brief asks for:
 *
 *   verdict      what a merchant reads on Monday, in two minutes
 *   correlation  the measured claim: how much of the unexplained we eliminate
 *   audit        how anyone can check it
 *
 * Not three routes, because the demo is a story told by scrolling, not a feature tour
 * navigated by clicking. Depth is available; nobody is made to go looking for it.
 */
export const dynamic = "force-dynamic";

const BATCH = "demo";

export default async function Home() {
  try {
    const [verdict, correlation] = await Promise.all([
      api.verdict(BATCH),
      api.correlation(BATCH),
    ]);

    return (
      <main className="mx-auto max-w-2xl px-6 py-16 sm:py-24">
        <Verdict data={verdict} />
        <Correlation data={correlation} />
        <Audit batch={BATCH} />
      </main>
    );
  } catch (e) {
    const message = e instanceof ApiError ? e.message : "Something went wrong.";
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
