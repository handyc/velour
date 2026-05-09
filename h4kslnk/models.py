"""h4kslnk — outbound link to h4ks.com services.

The h4ks.com ecosystem is small but multi-protocol: vibegames as a
showroom (auto-versioned via GitHub commits when you push to the same
project name), s.h4ks.com as a blob/file paste, chat.h4ks.com as an
IRC server.  This app is the home for everything that talks to it:
documented policies, known contacts, push history, and IRC bot
sessions.

Pushes are dumb on purpose — vibegames keeps versions in git, so
pushing officerpghiresev32.html as project='officerpg' file='index.html'
overwrites the file but preserves the chain.  No version metadata is
stored locally; we just keep a row of when we pushed what so the
dashboard can show "last pushed N minutes ago".
"""

from __future__ import annotations

from django.db import models


class Policy(models.Model):
    """Free-form Markdown notes about how to interact with one
    facet of h4ks.com.  Editable in admin so the rules can grow
    without code changes — example policies:

        slug 'vibegames-naming'
            body 'Project names are lowercase-dash, no spaces.
                  Same name = same vibegames entry; new pushes
                  add a commit instead of a new entry.'

        slug 'irc-etiquette'
            body 'Don't double-message.  Don't ping mattf
                  late at night CET.  Bots prefix nicks with
                  "velour-".'
    """

    slug = models.SlugField(unique=True, max_length=80)
    title = models.CharField(max_length=200)
    body = models.TextField(
        help_text='Markdown.  Read this before any automated action '
                  'that touches the named target.')
    target = models.CharField(
        max_length=40,
        choices=[
            ('vibegames', 'games.h4ks.com'),
            ('shorts',    's.h4ks.com'),
            ('irc',       'chat.h4ks.com'),
            ('general',   'h4ks.com (general)'),
        ],
        default='general',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['target', 'slug']
        verbose_name_plural = 'Policies'

    def __str__(self):
        return f'{self.target}: {self.title}'


class IrcContact(models.Model):
    """A person on chat.h4ks.com we might want a bot to talk with.
    `nick` is canonical (lowercase); `display` is whatever they
    actually use in casing.  `notes` carries free-form context the
    bot should know — favoured topics, time-zone hints, sore spots.
    """
    nick = models.SlugField(unique=True, max_length=32)
    display = models.CharField(max_length=64)
    role = models.CharField(
        max_length=80, blank=True,
        help_text='e.g. "h4ks.com admin", "mattfly — vibegames maintainer".')
    timezone = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['nick']

    def __str__(self):
        return self.display or self.nick


class BotSession(models.Model):
    """One IRC bot run.  A session connects, joins/DMs, exchanges
    up to `message_cap` messages, then disconnects.  Lifecycle:

        created → connecting → running → done
                          ↘ error

    The `message_cap` is the floor we won't cross even if the
    operator forgets to disconnect — a hard spam guard.
    """

    STATUS = [
        ('created',    'Created'),
        ('connecting', 'Connecting'),
        ('running',    'Running'),
        ('done',       'Done'),
        ('error',      'Error'),
    ]

    nick = models.CharField(
        max_length=32,
        help_text='IRC nickname this bot will use.  Convention: '
                  '"velour-<purpose>" so its origin is obvious to '
                  'anyone watching the channel.')
    server = models.CharField(max_length=120, default='chat.h4ks.com')
    port = models.PositiveSmallIntegerField(default=6697)
    use_tls = models.BooleanField(default=True)
    target = models.CharField(
        max_length=80,
        help_text='Either a #channel or a contact nick (PM).')
    purpose = models.CharField(
        max_length=200, blank=True,
        help_text='What this bot is here to discuss/do.  Shown in '
                  'admin and used as part of the LLM system prompt.')
    message_cap = models.PositiveSmallIntegerField(
        default=5,
        help_text='Hard cap on PRIVMSG sends per session.  Spam guard.')
    autonomous = models.BooleanField(
        default=False,
        help_text='If False, the operator must approve each outgoing '
                  'message before it sends.')

    status = models.CharField(max_length=16, choices=STATUS, default='created')
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.nick} → {self.target} ({self.status})'


class BotMessage(models.Model):
    """One IRC message in a session — both incoming and outgoing,
    in a single ordered log so you can read the conversation top
    to bottom from admin."""

    DIRECTION = [
        ('out', 'Sent by bot'),
        ('in',  'Received from peer'),
        ('sys', 'System / log line'),
    ]

    session = models.ForeignKey(
        BotSession, on_delete=models.CASCADE, related_name='messages')
    direction = models.CharField(max_length=4, choices=DIRECTION)
    sender = models.CharField(max_length=64, blank=True)
    body = models.TextField()
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['session', 'at']

    def __str__(self):
        arrow = {'out': '→', 'in': '←', 'sys': '·'}[self.direction]
        return f'{arrow} {self.body[:60]}'


class VibegamePush(models.Model):
    """One push of a local artifact to vibegames as <project>/<filename>.
    Vibegames keeps version history in git automatically; this row
    just records that *we* pushed.  `commit_url` is filled in if the
    upload response gives one back."""

    project = models.SlugField(max_length=80)
    filename = models.CharField(max_length=200, default='index.html')
    source_path = models.CharField(
        max_length=500,
        help_text='Local file we pushed (e.g. isolation/artifacts/'
                  'office/officerpghiresev32.html).')
    bytes_sent = models.PositiveIntegerField(default=0)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    commit_url = models.URLField(blank=True)
    pushed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pushed_at']

    def __str__(self):
        return f'{self.project}/{self.filename} @ {self.pushed_at:%Y-%m-%d %H:%M}'
