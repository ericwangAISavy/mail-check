# Calendar invitation job matches

Opening an invitation shows paginated suggestions from native sourcing history for the invitation's linked email accounts. Matching uses explicit job URLs first, then company and role evidence. It includes archived history and uses the historical book owner for bidder attribution, rather than the account's current assignment.

Checked rows are labeled “Applied by”; unchecked rows are labeled “Saved by” and remain unverified. Company-only suggestions have possible confidence. Future-only rows and unsafe URLs are excluded. Match confidence describes evidence strength, not a probability or proof of submission. Multiple rows may represent the same job saved by different bidders.

Matching is read-only and runs separately from basic invitation details. It streams sparse history rows and retains only a ranked page in memory. Payments, classification, assignments, and checked status are unchanged.

Calendar descriptions are retained with a 16,000-character bound for future matching, independently of the analysis queue. Existing invitations gain this evidence on their next calendar sync; company/title evidence is usable immediately. Email-backed invitations use retained message text when available.
