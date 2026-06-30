---
name: project-brain
description: Maintains a persistent, compressed intelligence layer for a codebase, acting as its long-term memory. Use this skill when working on any codebase that has a 'brain/' folder to read architectural contexts before every task, and to update master-memory, patterns, decisions, or mistakes logs after task execution.
---

# Project Brain Skill

A skill for managing and maintaining a persistent, compressed intelligence layer for software repositories.

## 1. Concept

Every software project suffers from "Context Amnesia" when AI developers start new sessions, leading to repeated scanning, token waste, and architectural drift.
The **Project Brain** skill addresses this by enforcing a dedicated `brain/` directory representing the project's long-term memory.

```
project/
├── AGENTS.md
├── brain/
│   ├── master-memory.md      - Architecture summary, decisions, patterns, known issues, roadmap
│   ├── memory.md             - Central summary, key features, current state, active work
│   ├── architecture.md       - System design details (frontend, backend, DB, integrations)
│   ├── patterns.md           - Approved programming patterns
│   ├── decisions.md          - Architectural decisions & justifications
│   ├── mistakes.md           - Known pitfalls & fixes
│   ├── roadmap.md            - Future planning/phases
│   ├── glossary.md           - Definitions of project terminology
│   ├── dependency-graph.md   - File relationships diagram
│   └── feature-map.md        - Map of features to code coordinates
```

---

## 2. Triggering

Trigger this skill whenever:
* Working on a codebase containing a `brain/` folder.
* Modifying structure, making decisions, or running tests.
* Instructed to document, audit, or clean repository context.

---

## 3. Development Workflow

### Before Every Task (Context Load)
Before performing any modification or plan generation, the active agent MUST read:
1. `brain/master-memory.md` (to align on current state and roadmaps)
2. `brain/architecture.md` (to understand system structure)
3. `brain/patterns.md` (to adhere to approved coding idioms)
4. `brain/decisions.md` (to understand past design choices)

### During Task Execution
* Refer back to `brain/mistakes.md` to avoid duplicating past failures.
* Check `brain/feature-map.md` to find relevant files quickly.

### After Task Execution (Project Learning)
Upon successful verification of a task:
1. Identify if any new design decisions were made (update `brain/decisions.md`).
2. Identify if any new reusable patterns were created (update `brain/patterns.md`).
3. Identify if any bugs were fixed that represent recurrent pitfalls (update `brain/mistakes.md`).
4. Summarize changes and update the central project state in `brain/memory.md` and `brain/master-memory.md`.
