import { BackgroundWorkersSection } from "./background-workers-section";
import { CommunicationHubSection } from "./communication-hub-section";
import { DailyRhythmSection } from "./daily-rhythm-section";
import { IntelligentMemorySection } from "./intelligent-memory-section";
import { PersonalKnowledgeSection } from "./personal-knowledge-section";
import { ProjectsGoalsSection } from "./projects-goals-section";
import { SocraticLearningSection } from "./socratic-learning-section";

export function FeatureSections() {
  return (
    <div id="features">
      <IntelligentMemorySection />
      <DailyRhythmSection />
      <ProjectsGoalsSection />
      <CommunicationHubSection />
      <SocraticLearningSection />
      <BackgroundWorkersSection />
      <PersonalKnowledgeSection />
    </div>
  );
}
