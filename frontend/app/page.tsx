import { NewDesign } from "@/components/new-design";

export default function Home() {
  return (
    <>
      <div className="page-intro">
        <h1>From an idea to silicon.</h1>
        <p>Describe a small digital chip. Follow every tool run, test, and layout.</p>
      </div>
      <NewDesign />
    </>
  );
}
