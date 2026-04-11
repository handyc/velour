from django.db import models


class InboundMessage(models.Model):
    """One email fetched from a MailAccount's IMAP inbox.

    The raw RFC822 source is stored verbatim so nothing is lost — if the
    parser misses a header or an attachment handler lands in a later release,
    old messages can be re-processed without re-fetching. The polling logic
    uses the (mailbox, uid) unique constraint to skip messages it has
    already seen, so polls are idempotent.

    handled/read are independent: "read" is the human-in-the-loop viewing
    flag (like any webmail), while "handled" is the machine-in-the-loop
    processing flag used by future handler registries (e.g. "this submission
    mail has been parsed and its attachment saved to the filesystem").
    """

    mailbox = models.ForeignKey(
        'mailboxes.MailAccount',
        on_delete=models.CASCADE,
        related_name='inbound_messages',
    )
    uid = models.CharField(
        max_length=64,
        help_text='IMAP UID for this message within the mailbox. Used for '
                  'dedup across polls.',
    )

    # Parsed headers
    from_addr = models.CharField(max_length=500, blank=True)
    to_addr = models.CharField(max_length=1000, blank=True)
    subject = models.CharField(max_length=500, blank=True)

    # Bodies — both captured if available; either may be empty
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    attachment_names = models.JSONField(default=list, blank=True)

    # Timestamps: received_at is the Date: header if parseable, fetched_at
    # is when velour pulled it off the server.
    received_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    # Full RFC822 source for reprocessing / debugging. Indexed by PK only.
    raw = models.TextField(blank=True)

    # User/handler flags — orthogonal: "read" = human saw it, "handled" =
    # a handler module processed it and extracted whatever it needed.
    read = models.BooleanField(default=False)
    handled = models.BooleanField(default=False)
    handler_notes = models.TextField(blank=True)

    class Meta:
        unique_together = [('mailbox', 'uid')]
        ordering = ['-received_at', '-fetched_at']
        indexes = [
            models.Index(fields=['mailbox', 'read']),
            models.Index(fields=['-fetched_at']),
        ]

    def __str__(self):
        return f'{self.from_addr}: {self.subject[:60]}'

    @property
    def best_body(self):
        """Prefer plain text for display; fall back to HTML stripped of tags."""
        if self.body_text:
            return self.body_text
        if self.body_html:
            # Crude tag strip — good enough for a preview line; a full
            # renderer would use html.parser or bleach.
            import re
            return re.sub(r'<[^>]+>', '', self.body_html)
        return ''
