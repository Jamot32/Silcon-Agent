import { notFound } from "next/navigation";
import { ReliabilityDashboard } from "../../../components/reliability-dashboard";

export const dynamic = "force-dynamic";

export default function ReliabilityPage() {
  // Shared server-owned flag; production builds keep this development page off.
  // No query/client prop can enable this page or the disabled backend loader.
  if (process.env.NODE_ENV !== "development" || process.env.SILICON_DEV_RELIABILITY_ADMIN !== "1") notFound();
  return <ReliabilityDashboard />;
}
