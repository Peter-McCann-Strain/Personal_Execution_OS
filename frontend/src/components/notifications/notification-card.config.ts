import { Clock, GraduationCap, Handshake, Newspaper, Settings, Users, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { NotificationCategory } from "@/types";

const categoryIconMap: Record<NotificationCategory, LucideIcon> = {
  deadline: Clock,
  commitment: Handshake,
  relationship: Users,
  system: Settings,
  digest: Newspaper,
  proactive: Zap,
  tutorial: GraduationCap,
};

const categoryLabelMap: Record<NotificationCategory, string> = {
  deadline: "Deadline",
  commitment: "Commitment",
  relationship: "Relationship",
  system: "System",
  digest: "Digest",
  proactive: "Proactive",
  tutorial: "Tutorial",
};

export { categoryIconMap, categoryLabelMap };
