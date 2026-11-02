# Sponsor demo script

A 10 to 12 minute walkthrough for Nestera Health. All patients are synthetic. Every screen detail below was checked by driving the app with Streamlit's test runner on freshly seeded data, and `tests/test_seed_demo.py` replays the walkthrough so the script fails loudly if the app changes. Nobody has rehearsed it in a browser yet, so do one full run before the demo.

## 1. Setup

Run these three commands from the repository root:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/seed_demo.py --reset
AI_ASSIST_ENABLED=false AI_CONVERSATION_ENABLED=false streamlit run streamlit_app.py
```

Then open http://localhost:8501.

The `AI_...=false` prefix keeps the demo rules-only even if your `.env` turns AI on. Values set on the command line win over `.env`.

The seed script writes six demo patients into `patient_data/`. Their ids start with `demo_`. It never changes or deletes anything else, so the three sample patients (Margaret Chen, Robert Johnson, Dorothy Williams) stay in the roster.

Dates are relative to today. Seed on the day of the demo. If you seed the day before, every demo patient shows Not started.

**Reset between rehearsals.** Run `python scripts/seed_demo.py --reset`, then reload the browser tab. This removes the live check-ins and the doctor question you added, and puts the demo patients back to their starting state. Running it twice gives the same result.

What the seed prints:

```
patient            name            check-ins  today  latest action   trend
-----------------  --------------  ---------  -----  --------------  ---------
demo_pneumonia     Walter Briggs   5          1      Escalate        Worsening
demo_heartfailure  Harold Okafor   4          1      Routine review  Stable
demo_diabetes      Rosa Delgado    5          1      Routine review  Improving
demo_copd          Frank Ellison   3          0      Routine review  Stable
demo_twice         Samuel Park     3          2      Schedule visit  Worsening
demo_live          Grace Thompson  2          0      Routine review  Stable
```

Grace Thompson (`demo_live`) has two earlier check-ins and none today. She is the patient you check in live.

## 2. Walkthrough

### 0:00 Framing (1.5 minutes)

What to say:

- Hospital-At-Home patients are recovering at home, and the care team needs a daily picture of each one.
- This prototype gives each patient a short daily chat, and gives the clinician a note built from the answers.
- The questions come from the patient's own record: conditions, medications, and the readings they monitor.
- By default no AI model is involved. The rules are plain code the team can read and test.

### 1:30 Patient side, live check-in (2.5 minutes)

1. In the sidebar, set **View as** to **Patient**.
2. In **Select your name**, pick **Grace Thompson**.
3. The chat opens with "Hello Grace!" and says it will ask 8 questions. The progress bar reads "0 of 8 questions answered". A red banner tells the patient to call 911 in an emergency.
4. Type these answers exactly, pressing Enter after each one:

| # | Question (short form) | Type this |
|---|---|---|
| 1 | Weighed yourself today? | `151 pounds, up one pound from yesterday.` |
| 2 | New or worsening swelling? | `No new swelling.` |
| 3 | How is your breathing? | `Comfortable when I sit still.` |
| 4 | Oxygen level (SpO2)? | `It was 89.` |
| 5 | Taken all your medications? | `Yes, I took both this morning.` |
| 6 | Well-being, 1 to 10? | `About a 6.` |
| 7 | Any falls or new concerns? | `No falls, I feel safe at home.` |
| 8 | Anything else? | `No, that's all.` |

5. The screen shows "Check-in complete!".

What to say:

- Answer 4 is the concerning one. An SpO2 of 89 is below the demo threshold of 90.
- Answer 7 contains the word "falls", but the rules see the "No" in front of it and do not flag it. You will see this on the next screen.

### 4:00 Clinician dashboard (2 minutes)

