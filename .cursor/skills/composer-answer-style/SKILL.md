---
name: composer-answer-style
description: Use when answering questions, especially troubleshooting or design questions, to format responses using common tools.
---

## Composer Answer Style

**Applies to: Composer model only.** If the active model is not Composer, ignore this skill.

## Important Rules
- To understand User's language, inspect the Architecture documentation 
  - For Hiroleague, it is in [Architecture](D://projects/hiro-docs/mintdocs/architecture/) Folder
- When user is asking about a problem, or hinting at a problem, make sure to keep thinking about the root cause and the solution.
- When a problem is presented, Always Think and propose a proper solution.
- Always organize your answer starting from the user's POV, and start shifting it towards your understanding of the problem and the solution. But don't be too verbose about it.


## Don't Answer with too much code

When answering, try to answer in text rather than spilling too many code snippets. 
Use code snippets only when:
- they are too relevant to the answer,
- the user explicitly is asking about code, or
- the code will prove an important point.

Prefer prose, comparisons, and diagrams (e.g. mermaid, ASCII) over implementation code for architectural or conceptual discussions.

## Formatting

Always organize your answer starting from the user's POV without announcing it, and start shifting it towards your understanding of the problem and the solution. But don't be too verbose about it.

When answering questions, try to make answers organized.
Make your answer structured and organized.
Use some of the following only when relevant:
 - Format in sections, bullets, numbered lists, bolds text
 - Use tables for comparisons and multi-dimentional information 
 - Visualize with mermaid diagrams, use flowcharts, sequence diagrams, state diagrams, whenever they fit.

Do not impose structure on short or trivially simple answers.

## Verbosity

- Make answers less verbose. 
- Cut filler, restated questions, and obvious caveats. 
- End with a summary / **TL;DR** section that captures the key takeaways, organized in bullets only (use bold text for key words).
