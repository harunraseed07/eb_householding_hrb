# The 20-minute client walkthrough

Read this once before you present. The demo works because of one family you
narrate the whole way through, not because of the number of screens.

Reset first: sidebar **Reset demo to seed**, or
`python scripts/run_pipeline.py --reset`.

---

## The family you will use

The Sullivans of 47 Maple Street, Salem, Massachusetts. They exist in the data
on purpose and behave identically every run.

| Person | In CORE | In Elan card | In CRM |
|---|---|---|---|
| Robert Sullivan | `ROBERT J SULLIVAN`, DOB and tax id on file | `BOB SULLIVAN`, same tax id | `ROB SULIVAN`, surname typo, no tax id, no DOB, stale phone |
| Susan Sullivan | `SUSAN M SULLIVAN` | not present | `SUE SULLIVAN-MARTINEZ`, maiden name |
| Emily Sullivan | `EMILY SULLIVAN` | not present | not present |

Plus **Sullivan HVAC LLC**, owned 60% by Robert and 40% by someone in a
different household.

Three outcomes fall out of that, and they are the whole story:

1. Robert's CORE and CARD rows **link automatically**, on the shared tax id.
2. Susan's maiden name **links automatically**, on surname token overlap.
3. Robert's CRM row **needs a person**. It scores 0.853, inside the review
   band, because the surname is mistyped, the phone disagrees, and there is no
   tax id or birth date to settle it.

---

## Minute 0 to 3 · The problem

Open **Executive summary**. Stay on the KPI row.

> "Eastern Bank has 415 customer records across three systems. Those are not
> 415 customers. They are 226 people living in 123 households, and until now
> nothing in the bank could tell you that."

Point at **Source customer records 415 → Resolved parties 226 → Households
123**, then the funnel chart below.

> "Seventy per cent fewer entities to manage, and $6.2 million of relationship
> balance that was previously spread across three systems under four different
> spellings of the same man's name."

Do not scroll further yet.

## Minute 3 to 6 · What it is worth

Scroll to **Cross-sell opportunities**.

> "Here are eight households holding fifty thousand dollars or more on deposit
> with no lending and no card relationship with the bank. That list is
> invisible when those same people are three separate customer rows. The
> indicative value is a placeholder, eight per cent of idle deposits; you would
> put your own product economics in."

If someone asks where the number comes from, say so plainly: it is a rule, in
the code, that a banker can argue with. That honesty buys credibility for the
rest of the demo.

## Minute 6 to 10 · One household, completely

Go to **Household 360**. It opens on the Sullivans.

Walk the tiles left to right: 4 members, 9 accounts, deposits, lending, cards,
net relationship.

> "Nine accounts across core banking and the Elan platform. The joint checking
> account Robert and Susan hold appears once, not twice. Double counting joint
> balances is the single most common error in hand-built household reporting."

Now point at the **Members** table and slow down. This is the beat the whole
demo turns on.

> "Four members. Except this is a household of three. Look at the fourth row:
> ROB SULIVAN, one source record, from CRM, no birth date, no tax id, no
> demographics. That is Robert, sitting in his own household as a stranger,
> because one letter is missing from his surname."

Let it land, then:

> "Notice the engine did not quietly guess. It put him here as a separate
> person and flagged the pair for a human. In a minute I am going to be that
> human."

Scroll to **Source record provenance**.

> "Underneath, Robert is already two source records: Robert in core and Bob on
> the card platform, linked automatically on a shared tax id. Susan is two as
> well, because CRM has her under her maiden name. Nothing was deleted and
> nothing was overwritten. The original rows are still exactly as each system
> holds them."

Then **Extended household** on the right.

> "Sullivan HVAC. Robert owns sixty per cent, and his co-owner lives in a
> different household, which is why those two households appear as one super
> household. Note what did not happen: the two owners were not merged into one
> person. A business link is a relationship, never an identity."

Toggle **Show unmasked NPI** in the sidebar and toggle it back.

> "Same screen, two roles. Birth dates, tax digits, phone, email and street
> address are masked unless you hold the cleared role. In your environment that
> would be enforced by Unity Catalog column masks in the warehouse, so the
> application cannot grant itself access it does not have."

## Minute 10 to 15 · The decision moment

This is the centre of the demo. Go to **Match stewardship**.

> "232 of 298 compared pairs matched automatically. 52 did not, and those are
> here. These are not failures. They are the pairs where the evidence genuinely
> does not settle the question, and a bank wants a person to decide."

The top case is already **BOB SULLIVAN ↔ ROB SULIVAN, 0.853**. Read the chips
out loud: Tax Id Missing, Surname Strong, Given Name Strong, Dob Missing,
Address Exact, Postal Exact, **Phone Conflict**, Email Missing.