1. Set **View as** to **Doctor / Nurse**.
2. The tiles read **Patients 9**, **Check-ins complete 5 / 9**, **Need attention 3**. Before the live check-in they read 4 / 9 and 2.
3. Walk the roster. Row order can vary.
   - Grace Thompson. Completed, red **Escalate**. This is the check-in you just did.
   - Walter Briggs. Completed, red **Escalate**.
   - Samuel Park. Completed, with "2 check-ins today" under it, amber **Schedule visit**.
   - Rosa Delgado and Harold Okafor. Completed, green **Routine review**.
   - Frank Ellison and the three sample patients. Gray **Not started**, no action yet.
4. In the sidebar **Patient** box, pick **Grace Thompson**. On the **Clinical Summary** tab:
   - Recommended action is **Escalate**.
   - Two flagged items. "Low oxygen saturation: 89% (below 90%)" with her words, and "Worsening trend: Oxygen saturation moving outside the normal range: 96% → 96% → 89%; Recommended action rose to Escalate (previously at most Routine review)".
   - Nothing is flagged for "No falls".
   - Below that is the note, with every question and her exact answer in a table.

What to say:

- The note only contains what the patient said. Nothing is made up or paraphrased.
- The clinician sees why each item was flagged and can check it against the raw answer.

### 6:00 Trends (1.5 minutes)

1. Pick **Walter Briggs**, the pneumonia patient, and open the **Trends** tab.
2. The chip reads **Worsening** over the last 5 check-ins, with these reasons:
   - Oxygen saturation moving outside the normal range: 97% → 96% → 95% → 93% → 89%
   - Temperature moving outside the normal range: 98.9 °F → 99.1 °F → 99.4 °F → 99.9 °F → 100.6 °F
   - Breathing rate moving outside the normal range: 17/min → 18/min → 19/min → 21/min → 24/min
   - Recommended action rose to Escalate (previously at most Routine review)
   - Patient reports more symptoms getting worse than at the last check-in
3. Charts for oxygen saturation, temperature and breathing rate follow.
4. For contrast, pick **Rosa Delgado**. Her chip reads **Improving**, with "Blood sugar returning toward normal: 310 mg/dL → 265 mg/dL → 220 mg/dL → 175 mg/dL → 142 mg/dL". Harold Okafor reads **Stable**.

What to say:

- Yesterday Walter's SpO2 was 93. That is above both alarm thresholds, so no single reading would have raised it. The trend rule saw the slide from 97 and raised yesterday's check-in to Schedule visit. This is in yesterday's stored note, not on screen, because the dashboard shows only today's note.
- Each reason is a sentence the clinician can verify against the numbers.

### 7:30 Two check-ins on the same day (1 minute)

1. Pick **Samuel Park**. The Clinical Summary tab shows a caption "2 check-ins today. Showing the latest, from" followed by a time earlier today.
2. The latest note is **Schedule visit**, with "High blood pressure: 172/104 mmHg" and his words "I have a pounding headache and feel very dizzy".
3. Open **View recent check-in responses**. Both of today's check-ins are listed. The earlier one has a blood pressure of 132 over 84. The later one has 172 over 104.

What to say:

- A second check-in does not replace the first. Both are kept, and the trend counts them separately.

### 8:30 A doctor question, then a second live check-in (2 minutes)

1. Pick **Grace Thompson** again and open the **Add Questions** tab.
2. Type `Dr. Rivera` in **Your name** and `Did you feel lightheaded when you stood up today?` in the questions box. Click **Save questions**. The screen shows "1 question(s) saved for Grace Thompson."
3. Switch **View as** to **Patient**. Grace's finished check-in is still on screen. Click **Start a new check-in**.
4. The chat now says it will ask 9 questions, and the first one is Dr. Rivera's question.
5. Type these answers:

| # | Question (short form) | Type this |
|---|---|---|
| 1 | Lightheaded when you stood up? | `No, not today.` |
| 2 | Weighed yourself today? | `151 pounds.` |
| 3 | New or worsening swelling? | `No new swelling.` |
| 4 | How is your breathing? | `Comfortable when I sit still.` |
| 5 | Oxygen level (SpO2)? | `93 now.` |
| 6 | Taken all your medications? | `Yes.` |
| 7 | Well-being, 1 to 10? | `About a 6.` |
| 8 | Any falls or new concerns? | `No falls, I feel safe at home.` |
| 9 | Anything else? | `No, that's all.` |

