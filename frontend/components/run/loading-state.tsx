import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";

export function RunUnavailable({ title, description }: { title: string; description: string }) {
  return <Empty role="status" className="min-h-[400px] border border-dashed"><EmptyHeader><EmptyTitle role="heading" aria-level={1} className="text-2xl font-semibold tracking-tight">{title}</EmptyTitle><EmptyDescription>{description}</EmptyDescription></EmptyHeader><EmptyContent><Button asChild variant="outline"><Link href="/runs"><ArrowLeft data-icon="inline-start" />Return to run history</Link></Button></EmptyContent></Empty>;
}
