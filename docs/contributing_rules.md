# Contributing to akxOS-Pi

---

## Branching Model

| Branch | Purpose |
|--------|----------|
| `main` | Stable branch holding officially released versions. |
| `release/vX.X` | Ongoing development branch for each version milestone |
| `feature/<name>/vX.X` | Short-lived branches for individual features merged into their release branch. |


---

## Commit Template

git commit -m "feat(\<scope\>)-\<release_version\>: \<short summary\>"

### Allowed Commit Types

| **Type** | **Description** | **Example** |
|-----------|------------------|--------------|
| `feat` | New feature addition | `feat(power)-1.0: implement dynamic power model` |
| `fix` | Bug fix or correction | `fix(parser)-1.0: correct PID parsing logic` |
| `docs` | Documentation updates | `docs(releases)-1.0: update roadmap to v5.0` |
| `refactor` | Code restructuring without new features | `refactor(cli)-1.0: simplify argument parsing` |
| `style` | Formatting, comments, or whitespace changes | `style(code)-1.0: format indentation` |
| `test` | Adding or updating tests | `test(power)-1.0: add validation test for leakage model` |
| `chore` | Maintenance or setup tasks | `chore(repo)-1.0: setup .gitignore and folders` |
| `build` | Build system or dependency updates | `build(makefile)-1.0: add kernel module build rules` |
| `perf` | Performance improvement | `perf(model)-1.0: optimize dyn power loop` |

---

