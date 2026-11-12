# Planning

Load when a case needs more than one action, or someone else must act first.

1. Rebuild the state from the case: who asked for what, what has happened, what is still open.
   "Now" is the latest event in the case, never another date.
2. Check the actions already taken in the history. Never act twice on one request.
3. List the remaining actions in order, one tool call each. Mark those waiting on someone else.
4. Do the first action that is not waiting, and read its result before the next.
5. When an action fails, retry once. If it fails again, stop and load escalation.
6. When the next action waits on someone else, ask them (load communications) and finish with
   STATE: NEEDS_INFO.
7. Identical messages minutes apart are one message; identical reminders days apart are
   separate chases.