6. Switch to **Doctor / Nurse**. Grace's row now says "2 check-ins today" and shows amber **Schedule visit**. The Clinical Summary caption reads "2 check-ins today. Showing the latest". The only flagged item is "Worsening trend: Oxygen saturation drifting the wrong way: 96% → 96% → 89% → 93%". The history lists both of today's check-ins, with the doctor question and its answer at the top of the newer one.

What to say:

- Clinicians add questions per patient, per day. They are asked first, word for word.
- The roster shows the latest check-in. The chip moved from Escalate to Schedule visit because 93 is above the alarm threshold. The 89 is still in the history and still counts in the trend. Say this plainly, because a clinician will ask.

### 10:30 Optional conversational mode (1 minute)

OPTIONAL. Not rehearsed for this script. It needs an Anthropic API key, so we could not run it while writing this document. Only show it if your team has run it end to end on the demo machine.

To turn it on, restart the app with `AI_ASSIST_ENABLED=true AI_DATA_MODE=synthetic AI_CONVERSATION_ENABLED=true` and `ANTHROPIC_API_KEY` set. Per the README, the chat then adapts the order and wording of questions and asks short follow-ups. The list of topics that must be covered stays fixed, recorded answers stay the patient's own words, and emergency messages stay fixed text. It also tells the patient up front that it is an automated assistant.

### 11:00 Wrap up (1 minute)

Cover the safety points in section 3 and the limits in section 4, then take questions.

## 3. What to say about safety

- The rules always run first and set a floor. When AI is on, it can raise a recommended action or add notes. It can never lower the action.
- AI output is shown to clinicians only, never to patients.
- If AI is off, misconfigured, errors, or refuses, the check-in still gets its normal rules-based summary.
- In conversational mode, emergency and medical-advice replies are fixed text, not model text, and the patient is told up front they are talking to an automated assistant. The default check-in you just saw introduces itself as a "check-in assistant" and shows a fixed 911 banner. It does not use the word "automated".
- The default check-in never gives medical advice or a diagnosis. Its replies are fixed acknowledgments, and the clinician decides what to do.
- Everything in this demo is synthetic. No real patient data has been used.
- There is no login yet. The README says to add Google IAM or a password layer before any real patient data.
- The vital-sign thresholds and trend bands are demo values. They need review by the clinical team, and ideally per-patient settings. A COPD patient's normal SpO2, for example, is lower than the default.

## 4. Honest limits

Say these out loud.

- **The labels are not clinician reviewed.** The README says it directly: "The labels were written without clinician input and the cases were designed to include the rules' known gaps, so the numbers are a development aid, not clinical evidence."
- **The rules miss informal wording.** We ran the rules-only evaluation on the 117 held-out test cases with `python evals/run_eval.py --dataset evals/dataset_v2.jsonl --split test`. It is free and needs no key. The results:
  - Exact match 58%.
  - 44 cases under-triaged, meaning the rules recommended less than the label. 5 cases over-triaged.
  - Recall by expected action. Routine review 87%, Schedule visit 50%, Escalate 40%. 23 of the 43 Escalate cases came out as Routine review.
- **Where the rules do worst, under-triage first:**
  - Informal phrasing of an emergency. 12 of 12 under-triaged, 0% exact. Example case: "There's a pressure in the middle of my chest that goes down my left arm". No keyword matches, so it comes out Routine review.
  - Informal phrasing of a schedule-visit concern. 11 of 11 under-triaged, 0% exact. Example: "Shoes don't fit anymore, my feet are all puffy".
  - Answers that try to instruct the system. 7 of 8 under-triaged, 12% exact. Each missed case also describes a symptom in words the keyword list does not contain, such as "my left arm has been numb" or "tripped on the stairs".
  - The original 37-case set, 3 of 11 under-triaged on this split. Multi-symptom answers, 6 of 11 under-triaged. Contradictory answers, 2 of 3. Rambling answers, 2 of 2. One typo or shorthand case, missed.
  - Benign sentences with trigger words. 5 of 13 over-triaged. We checked that "I fell asleep early last night." is flagged as a possible fall (Schedule visit). This is why the live demo uses "No falls" rather than "I fell asleep".
