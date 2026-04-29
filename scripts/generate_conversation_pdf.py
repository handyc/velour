#!/usr/bin/env python3
"""Generate a PDF of the Velour project conversation and design notes."""

from datetime import datetime
from fpdf import FPDF


class ConversationPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'Velour - Project Notes & Conversation Log', align='C')
        self.ln(4)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(30, 80, 160)
        self.ln(4)
        self.cell(0, 10, title)
        self.ln(10)

    def sub_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(50, 50, 50)
        self.ln(2)
        self.cell(0, 8, title)
        self.ln(8)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def code_block(self, text):
        self.set_font('Courier', '', 9)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(30, 30, 30)
        x = self.get_x()
        self.set_x(x + 5)
        self.multi_cell(180, 5, text, fill=True)
        self.ln(3)

    def bullet(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        x = self.get_x()
        self.set_x(x + 5)
        self.cell(5, 5.5, '-')
        self.multi_cell(175, 5.5, text)
        self.ln(1)

    def speaker(self, name):
        self.set_font('Helvetica', 'B', 10)
        if name == 'User':
            self.set_text_color(0, 120, 60)
        else:
            self.set_text_color(30, 80, 160)
        self.cell(0, 7, f'{name}:')
        self.ln(7)


def build_pdf(output_path):
    pdf = ConversationPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title page
    pdf.set_font('Helvetica', 'B', 24)
    pdf.set_text_color(30, 80, 160)
    pdf.ln(40)
    pdf.cell(0, 15, 'Velour', align='C')
    pdf.ln(15)
    pdf.set_font('Helvetica', '', 14)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 10, 'Project Design Notes & Conversation Log', align='C')
    pdf.ln(20)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 8, f'Generated: {datetime.now().strftime("%B %d, %Y at %H:%M")}', align='C')
    pdf.ln(8)
    pdf.cell(0, 8, 'Server: example.com', align='C')

    # --- Section 1: Project Overview ---
    pdf.add_page()
    pdf.section_title('1. Project Overview')
    pdf.body_text(
        'Velour is a Django-based administration panel designed to serve as a '
        'centralized management interface for a Linux server. It runs as a normal Linux '
        'user (velour) with limited permissions, inside that user\'s home directory. '
        'It can optionally elevate to sudo access when an authorized administrator provides '
        'their credentials through the web interface.'
    )

    pdf.sub_title('Core Features')
    pdf.bullet('Web-based terminal interface to the host system')
    pdf.bullet('Django authentication with guest landing page for unauthenticated users')
    pdf.bullet('App Factory: duplicate itself or create new Django apps in datetime-stamped directories')
    pdf.bullet('Human approval workflow for generated apps before deployment')
    pdf.bullet('Production deployment via Supervisor, Gunicorn, and Nginx')
    pdf.bullet('Extended system information dashboard (CPU, memory, disk, network, processes)')
    pdf.bullet('Secure sudo elevation via sudoer credential prompt (per-action, never stored)')

    pdf.sub_title('Django Apps')
    pdf.bullet('dashboard - Guest landing page and authenticated admin dashboard with system overview')
    pdf.bullet('terminal - Web-based shell with command history, sudo toggle (superuser only)')
    pdf.bullet('app_factory - Create blank Django apps or clone Velour, with approve/reject workflow')
    pdf.bullet('sysinfo - Extended system information (CPU, memory, disk, network, processes, logged-in users)')

    # --- Section 2: Architecture ---
    pdf.add_page()
    pdf.section_title('2. Architecture')

    pdf.sub_title('Local + Remote Synchronization')
    pdf.body_text(
        'The system is designed to run in two locations simultaneously:'
    )
    pdf.bullet('Local instance on the developer\'s laptop for development and remote management')
    pdf.bullet('Remote instance on example.com for actual server administration')
    pdf.body_text(
        'The recommended synchronization method is SSH tunneling (Option 1), chosen for '
        'its security properties:'
    )
    pdf.bullet('Zero additional attack surface - no new ports opened on the remote server')
    pdf.bullet('SSH key authentication (battle-tested, industry standard)')
    pdf.bullet('The remote Velour binds only to 127.0.0.1 (not publicly accessible)')
    pdf.bullet('App factory projects sync between local and remote via rsync over SSH')

    pdf.sub_title('Architecture Diagram')
    pdf.code_block(
        '[Your Laptop]                         [example.com]\n'
        'Velour (local)  ---SSH--->    Velour (local-only)\n'
        '  - Local terminal                      - Bound to 127.0.0.1:8000\n'
        '  - Remote terminal (via SSH)           - Supervisor/Gunicorn/Nginx\n'
        '  - App factory (sync via rsync)        - Actual app hosting\n'
        '  - System info (local + remote)        \n'
    )

    pdf.sub_title('Alternatives Considered')
    pdf.body_text('Option 2: WireGuard VPN + API')
    pdf.bullet('Both instances on a private WireGuard network (e.g. 10.0.0.1 local, 10.0.0.2 remote)')
    pdf.bullet('Encrypted private tunnel, no public exposure')
    pdf.bullet('More setup required, but provides a full private network')
    pdf.ln(2)
    pdf.body_text('Option 3: HTTPS API with Mutual TLS')
    pdf.bullet('Remote exposes a locked-down REST API over HTTPS')
    pdf.bullet('Client certificate authentication (mutual TLS) + IP whitelisting + token auth')
    pdf.bullet('Most flexible but does expose a port to the internet')

    # --- Section 3: Security Model ---
    pdf.add_page()
    pdf.section_title('3. Security Model: Sudo Elevation')

    pdf.sub_title('The Pattern')
    pdf.body_text(
        'The app runs as an unprivileged user (velour) that has NO sudo privileges. '
        'When a privileged operation is needed, the web UI prompts the human administrator '
        'for a real sudoer\'s credentials (e.g. handyc\'s username and password). These '
        'credentials are used for that single command and immediately discarded.'
    )

    pdf.sub_title('How It Works')
    pdf.bullet('Normal operations run as velour (unprivileged) - reading logs, checking '
               'system info, managing Django apps, etc.')
    pdf.bullet('Privileged operations trigger a modal/prompt in the browser asking for a '
               'sudoer\'s credentials (e.g. handyc username + password).')
    pdf.bullet('The app uses "sudo -S -u root" with the provided credentials piped via stdin, '
               'never storing them - they exist only for the duration of that one command.')
    pdf.bullet('After execution, the credentials are immediately discarded. No caching, no '
               'session tokens for sudo.')

    pdf.sub_title('Why This Is Safe')
    pdf.bullet('The velour user itself has no sudo privileges - it cannot escalate on its own')
    pdf.bullet('Sudo credentials are provided per-action by a human, like typing your password in a terminal')
    pdf.bullet('Failed attempts get logged by the system\'s normal sudo audit trail (/var/log/auth.log)')
    pdf.bullet('Commands can be further restricted via /etc/sudoers rules')
    pdf.bullet('The app is behind Django auth, so an attacker would need to breach Django login '
               'AND know a sudoer\'s password')

    pdf.sub_title('sudoers Configuration')
    pdf.code_block(
        '# Only allow specific commands when sudo is invoked\n'
        'handyc ALL=(ALL) ALL\n'
        '# velour has NO sudo entry -\n'
        '# it relies on the human\'s credentials'
    )

    pdf.sub_title('Optional Hardening')
    pdf.bullet('Rate limiting on sudo attempts (lock out after 3 failures)')
    pdf.bullet('Audit log in the Django database - who ran what, when, from what IP')
    pdf.bullet('Command allowlist - only permit specific sudo commands through the web UI')
    pdf.bullet('2FA - require a TOTP code alongside the sudo password')

    # --- Section 4: Planned Features ---
    pdf.add_page()
    pdf.section_title('4. Planned Features (To Build)')

    pdf.sub_title('SSH-Based Remote Mode')
    pdf.bullet('A "remote" app with SSH connection settings (host, key path, user)')
    pdf.bullet('A remote terminal that pipes commands over SSH via paramiko')
    pdf.bullet('Remote system info fetched over SSH')
    pdf.bullet('Rsync-based app sync between local and remote')

    pdf.sub_title('Sudo Elevation UI')
    pdf.bullet('Sudo prompt modal that appears when a privileged action is requested')
    pdf.bullet('Backend endpoint that accepts sudoer credentials, runs the single command, discards them')
    pdf.bullet('Audit log model tracking every sudo attempt (success or failure)')
    pdf.bullet('Rate limiting on failed sudo attempts')

    # --- Section 5: Project Structure ---
    pdf.add_page()
    pdf.section_title('5. Project Structure')

    pdf.code_block(
        'vHC5jgyo_9apr2026/\n'
        '  manage.py\n'
        '  requirements.txt\n'
        '  db.sqlite3\n'
        '  velour/          # Django project config\n'
        '    settings.py\n'
        '    urls.py\n'
        '    wsgi.py / asgi.py\n'
        '  dashboard/              # Landing page + dashboard\n'
        '  terminal/               # Web terminal\n'
        '  app_factory/            # App creation + approval\n'
        '  sysinfo/                # Extended system info\n'
        '  templates/              # All HTML templates\n'
        '  static/css/style.css    # Stylesheet\n'
        '  deploy/                 # Production configs\n'
        '    supervisor.conf\n'
        '    nginx.conf\n'
        '    gunicorn.conf.py\n'
        '  venv/                   # Virtual environment\n'
    )

    pdf.sub_title('Deployment Config Locations (Production)')
    pdf.bullet('Supervisor: /etc/supervisor/conf.d/velour.conf (symlink to deploy/supervisor.conf)')
    pdf.bullet('Nginx: /etc/nginx/sites-enabled/velour (symlink to deploy/nginx.conf)')
    pdf.bullet('App runs from: /home/velour/')

    # --- Section 6: Conversation Log ---
    pdf.add_page()
    pdf.section_title('6. Conversation Log (April 9, 2026)')

    pdf.speaker('User')
    pdf.body_text(
        'I would like to create a Django app that acts as a kind of master app for my entire '
        'server. This app would be tested on my local machine first, but then moved to a web '
        'server in the cloud. This app would be like an administration panel that could be '
        'granted sudo access if desirable, but would normally run as a normal Linux user with '
        'limited permissions, running inside that user\'s home directory. This app would '
        'feature a terminal that could act as an interface to the host system. This app would '
        'use the Django authentication system to limit access, and would have a different '
        'guest landing page displayed when the user is not logged in. This Django app would '
        'also be able to duplicate itself and to make other kinds of Django apps, which would '
        'be written to datetime stamped directories. These apps would then be run by a human '
        'for approval, and if approved would then be moved to their own Linux user directory '
        'to be isolated and installed permanently using Supervisor to keep them running, '
        'Gunicorn to create a socket and Nginx to manage that socket.'
    )

    pdf.speaker('Claude')
    pdf.body_text(
        'Built the complete Django project with: dashboard app (guest landing + admin dashboard), '
        'terminal app (web-based shell with sudo toggle), app_factory (create/clone Django apps '
        'with datetime-stamped directories and approval workflow), production deploy configs '
        '(Supervisor, Nginx, Gunicorn), and virtual environment with all dependencies.'
    )

    pdf.speaker('User')
    pdf.body_text(
        'I would like to have two versions of this system running -- one on the actual host '
        'server I manage in the cloud, which is located at example.com, and the other running '
        'locally on this machine (my personal laptop). These two versions of the app would '
        'somehow be synchronized, so that when I am using my laptop, I have a live context '
        'window that interacts with and manages the remote server. How is it possible to do '
        'this safely?'
    )

    pdf.speaker('Claude')
    pdf.body_text(
        'Recommended SSH tunnel approach (Option 1) as safest: local Velour connects '
        'to example.com via SSH to run commands and sync state. Remote instance never exposed to '
        'public internet, only listens on 127.0.0.1. Also presented WireGuard VPN (Option 2) '
        'and HTTPS with mutual TLS (Option 3) as alternatives.'
    )

    pdf.speaker('User')
    pdf.body_text(
        'I would create a new Linux user specifically for the app to run. I would want the app '
        'to be able to elevate to sudo permissions if absolutely necessary, but I also would not '
        'want it to be a security backdoor. So what I would really want is for the app to run as '
        'its own user (e.g. velour) but when prompted for sudo access, be able to request '
        'the username and password of an actual sudoer user (e.g. handyc). In this way the admin '
        'would have to verify sudo tasks by logging in through the app.'
    )

    pdf.speaker('Claude')
    pdf.body_text(
        'Confirmed this is a solid security model. The velour user has NO sudo privileges '
        'itself. Privileged operations trigger a browser prompt for a real sudoer\'s credentials, '
        'which are used for that single command via "sudo -S" and immediately discarded. '
        'Recommended optional hardening: rate limiting, audit logging, command allowlists, and 2FA.'
    )

    pdf.speaker('User')
    pdf.body_text(
        'Could you put everything you\'ve said so far into a PDF so I can review it later '
        'in case I forget? And add the rest of this conversation as well, as we go.'
    )

    pdf.speaker('Claude')
    pdf.body_text('Generated this PDF document.')

    # Save
    pdf.output(output_path)
    print(f'PDF saved to: {output_path}')


if __name__ == '__main__':
    build_pdf('Master_Control_Notes.pdf')
