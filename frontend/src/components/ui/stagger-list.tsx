import { motion } from "motion/react";
import type { ReactNode } from "react";
import { containerVariants, itemVariants } from "./stagger-list.variants";

interface StaggerListProps {
  children: ReactNode[];
  /** CSS class for the container */
  className?: string;
  /** Delay between each child in ms */
  staggerMs?: number;
}

function StaggerList({ children, className, staggerMs }: StaggerListProps) {
  const customContainer = staggerMs
    ? {
        hidden: {},
        visible: { transition: { staggerChildren: staggerMs / 1000 } },
      }
    : containerVariants;

  return (
    <motion.div variants={customContainer} initial="hidden" animate="visible" className={className}>
      {children.map((child, i) => (
        <motion.div key={i} variants={itemVariants}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
}

export { StaggerList };
