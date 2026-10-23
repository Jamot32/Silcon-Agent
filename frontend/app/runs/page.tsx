import { RunHistory } from "@/components/run-history";

export default function Runs() {
  return (
    <>
      <div className="page-intro"><h1>Run history.</h1><p>Every design, tool run, and result in one place.</p></div>
      <RunHistory />
    </>
  );
}
