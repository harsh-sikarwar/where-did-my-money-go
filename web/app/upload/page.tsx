"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Upload } from "@/components/Upload";
import { BackLink } from "@/components/ui";

/**
 * The upload route. Thin by design — `Upload` already owns the whole flow (file
 * picking, the mapping question, the confirmation screen); this page's only job is to
 * frame it and send a finished batch on to `/analysis/[batch]`.
 */
export default function UploadPage() {
  const router = useRouter();

  return (
    <main className="mx-auto max-w-[600px] px-6 pt-16 pb-32 sm:pt-[88px]">
      <div className="stagger">
        <div style={{ "--i": 0 } as React.CSSProperties}>
          <Link href="/">
            <BackLink />
          </Link>
        </div>

        <h1
          className="text-headline mt-9 mb-10"
          style={{ "--i": 1 } as React.CSSProperties}
        >
          Reconcile your own files.
        </h1>

        <div style={{ "--i": 2 } as React.CSSProperties}>
          <Upload
            onDone={(batch) => router.push(`/analysis/${encodeURIComponent(batch)}`)}
          />
        </div>
      </div>
    </main>
  );
}
