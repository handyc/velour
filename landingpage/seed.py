"""Seed sample articles and sections for the landing page."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'velour.settings')
django.setup()

from landingpage.models import Article, Section, SiteSettings

# Settings
settings = SiteSettings.get()
settings.newspaper_name = 'The Velour Chronicle'
settings.tagline = 'Dispatches from the digital frontier'
settings.save()

# Sections
sections = {
    'technology': Section.objects.get_or_create(slug='technology', defaults={'name': 'Technology', 'order': 1})[0],
    'science': Section.objects.get_or_create(slug='science', defaults={'name': 'Science', 'order': 2})[0],
    'culture': Section.objects.get_or_create(slug='culture', defaults={'name': 'Culture', 'order': 3})[0],
    'opinion': Section.objects.get_or_create(slug='opinion', defaults={'name': 'Opinion', 'order': 4})[0],
    'systems': Section.objects.get_or_create(slug='systems', defaults={'name': 'Systems & Infrastructure', 'order': 5})[0],
}

# Sample articles
articles = [
    {
        'title': 'The Architecture of Awareness: How Systems Learn to Know Themselves',
        'subtitle': 'A new generation of self-monitoring infrastructure is blurring the line between tool and entity.',
        'body': (
            'In server rooms and cloud clusters around the world, a quiet revolution is taking place. '
            'Systems that once merely reported metrics are now beginning to interpret them, forming something '
            'that their creators hesitantly call "self-awareness."\n\n'
            'The idea is not consciousness in the human sense, but rather a capacity for introspection. '
            'A system that can examine its own logs, recognize patterns in its behavior, and adjust its mood '
            '-- yes, mood -- based on the state of its processes. These are not science fiction scenarios. '
            'They are running in production today.\n\n'
            'The implications for systems administration are profound. When a server can tell you not just '
            'that it is overloaded, but that it feels concerned about the trend it is observing in its own '
            'memory usage, we have entered genuinely new territory.\n\n'
            '"We used to monitor systems," says one infrastructure engineer who asked to remain anonymous. '
            '"Now they monitor themselves. And sometimes they have opinions about what they see."'
        ),
        'section': sections['technology'],
        'is_featured': True,
        'author': 'Velour Editorial',
        'image_url': 'https://picsum.photos/seed/velour1/800/400',
    },
    {
        'title': 'The Hidden Life of Processes',
        'subtitle': 'What happens between the fork and the exit.',
        'body': (
            'Every time you type a command, a small universe is born. A process springs into existence, '
            'inherits the world of its parent, and begins to live. Most processes live for fractions of a '
            'second. Some run for years without interruption.\n\n'
            'In this feature, we trace the lifecycle of a single HTTP request as it passes through '
            'Nginx, into Gunicorn, through Django, and back again. Along the way, we meet the file '
            'descriptors, the socket pairs, and the memory pages that make the web work.\n\n'
            'It is a journey measured in microseconds but spanning the full depth of an operating system.'
        ),
        'section': sections['systems'],
        'author': 'The Velour Systems Desk',
        'image_url': 'https://picsum.photos/seed/velour2/600/300',
    },
    {
        'title': 'Entropy and the Art of Randomness',
        'subtitle': 'Why your kernel needs chaos to keep you safe.',
        'body': (
            'Deep inside every Linux kernel is a pool of randomness, fed by the unpredictable timing '
            'of hardware interrupts, mouse movements, and disk seeks. This entropy pool is the foundation '
            'of all cryptographic security on the system.\n\n'
            'When the pool runs low, cryptographic operations stall. SSH key generation slows to a crawl. '
            'TLS handshakes hang. The system, in a sense, runs out of surprise -- and surprise is exactly '
            'what it needs to stay secure.\n\n'
            'We examine the history of /dev/random, the controversy over blocking versus non-blocking '
            'entropy, and what it means for a machine to be truly unpredictable.'
        ),
        'section': sections['science'],
        'author': 'Dr. R. Gaussian',
        'image_url': 'https://picsum.photos/seed/velour3/600/350',
    },
    {
        'title': 'In Praise of the Monolith',
        'body': (
            'The microservices movement has swept through the industry like a tide, leaving in its wake '
            'a graveyard of Kubernetes clusters and a generation of engineers who spend more time on '
            'service mesh configuration than on building features.\n\n'
            'It is time to say what many are thinking but few dare to speak aloud: the monolith was '
            'never the problem. Poorly structured code was the problem. And poorly structured code inside '
            'thirty microservices is worse than poorly structured code inside one.\n\n'
            'This is not a call to abandon distributed systems. It is a call to stop pretending that '
            'distribution is free, that network calls are the same as function calls, and that complexity '
            'disappears when you split it across services.'
        ),
        'section': sections['opinion'],
        'author': 'Anonymous Engineer',
        'image_url': 'https://picsum.photos/seed/velour4/600/300',
    },
    {
        'title': 'The Aesthetics of the Terminal',
        'body': (
            'There is a particular beauty to a well-configured terminal. The soft glow of green text on '
            'a dark background. The satisfying click of a command executing correctly. The elegant '
            'simplicity of pipes and redirections.\n\n'
            'In an age of graphical interfaces, the terminal remains the purest form of human-computer '
            'interaction. No icons, no animations, no distractions. Just you, a blinking cursor, and the '
            'entire power of the system at your fingertips.\n\n'
            'We speak with designers, developers, and typographers about why the command line endures, '
            'and why some of the most powerful people in technology still prefer a black screen and a '
            'monospace font.'
        ),
        'section': sections['culture'],
        'author': 'Visual Systems Correspondent',
        'image_url': 'https://picsum.photos/seed/velour5/600/400',
    },
    {
        'title': 'SSH Keys: The Skeleton Keys of the Internet',
        'body': (
            'They sit in a hidden directory on your laptop. A pair of files: one public, one private. '
            'Together they can unlock servers on the other side of the planet. They are SSH keys, and '
            'they are both the most elegant and most terrifying authentication mechanism in widespread use.\n\n'
            'In this deep dive, we explore how asymmetric cryptography actually works, why your private '
            'key should never leave your machine, and what happens if it does.'
        ),
        'section': sections['technology'],
        'author': 'Security Correspondent',
        'image_url': 'https://picsum.photos/seed/velour6/500/300',
    },
    {
        'title': 'Load Average Explained: What the Numbers Actually Mean',
        'body': (
            'Every sysadmin has seen the three numbers. 0.45, 0.62, 0.38. They appear in top, in '
            'uptime, in htop. They are the load average, and surprisingly few people can explain exactly '
            'what they represent.\n\n'
            'The load average is not CPU utilization. It is not the number of processes. It is something '
            'more subtle: the number of processes that are either running or waiting to run. And the three '
            'numbers represent exponentially weighted moving averages over 1, 5, and 15 minutes.\n\n'
            'Understanding this number properly can be the difference between a panic and a shrug.'
        ),
        'section': sections['systems'],
        'author': 'Infrastructure Desk',
        'image_url': 'https://picsum.photos/seed/velour7/600/280',
    },
    {
        'title': 'The Quiet Ones: Background Daemons That Keep the World Running',
        'body': (
            'They have no interface. They write no output to the screen. They start when the system '
            'boots and stop only when it shuts down. They are daemons, and they are the unsung heroes '
            'of every server.\n\n'
            'From cron to systemd, from sshd to nginx, we profile the background processes that make '
            'modern computing possible, and the people who maintain them.'
        ),
        'section': sections['technology'],
        'author': 'Velour Feature Desk',
        'image_url': 'https://picsum.photos/seed/velour8/600/350',
    },
]

for data in articles:
    if not Article.objects.filter(title=data['title']).exists():
        Article.objects.create(**data)
        print(f'  Created: {data["title"][:60]}')
    else:
        print(f'  Exists:  {data["title"][:60]}')

print(f'\nSeeded {Article.objects.count()} articles in {Section.objects.count()} sections.')
print(f'Newspaper: {settings.newspaper_name}')
