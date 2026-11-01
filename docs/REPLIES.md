# Replying from the app

Open a message in Triage and click **Reply** or **Reply all**. The inline composer shows the sending inbox, recipients and subject. Write a plain-text reply and choose **Send** to stay in the queue, or **Send & Done** to send and then complete the item locally. Done is only set after the outgoing server accepts the reply to all recipients. Replies appear below the original message in this app, including their acceptance time and any delivery uncertainty.

Replies use the account that received the original message. Reply-To takes priority over the sender. Reply all includes original To and Cc recipients, excluding the sending inbox. The original subject and thread are retained. This composer supports text replies; attachments, rich-text composition, forwarding and composing new conversations are separate features.

Drafts are stored separately per message in this browser's local storage. They survive switching messages and reloading the page. Closing the composer retains a draft; discarding a nonempty draft requires a second click. If browser storage is blocked or full, only the in-memory draft remains. Clearing site storage removes saved drafts.

## Outlook

Reconnect the account once to grant Microsoft **Mail.Send**, in addition to Mail.Read and Calendars.Read. If the Microsoft app's delegated API permissions are configured explicitly, add Mail.Send there first. Existing reading and calendar collection do not require the new send permission and keep working before reconnect. The composer offers the reconnect dialog directly, without navigating to Outlook. Sending uses Graph's native reply/replyAll actions and Microsoft keeps the sent copy in its Sent Items.

## IMAP accounts

Open **Accounts → Outgoing mail**, or **Configure outgoing mail** in the reply composer. Set SMTP hostname, port, encryption and username, then **Test & save**. Known Gmail, Yahoo, iCloud and Fastmail IMAP hosts have SMTP suggestions. Custom providers require their own SMTP details. The account's existing app password is read from the OS keyring; no password is copied into SQLite or returned to the browser.

Only SSL/TLS or STARTTLS connections are supported. STARTTLS completes before authentication. Testing connects and signs in but sends no test message. The app reads original Reply-To, To, Cc, Message-ID and References headers using read-only IMAP and sends a threaded MIME reply over SMTP. SMTP replies are recorded in this app; they are not appended to the provider's Sent folder.

## Delivery and access

Only admins can send. Bidder sessions cannot access the reply or outgoing settings endpoints. Existing same-origin checks apply to every send. Automatic mail checks never send replies.

Each Send has a durable operation ID. Repeating an accepted operation returns its existing result instead of sending again. Concurrent duplicates and replies whose delivery outcome is unknown are blocked. The sending request is never automatically retried after a timeout, disconnect or ambiguous server failure, because the provider could already have accepted it. The draft and delivery warning remain visible and editing is locked. **Check send status** reads the existing delivery record. **Retry original send safely** reuses the original operation, body, mode and completion option, so a previously accepted request returns its existing result rather than sending twice. Acceptance means the provider accepted the message, not guaranteed final delivery to the recipient.

Sent text, recipient metadata and delivery status are kept locally in `mail_replies`, independently of inbox retention. SMTP settings are stored in `mail_outgoing`; credentials remain in the OS keyring.
