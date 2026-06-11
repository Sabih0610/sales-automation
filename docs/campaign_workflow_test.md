# Campaign Workflow Manual Test

Use this checklist to validate the end-to-end campaign flow without accidental sends.

## Start Services

1. Start backend:

   ```powershell
   python main.py serve
   ```

2. Start frontend:

   ```powershell
   cd dashboard
   npm run dev
   ```

3. Open the dashboard and choose a campaign workspace.

## Lead Collection And Enrichment

1. Go to Sources.
2. Add or paste a Sales Navigator people-search URL.
3. Scrape 10 Sales Navigator leads.
4. Confirm the source run completes and leads appear in Leads.
5. Export for ZoomInfo.
6. Add test emails to 3 exported leads in the enrichment file.
7. Upload the enriched file.
8. Confirm Leads shows:
   - 3 leads with email.
   - Leads without email still marked as needing enrichment.
   - Generate drafts is enabled only when enriched leads are selected.

## Touch 1 Draft Review

1. Select the 3 enriched leads.
2. Generate Touch 1 drafts.
3. Confirm Drafts shows:
   - 3 drafts.
   - Status `draft`.
   - Touch `1`.
4. Open one draft.
5. Edit the subject or body.
6. Save the draft.
7. Open Preview and confirm:
   - Recipient is correct.
   - Sender is shown.
   - Touch number is shown.
   - Line breaks are preserved.
8. Approve two drafts.
9. Send a test email for one draft.
10. Send one approved draft.

## Send Result Checks

After sending one approved draft, confirm:

1. Draft status is `sent`.
2. Lead state is `waiting_followup`.
3. `last_touch_sent_at` is set.
4. `next_touch_due_at` is set.
5. Activity includes:
   - `email_sent`
   - `followup_scheduled`
6. Campaign overview metrics update:
   - Emails sent increments.
   - Pipeline Sent increments.

## Follow-Up Demo Mode

1. Go to Sequence.
2. Set Touch 2 delay days to `0`.
3. Set Touch 3 delay days to `0`.
4. Save settings.
5. Go to Queue.
6. Click Refresh due queue.
7. Click Generate due follow-up drafts.
8. Confirm a Touch 2 draft appears.
9. Approve the Touch 2 draft.
10. Send selected approved from Queue.
11. Confirm the lead returns to `waiting_followup` or completes if no later active touch exists.

## Stop Conditions

1. Pick a lead with a future follow-up.
2. Mark the lead replied.
3. Confirm the confirmation prompt appears.
4. Confirm:
   - Lead status is `replied`.
   - Future follow-ups are skipped.
   - Queue no longer shows the lead as due.
   - Activity includes `replied`.
5. Repeat for bounced, unsubscribed, and do not contact using test leads.

## Final Touch Completion

1. Generate the remaining due follow-up.
2. Approve it.
3. Send the final active touch.
4. Confirm:
   - Lead status is `completed`.
   - `completed_at` is set.
   - Activity includes `sequence_completed`.
   - Campaign overview Completed increments.

## Safety Checks

Confirm the system does not:

1. Send without explicit user action.
2. Send to leads without email.
3. Send unapproved drafts.
4. Send duplicate touch emails.
5. Generate duplicate active drafts for the same lead, campaign, and touch.
6. Send outside the configured send window.
7. Send beyond the daily send limit.
8. Send follow-ups after replied, bounced, unsubscribed, or do not contact.

## Build Checks

Run backend compile:

```powershell
python -m py_compile src/api.py src/storage.py src/agents/*.py
```

Run frontend build:

```powershell
cd dashboard
npm run build
```