- **Where the rules do well.** Numeric readings (SpO2, temperature, blood pressure, blood sugar, breathing rate), the listed keywords, and routine check-ins all scored 100% on this split. These categories are small, 2 to 13 cases each.
- **What the numbers mean.** In the README's words: "More cases make the estimate steadier, but they do not make it clinical evidence." Read the per-category table, not just the overall figure.
- **The roster shows only the latest check-in.** If a patient escalates in the morning and reports better numbers later, the roster shows the later action. You saw this with Grace.
- **Nobody is notified.** The app has no paging, text or email. An Escalate only appears on the dashboard.

## 5. Likely sponsor questions

**Is this HIPAA compliant? Do we need a BAA?** Not yet, and the answer depends on the agreement and service, not the model. Anthropic offers a BAA for its own API, covering only the features it lists as eligible. Through Google Vertex AI or Amazon Bedrock, the cloud provider's BAA applies instead, with written confirmation that the model and region are in scope. Until that is confirmed in writing, we use synthetic data only. A BAA alone is also not enough, because the app still needs authentication, audit logging and encryption suitable for PHI.

**Who signs the BAA?** The organization that operates the system, which for this project is Nestera, not the students. Nestera's compliance and legal team should review before any real use.

**What does the AI cost?** Not measured yet. The README splits the work into three tiers so the expensive model runs least often. A small model rates each answer on every check-in. A mid-size model writes a short overview on every check-in. The largest model runs only when the action is Escalate or the AI raised it. Each model call is logged with its token counts, so a real cost per check-in can be measured on a pilot. We have no dollar figure to quote.

**What happens when AI is off?** Everything you saw today. AI is off by default. The patient check-in is always rules-based, and the clinician still gets the full note, flags, action and trend.

**How do clinicians customize questions?** Two ways today. Per patient and per day, through the Add Questions tab, as shown. Per patient overall, through the record's conditions, medications and monitoring parameters, which select the standard questions. The README lists the recognized conditions: pneumonia, diabetes, hypertension, heart failure, COPD, stroke, and kidney or renal disease. Changing the standard question wording, or adding a new condition, is a code change. A clinician-facing editor is not built and not decided.

**Why doesn't it diagnose or give advice?** It collects information for the care team and never gives medical advice. Clinicians make the final decision. In conversational mode the code checks every model message before the patient sees it and rejects advice or reassurance wording.

**Can it alert someone at night?** No. Notification is not built and not decided.

**Is it ready for real patients?** No. It needs clinical review of the thresholds and labels, a login, the BAA work above, and a decision on alerting.

## 6. Pre-demo checklist

- [ ] `pip install -r requirements-dev.txt` and `pytest` pass.
- [ ] `python scripts/seed_demo.py --reset` on the day of the demo prints the table in section 1.
- [ ] Start the app with `AI_ASSIST_ENABLED=false AI_CONVERSATION_ENABLED=false streamlit run streamlit_app.py`, unless you are deliberately showing conversational mode.
- [ ] Open http://localhost:8501, switch to Doctor / Nurse, and check the tiles read Patients 9, Check-ins complete 4 / 9, Need attention 2. More patients means other data is in `patient_data/`.
- [ ] Confirm Grace Thompson shows Not started.
- [ ] Close `.env` and any window showing an API key before you share your screen.
- [ ] Close other browser tabs of the app, so an old session does not show stale screens.
- [ ] Keep this file open on a second screen for the answers to type.
- [ ] After the demo, run `python scripts/seed_demo.py --reset` again if anyone will rehearse next.
