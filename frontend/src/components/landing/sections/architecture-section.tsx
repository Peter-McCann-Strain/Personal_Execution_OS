import { Section, SectionHeading } from "../primitives";
import { ArchitectureDiagram } from "../visuals/architecture-diagram";

export function ArchitectureSection() {
  return (
    <Section id="architecture">
      <SectionHeading
        label="Under the Hood"
        title="An Inspectable Local Data Flow"
        description="Inputs move through explicit routes and focused workflows into PostgreSQL. Vector search and external providers remain optional."
      />
      <ArchitectureDiagram />
    </Section>
  );
}
