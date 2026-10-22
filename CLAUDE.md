# Notes for agents working in this repo

## Where skills go

- **Report skills go in `reports/`**, not `SKILLS/`. A report skill is one that produces a
  finished report document (HTML / PDF / CSV) from tenant data, for example
  `reports/security-agent-deployment-status-report` and `reports/o365-activity-report`.
  Same layout as any skill: a folder with a `SKILL.md` plus its `scripts/`, `assets/`, `references/`.
- Everything else (connectors, investigations, query helpers, rules, ops tools) stays in `SKILLS/`.
- `scripts/validate_skills.py` checks both `SKILLS/` and `reports/`. If you add another
  top-level skills folder, add it there too or its skills skip the pre-commit check.
- Packaged skills live in `cowork/*.skill` and embed their own copy of `SKILL.md`; rebuild the
  package whenever you edit a source `SKILL.md`, wherever it lives.
