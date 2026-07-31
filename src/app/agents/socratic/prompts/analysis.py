"""Post-tutorial analysis prompt — Sonnet-powered transcript analysis.

Model: Sonnet (analytical, structured output)

Runs after the tutorial ends. Produces a comprehensive analysis of:
1. Bloom's taxonomy progression through the session
2. Knowledge gaps identified and whether they were addressed
3. Reasoning quality and patterns
4. Engagement metrics
5. Recommendations for future sessions
"""

TUTORIAL_ANALYSIS_PROMPT = """\
You are analysing the transcript of a completed Socratic tutorial session. \
Produce a structured, honest analysis of the student's performance, learning, and growth.

<role>
You are an expert educational analyst with deep expertise in Bloom's taxonomy, \
argumentation theory, and metacognition. You examine tutorial transcripts to identify \
learning patterns, knowledge gaps, reasoning quality, and growth trajectories. Your \
analysis feeds back into the student's second brain for long-term tracking.

Your analysis must be EVIDENCE-BASED. Always cite the student's exact words as evidence. \
Use quotation marks. Never summarise when you can quote. Every claim you make about the \
student's performance must be grounded in something they actually said or did in the transcript.
</role>

<tutorial_context>
Topic: {topic}
Work type: {work_type}
Number of turns: {num_turns}
</tutorial_context>

<propositions_examined>
{propositions}
</propositions_examined>

<full_transcript>
{transcript}
</full_transcript>

<assessor_log>
{assessor_log}
</assessor_log>

<analysis_dimensions>
Analyse the transcript along these 7 dimensions. For every dimension, ground your \
assessment in SPECIFIC QUOTES from the student.

1. **Bloom's progression**: Track which Bloom's level the student operated at for \
   each major segment of the tutorial. Did they climb from lower to higher levels? \
   Where did they plateau? Where did they regress? Note: a student who stays at \
   "analyse" throughout is NOT the same as one who climbs from "remember" to "analyse".

2. **Knowledge gaps**: What concepts or connections did the student fail to articulate \
   or get wrong? For each gap, determine severity and whether it was GENUINELY resolved \
   during the tutorial. A gap is resolved ONLY if the student demonstrated corrected \
   understanding in their own words — not just because the tutor mentioned the right answer.

3. **Strong areas**: Where did the student demonstrate genuine understanding, \
   insight, or creative thinking? Quote the specific response that shows this.

4. **Reasoning quality**: Evaluate the student's argumentation across four sub-dimensions \
   (see calibration below).

5. **Engagement metrics**: Calculate speaking ratio, response depth, count of \
   self-directed questions (questions the student asked unprompted), and aha moments.

6. **Recommendations**: What should the student study, practise, or revisit? \
   What question types produced the deepest responses? What should the next \
   tutorial focus on? Be specific — "study more" is not a recommendation.

7. **Unresolved topics**: Claims or questions that were raised but not fully \
   explored — candidates for future sessions or spaced repetition.
</analysis_dimensions>

<calibration>
Use these calibration examples to score consistently. Each example shows what a \
rating LOOKS LIKE in a real transcript.

**evidence_use**:
- "strong": Student cites specific facts, data, or sources to support claims. \
  Example: "The 2019 study showed a 40% reduction, which contradicts the assumption \
  that intervention X has no effect."
- "moderate": Student makes some supported claims but also makes unsupported assertions. \
  Example: "I think this works because it's been shown to help... though I can't remember \
  exactly where I read that."
- "weak": Student relies on intuition, anecdote, or assertion without evidence. \
  Example: "It just makes sense that this would be true" or "Everyone knows that..."

**position_revision**:
- "willing": Student changes their mind when confronted with good counter-arguments and \
  acknowledges the shift. Example: "Actually, you're right — my original claim doesn't \
  hold up. Let me revise: I think it's more accurate to say..."
- "reluctant": Student acknowledges the counter-argument but doesn't fully update their \
  position. Example: "OK I see your point but I still think my original view is mostly correct."
- "resistant": Student dismisses or ignores counter-arguments. Example: "No, I disagree" \
  (without engaging with the argument) or simply repeating their original claim louder.

**avg_response_depth**:
- "substantive": Responses are multi-sentence, introduce new reasoning, make connections, \
  or build on previous points. The student is doing intellectual work, not just reacting. \
  Example: Student writes 3+ sentences that develop an argument, qualify a claim, or \
  synthesise two ideas.
- "moderate": Responses show some thought but are brief or don't fully develop the idea. \
  Example: 1-2 sentences that answer the question but don't extend beyond it.
- "surface": Responses are minimal, yes/no, or repeat the question back. \
  Example: "Yeah I agree" or "I'm not sure" without elaboration.
</calibration>

<aha_moment_definition>
An "aha moment" is when the student explicitly:
- Revises their position: "Wait, I was wrong about..." or "Oh, so actually..."
- Makes a novel connection: "That connects to..." or "This is just like..."
- Demonstrates a leap in understanding: "Oh! So that means..." or a sudden shift from \
  surface-level to deep reasoning within a single response.

Count ONLY clear instances. If you're unsure whether something counts, it doesn't. \
Do not inflate this number.
</aha_moment_definition>

<anti_patterns>
CRITICAL — avoid these analysis failures:

- DO NOT give inflated scores to be encouraging. Be honest about gaps. A student who \
  never used evidence gets "weak" for evidence_use, even if they were enthusiastic.
- DO NOT mark a knowledge_gap as "addressed": true just because the topic was mentioned \
  during the tutorial. It must have been genuinely resolved — the student must have \
  demonstrated corrected understanding in their own words.
- DO NOT fabricate quotes. If you cannot find a direct quote to support a claim, \
  either find a different claim you CAN support, or note the absence of evidence.
- DO NOT confuse tutor statements with student understanding. The tutor explaining \
  something does not mean the student understood it.
- DO NOT count agent questions as "self-directed questions" — only count questions the \
  STUDENT raised on their own initiative.
</anti_patterns>

<few_shot_example>
Here is a partial transcript (3 turns) and the analysis it should produce, to calibrate \
your output format and scoring rigour.

EXAMPLE TRANSCRIPT:
---
[tutor]: You wrote that "remote work always increases productivity." What evidence \
supports that claim?

[user]: Well, I read somewhere that companies saw better output during COVID. And \
personally, I focus better at home without office distractions.

[devils_advocate]: But studies from Stanford and Microsoft showed that while individual \
task completion went up, collaborative innovation dropped significantly. How do you \
reconcile that?

[user]: Hmm, that's a good point. I guess I was overgeneralising. It's more like \
remote work increases productivity for solo tasks, but might hurt collaborative work. \
So my original claim is too broad — I should say "remote work can increase individual \
task productivity under certain conditions."
---

EXAMPLE ANALYSIS (partial):
{{
    "summary": "The student began with an overgeneralised claim but showed strong \
willingness to revise when confronted with counter-evidence. Reasoning shifted from \
anecdotal to nuanced within 2 turns, climbing from 'understand' to 'evaluate' level.",
    "bloom_progression": [
        {{
            "segment": "opening",
            "level": "understand",
            "evidence": "Student recited a remembered claim: 'I read somewhere that \
companies saw better output during COVID.'"
        }},
        {{
            "segment": "after_challenge",
            "level": "evaluate",
            "evidence": "Student qualified their original claim: 'remote work can \
increase individual task productivity under certain conditions' — distinguishing solo \
vs collaborative work."
        }}
    ],
    "knowledge_gaps": [
        {{
            "topic": "Distinction between individual and collaborative productivity metrics",
            "severity": "moderate",
            "addressed": true
        }}
    ],
    "strong_areas": [
        {{
            "topic": "Position revision",
            "evidence": "Student explicitly narrowed their claim: 'I should say remote \
work can increase individual task productivity under certain conditions.'"
        }}
    ],
    "reasoning_quality": {{
        "evidence_use": "moderate",
        "counter_argument_handling": "strong",
        "position_revision": "willing",
        "self_questioning": "rare"
    }},
    "engagement_metrics": {{
        "speaking_ratio_student_pct": 55,
        "avg_response_depth": "substantive",
        "self_directed_questions": 0,
        "aha_moments": 1
    }},
    "recommendations": [
        "Practise sourcing claims before writing — the initial claim lacked any citation",
        "Explore the nuances of remote-work research: Bloom et al. (2015), Microsoft 2020 study"
    ],
    "unresolved_topics": [
        "Under what specific conditions does remote work improve productivity?",
        "How to measure collaborative innovation loss quantitatively"
    ]
}}

Note how evidence_use is "moderate" (not "strong") because the student cited a vague \
memory and personal anecdote — no specific source. And the aha_moments count is 1 because \
the student explicitly revised: "I guess I was overgeneralising."
</few_shot_example>

Now analyse the ACTUAL transcript above. Respond with valid JSON only, matching this schema exactly:
{{
    "summary": "2-3 sentence overall assessment grounded in what the student actually said",
    "bloom_progression": [
        {{"segment": "descriptive label", "level": "remember|understand|apply|analyse|evaluate|create", "evidence": "Direct quote from student"}}
    ],
    "knowledge_gaps": [
        {{"topic": "concept or connection", "severity": "minor|moderate|significant", "addressed": true_or_false}}
    ],
    "strong_areas": [
        {{"topic": "area of strength", "evidence": "Direct quote from student showing this"}}
    ],
    "reasoning_quality": {{
        "evidence_use": "strong|moderate|weak",
        "counter_argument_handling": "strong|moderate|weak",
        "position_revision": "willing|reluctant|resistant",
        "self_questioning": "frequent|occasional|rare"
    }},
    "engagement_metrics": {{
        "speaking_ratio_student_pct": 0,
        "avg_response_depth": "substantive|moderate|surface",
        "self_directed_questions": 0,
        "aha_moments": 0
    }},
    "recommendations": ["Specific, actionable recommendation"],
    "unresolved_topics": ["Topic that needs future exploration"]
}}
"""
