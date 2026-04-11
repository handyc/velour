"""Poll one or all enabled MailAccounts for new incoming messages.

    python manage.py poll_inbox                    # poll every enabled account
    python manage.py poll_inbox --mailbox snel     # poll just one

Designed to be run from cron, a systemd timer, or the /mailboxes/<pk>/
"Poll now" button in the UI. Each poll is logged to stdout; failures are
reported per-account so one broken account doesn't stop the others.
"""

from django.core.management.base import BaseCommand, CommandError

from mailboxes.models import MailAccount
from mailroom.polling import poll_account, PollError


class Command(BaseCommand):
    help = 'Poll IMAP accounts for new inbound messages.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mailbox', default=None,
            help='Name of a specific MailAccount to poll. If omitted, polls '
                 'every enabled account that has IMAP credentials set.',
        )

    def handle(self, *args, **opts):
        if opts['mailbox']:
            accounts = MailAccount.objects.filter(name=opts['mailbox'], enabled=True)
            if not accounts.exists():
                raise CommandError(f'No enabled MailAccount named "{opts["mailbox"]}".')
        else:
            accounts = MailAccount.objects.filter(enabled=True).exclude(imap_host='')

        if not accounts.exists():
            self.stdout.write(self.style.WARNING(
                'No mail accounts with IMAP credentials to poll.'
            ))
            return

        total_fetched = 0
        failures = 0
        for account in accounts:
            self.stdout.write(f'Polling {account.name}...')
            try:
                result = poll_account(account)
            except PollError as e:
                self.stdout.write(self.style.ERROR(f'  FAIL: {e}'))
                failures += 1
                continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  UNEXPECTED {type(e).__name__}: {e}'
                ))
                failures += 1
                continue

            total_fetched += result['fetched']
            msg = (
                f'  fetched={result["fetched"]} '
                f'skipped={result["skipped"]} '
                f'total_seen={result["total_known"]}'
            )
            if result['errors']:
                msg += f' errors={len(result["errors"])}'
                self.stdout.write(self.style.WARNING(msg))
                for err in result['errors'][:5]:
                    self.stdout.write(f'    {err}')
                if len(result['errors']) > 5:
                    self.stdout.write(f'    ... {len(result["errors"]) - 5} more')
            else:
                self.stdout.write(self.style.SUCCESS(msg))

        self.stdout.write('')
        summary = f'Polled {accounts.count()} account(s): {total_fetched} new messages'
        if failures:
            summary += f', {failures} failure(s)'
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
