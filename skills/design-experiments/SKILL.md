---
name: design-experiments
description: "Design low-effort experiments to validate assumptions before building — prototypes, fake-door / A-B / Wizard-of-Oz tests for an existing product, and XYZ-hypothesis pretotypes (landing pages, explainer videos, pre-orders, concierge MVPs) for a new product. Use when validating assumptions, testing an idea cheaply, or planning product experiments."
---

## Design Experiments

Design experiments that produce maximum validated learning for minimum effort. Take the risky assumptions (from `identify-assumptions` / `prioritize-assumptions`) and turn each into a test of **actual behavior**, not opinion. Read any provided files (PRDs, assumption lists, designs, mockups) first.

### Core principles

- **Measure behavior, not opinions.** What people *do* beats what they *say*.
- **Skin in the game** (Alberto Savoia, *The Right It*) — real commitment (time, money, reputation) is the only reliable demand signal. Prefer tests that ask for it.
- **Your Own Data (YODA)** — collect your own evidence; "the market for your idea does not care about the market for someone else's idea."
- **Test responsibly** — don't put users or the business at risk; for production tests, state the risk-mitigation plan.

### Methods by mode

**Existing product — validate a feature cheaply:**
- First-click / task-completion testing on a prototype
- Feature stub or **fake-door** test
- Technical spike
- **A/B test** in production (with risk mitigation)
- **Wizard of Oz** (manual back-end behind a real-looking front-end)
- Behavioral survey (not opinion-based)

**New product — validate demand with a pretotype:**
First write an **XYZ hypothesis**: *"At least X% of Y will do Z"* (X = expected engagement rate, Y = the specific target market, Z = the committing action). Then test it with 2–3 pretotypes:
- **Landing page** — sign-ups / clicks
- **Explainer video** — engagement / understanding
- **Email campaign** — response / click-through
- **Pre-order or waitlist** — willingness to pay (skin in the game)
- **Concierge / manual MVP** — deliver the value by hand to test it's real

### Output

For each experiment specify:
- **Assumption / hypothesis** — what we believe (XYZ form for new products)
- **Experiment** — exactly what we'll do
- **Metric** — what we'll measure (a behavior)
- **Success threshold** — the value we expect if we're right

Present as a clear table. Save substantial output as markdown.

---

### Further reading

- [Testing Product Ideas: The Ultimate Validation Experiments Library](https://www.productcompass.pm/p/the-ultimate-experiments-library)
- [How to Build the Right Product with Alberto Savoia](https://www.productcompass.pm/p/how-to-build-the-right-product-with)