> "Same address, same postal code. Given names are both forms of Robert.
> Surname is one character out. But there is no tax id, no birth date, and the
> phone numbers disagree. The engine scored it eighty-five per cent and
> declined to decide."

Scroll to the two record cards.

> "Green agrees, orange differs, grey italic means one system has no value.
> This is the whole case in one screen, from the source rows, not a summary of
> them."

Open **Feature vector as scored** if the audience is technical.

> "No black box. Each feature, its agreement level, its weight, its
> contribution. Missing fields are excluded from the score rather than counted
> as a disagreement, which matters enormously on CRM data."

Now choose `SAME_PERSON_CONFIRMED`, type a note, and press **Accept match**.

> "Watch what happens."

Go straight back to **Household 360**.

> "Four members became three. ROB SULIVAN is gone as a separate person, and
> Robert now shows CORE, CARD and CRM as his source systems with three records
> behind him. I accepted one pair and three records merged, because identity
> clustering is transitive. Nothing was deleted, and the decision is in the
> audit log with my name on it."

If the household name changed from "SULIVAN / SULLIVAN HOUSEHOLD" to
"SULLIVAN HOUSEHOLD", point at it. The typo was shaping the household label
until the match was confirmed.

## Minute 15 to 18 · Can you trust it

Go to **Model quality**.

> "Every demo claims good matching. Here is ours, measured."

| Say this | About |
|---|---|
| "One hundred per cent precision. Every link we made is correct." | Precision tile |
| "Eighty-four per cent recall. We found eighty-four per cent of the links that exist, and the queue you just used closes the rest." | Recall tile |
| "One hundred per cent blocking recall, and we avoided 99.65% of the comparisons. We made the problem tractable without losing a single true pair." | Blocking tiles |

Then the **score separation** chart.

> "Blue is pairs that really are the same person, orange is pairs that are not.
> Two separate humps means the score is doing real work. The overlap in the
> middle is exactly what the steward queue exists to handle."

Then the **threshold** chart.

> "And this is the trade you are actually buying. Move the auto-match threshold
> right and precision holds but recall falls away. When your team asks for
> fewer false matches, this is the conversation, with numbers."

Finish on the scale table at the bottom.

> "Your scope document says 570,000 customers. Comparing every record to every
> other is 162 billion comparisons. Blocking is not an optimisation here, it is
> the design, and blocking recall is how we prove it is safe."

## Minute 18 to 20 · Governance

Go to **Governance and refresh**.

> "Every decision and every manual correction is appended, never edited: who,
> when, why, and which policy version was in force. Source freshness per feed
> at the last publish. Refresh run history, and if a run fails the app says so
> rather than showing you a stale view as if it were new."

Press **Run monthly refresh** in the sidebar.

> "That just re-ran the whole pipeline the way a monthly batch would. My
> decision survived it. Corrections are anchored to source records rather than
> to internal ids, because internal ids are regenerated every run and an
> override pinned to one would silently attach to the wrong person."

Close on the requirements table at the bottom of the tab.

---

## Questions you will be asked

| Question | Answer |
|---|---|
| Will it run on 570,000 customers? | Blocking and scoring parallelise today. Identity clustering runs on one machine in this POC and becomes GraphFrames connected components on Spark. That is a known, scoped piece of work, not a research problem. |
| How do we tune the matching? | Thresholds and feature weights are configuration, not code. The Model quality tab shows what any change costs before you make it. |
| What about incremental loads? | This POC refreshes a full snapshot. The incremental design is written up in notebook 03: re-score only pairs touching a changed record, re-cluster only the affected components. |
| In-house or vendor-hosted? | Your scope document prefers bank-controlled. This is running in your own catalog, in your own workspace, under your own Unity Catalog grants. Nothing leaves. |
| Is this real customer data? | No. Every record is generated. Tax identifiers are one-way hashes of synthetic strings. That is deliberate: it is the only way to show you measured accuracy. |
| Why not Splink or a commercial MDM tool? | Nothing rules them out. The score here is a transparent weighted sum so a reviewer can see which evidence moved it. A fitted model is the right next step once there is labelled data, and the labels come from the queue you just saw. |
| What happens to our manual corrections? | They survive every refresh. We just demonstrated it. |

---

## Before you present

- [ ] Reset the demo, then click through the whole script once
- [ ] Confirm Household 360 opens on the Sullivans
- [ ] Confirm the top queue case is BOB SULLIVAN ↔ ROB SULIVAN at 0.853
- [ ] Accept it once in rehearsal, check the merge, then reset again
- [ ] Record a screen capture of the full run as a fallback
- [ ] If demoing on Databricks, start the SQL Warehouse ten minutes early
- [ ] Have `src/config.py` open in a second window for the tuning question
