# Personal intelligence — Wave 18

Use **Personal intelligence** in an owner or fictional demo workspace. Guest and
remote-device requests cannot inspect these local structures.

Save a fact using `/remember project cedar = Cedar uses Example Studio`. Refresh
the personal view, select this current source, and annotate `Cedar → uses → Example
Studio`. Both entities must occur in the source. Relationships are explicit owner
annotations, with REPORTED/INFERRED labels and a **Why do you think this?** source
view. This is bounded keyword/entity matching, not autonomous entity extraction.
Graph structure never overrides source facts or authorizes actions.

Correct an annotation by removing it and reviewing a replacement. Correcting the
source memory makes its old annotation historical. Retraction hides it; forgetting
the source deletes linked annotations through a foreign-key cascade. Restricted
subjects/audiences and credentials remain filtered by the existing memory policy.

The timeline shows memory valid-from/until dates and current/historical/possible
status, including project statements. An optional as-of timestamp selects claims
valid at that time. These are recorded owner claims, not independently verified
events. Queries are bounded and report truncation. Chat supports `/graph QUERY`,
`/timeline QUERY`, `/goals` and `/briefing` without a model call.

Create, edit, pause/resume, update progress or complete goals explicitly. Completion
requires 100% progress. Revision checks reject stale edits. Goal progress history
is retained separately; **Stop tracking** removes tracking, while forgetting its
supporting memory also removes the goal and progress records.

Routine suggestions require the same explicit episodic statement on at least
three distinct recorded dates. They remain INFERRED and cite supporting memories.
Correct, retract or forget supporting records to remove a mistaken suggestion.
No routine is saved as fact, scheduled or acted on automatically. Briefings are
manual local views; reminder delivery remains a separate opt-in feature.
