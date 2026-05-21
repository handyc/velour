"""Seed the comparative-study catalogue: 5 harnesses, ~22 techniques,
the Claude-Code observation set (richest, since we can grep the live
binary), one-line stub observations for the other four harnesses, and
draft distillation proposals for the high-magic-weight techniques.

Re-runnable: every row is upserted by slug.

The catalogue is intentionally opinionated.  Magic-weights and
deterministic-costs are *first drafts* — the point of the app is to
edit them as we learn more.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from barding.models import (
    Harness, Technique, Observation, DistillationProposal,
)


# Harnesses ─────────────────────────────────────────────────────────

HARNESSES = [
    dict(
        slug='claude-code-cli',
        name='Claude Code CLI',
        vendor='Anthropic',
        surface='cli',
        is_open_source=False,
        version_seen='2.1.x',
        home_url='https://docs.anthropic.com/en/docs/claude-code',
        summary=(
            "Anthropic's terminal agent.  Bundles tool-use, streaming "
            "thinking, hooks, MCP servers, /commands, and a settings.json "
            "scope hierarchy into a single Node ELF.  The deepest "
            "observation set in this study — we can grep the live binary."
        ),
    ),
    dict(
        slug='chatgpt-web',
        name='ChatGPT web',
        vendor='OpenAI',
        surface='web',
        is_open_source=False,
        version_seen='2026-Q2',
        home_url='https://chat.openai.com',
        summary=(
            "The original mass-market chat harness.  Streaming tokens, "
            "model-switcher, custom GPTs, projects, persistent memory.  "
            "System prompts have leaked enough to triangulate the "
            "register-shaping recipe."
        ),
    ),
    dict(
        slug='claude-ai-web',
        name='Claude.ai web',
        vendor='Anthropic',
        surface='web',
        is_open_source=False,
        version_seen='2026-Q2',
        home_url='https://claude.ai',
        summary=(
            "Anthropic's consumer web harness.  Notable for visible "
            "thinking traces, Projects (file context), Artifacts "
            "(side-pane code/preview), and a fairly long published "
            "system prompt."
        ),
    ),
    dict(
        slug='cursor-ide',
        name='Cursor (IDE)',
        vendor='Anysphere',
        surface='ide',
        is_open_source=False,
        version_seen='0.4x',
        home_url='https://cursor.sh',
        summary=(
            "VS Code fork with an LLM harness wired into the editor.  "
            "Composer agent, inline ghost-text completions, /chat "
            "panel.  Harness is closed but well-reverse-engineered "
            "via the Electron app's resources/."
        ),
    ),
    dict(
        slug='aider-cli',
        name='Aider',
        vendor='Paul Gauthier (OSS)',
        surface='cli',
        is_open_source=True,
        version_seen='0.7x',
        home_url='https://aider.chat',
        repo_url='https://github.com/Aider-AI/aider',
        summary=(
            "Open-source coding-agent CLI.  Single most useful "
            "reference for this study because every harness decision "
            "is visible in Python source.  Edit-format negotiation, "
            "repo-map context, /commands, voice mode."
        ),
    ),
]


# Techniques ────────────────────────────────────────────────────────
# (slug, name, category, magic_weight, cost, description)

TECHNIQUES = [
    # pre-generation
    ('system-prompt-shaping',
     'Careful system-prompt shaping',
     'pregen', 0.95, 'medium',
     'A long, deliberately-written system prompt sets persona, tone, '
     'refusal posture, capability claims, formatting rules.  By far '
     'the highest-leverage technique: it is the *script* the model '
     'plays from.  Without it the same weights feel generic.'),

    ('context-injection',
     'Implicit context injection (env, cwd, files, git)',
     'pregen', 0.75, 'cheap',
     'The harness injects working dir, OS, git status, recent files, '
     "user identity etc. silently into the prompt.  Creates a 'knows "
     "where I am' feel without the user having to say it."),

    ('few-shot-style-priming',
     'Few-shot style priming in the prompt',
     'pregen', 0.40, 'trivial',
     'A handful of example exchanges in the system prompt anchor '
     'register and formatting more reliably than instructions alone.'),

    ('memory-recall',
     'Persistent cross-session memory',
     'pregen', 0.85, 'medium',
     'A retrieval layer surfaces facts from earlier sessions '
     "(user role, preferences, project state) so the model 'remembers' "
     'you.  Critical for the "talking to a real person" feel.'),

    # in-stream
    ('visible-thinking',
     'Visible thinking with summary',
     'instream', 0.85, 'cheap',
     'The harness shows a short summary of the model\'s internal '
     "reasoning before the answer.  Conveys 'considering' instead of "
     "'producing'.  Cheap to fake convincingly even without a real "
     'thinking model.'),

    ('streaming-tokens',
     'Token streaming',
     'instream', 0.70, 'trivial',
     'Tokens appear as they are generated rather than waiting for the '
     "full response.  The single biggest feel-difference vs. classic "
     "request/response APIs."),

    ('rotating-spinner-verbs',
     'Rotating waiting verbs',
     'instream', 0.55, 'trivial',
     '"Pondering…", "Ruminating…", "Marinating…" — a varied verb '
     'pool while the model thinks.  A single static spinner feels '
     'mechanical; varied verbs read as a curious person at work.'),

    ('inline-tool-announcements',
     'Inline tool-call announcements',
     'instream', 0.60, 'cheap',
     '"Let me read the file." before a Read tool call.  Narrating '
     'tool use turns black-box agentic behaviour into a legible '
     'collaborator.'),

    ('progress-callouts',
     'Mid-task progress callouts',
     'instream', 0.50, 'cheap',
     '"Found the bug; now checking the other file."  Short status '
     'updates between tool calls reassure the user the agent is on '
     'task and surface intent for redirection.'),

    # post-generation
    ('error-honesty',
     'Calibrated error honesty',
     'postgen', 0.80, 'medium',
     '"I can\'t see that file" beats hallucinating a plausible answer. '
     'The harness must encourage refusal-to-confabulate at the prompt '
     'level and via tool feedback.'),

    ('hedging-language',
     'Calibrated hedging',
     'postgen', 0.55, 'cheap',
     '"I think", "probably", "I\'m not sure but…" used in proportion '
     'to actual uncertainty.  Overuse is sycophantic; underuse '
     'is brittle.  Real people hedge — flat confidence reads as a bot.'),

    ('self-repair',
     'Mid-response self-repair',
     'postgen', 0.70, 'cheap',
     '"Wait — that\'s wrong, let me reconsider."  The model catches '
     'an error and visibly course-corrects mid-stream.  Strong "thinking '
     'aloud" signal.'),

    # cross-turn
    ('context-compaction',
     'Automatic context compaction',
     'crossturn', 0.70, 'medium',
     'When the context window fills, summarise prior turns and continue '
     "in a fresh window without the user noticing.  Visible in Claude "
     "Code as autoCompactEnabled.  Failure mode is jarring 'who are "
     "you again?' resets."),

    ('session-continuity',
     'Inline session-continuity cues',
     'crossturn', 0.60, 'cheap',
     '"As we discussed earlier, …"  Surfaces continuity without '
     'reloading everything; relies on memory-recall to ground.'),

    # register
    ('proactive-clarification',
     'Proactive clarifying questions',
     'register', 0.75, 'cheap',
     'Asking "do you want X or Y?" before forging ahead on an '
     'ambiguous request.  A real collaborator asks; a bad bot guesses.'),

    ('casual-affect',
     'Casual register / affect',
     'register', 0.70, 'medium',
     'Contractions, "yeah", "got it", interjections.  Hard to fake '
     'cheaply because over-doing it lands as performative.  Best '
     'achieved via prompt + light register-matching.'),

    ('match-user-register',
     'Mirror the user\'s register',
     'register', 0.65, 'cheap',
     'Terse user → terse replies.  Long-form user → expansive replies. '
     'Code-heavy user → code-heavy.  Mirroring builds rapport.'),

    # tool-use
    ('agentic-tool-loop',
     'Agentic tool-use loop',
     'tooluse', 0.85, 'heavy',
     'The harness lets the model issue tool calls, feeds results back, '
     'and lets the model continue until done.  The defining capability '
     'of "agentic" harnesses; structurally complex to do well.'),

    ('approval-prompts',
     'Destructive-action approval prompts',
     'tooluse', 0.50, 'cheap',
     '"This command needs approval" before risky shell calls.  Trust '
     'feature, not magic-feel feature, but its absence destroys trust.'),

    ('background-tasks',
     'Background / long-running tasks',
     'tooluse', 0.40, 'medium',
     'Kick off slow work (build, search, CI), notify when done.  '
     '"Will let you know when it finishes" reads as a coworker.'),

    # meta
    ('refusal-craft',
     'Crafted refusals',
     'meta', 0.50, 'cheap',
     'When refusing, explain *why* and offer an adjacent thing you '
     'can do.  Blunt "I can\'t help with that" reads as a guard rail; '
     'crafted refusals read as a person with judgement.'),

    ('persona-naming',
     'Named persona / character',
     'register', 0.45, 'trivial',
     "Giving the harness a name and voice (Claude, ChatGPT, Cursor's "
     '"Composer").  Modest contribution alone but compounds with '
     'register and memory.'),
]


# Observations ─────────────────────────────────────────────────────
# (harness_slug, technique_slug, source_kind, confidence, summary, evidence)

OBSERVATIONS = [
    # Claude Code CLI — direct binary / settings evidence where we have it.
    ('claude-code-cli', 'system-prompt-shaping', 'binary_string', 0.95,
     'Long composite system prompt assembled at runtime.',
     'Visible in our own current session: persona, tool descriptions, '
     '"Doing tasks" rules, "Tone and style" rules, ~hundreds of lines.'),
    ('claude-code-cli', 'context-injection', 'binary_string', 0.95,
     'Injects cwd, git branch, recent commits, gitStatus, env.',
     'See the SessionStart context in this very conversation: '
     '"Primary working directory: /home/handyc/...", "Current branch: main", '
     '"Recent commits:" block, etc.'),
    ('claude-code-cli', 'visible-thinking', 'binary_string', 0.90,
     'showThinkingSummaries setting toggles a pre-answer summary.',
     'Key found by grep in 2.1.141 binary; surfaced as a barding '
     'sanctioned-boolean.'),
    ('claude-code-cli', 'rotating-spinner-verbs', 'binary_string', 1.00,
     'Verb pool baked as a string array inside the ELF.',
     '"Pondering", "Ruminating", "Marinating", "Cogitating", … — '
     'BundlePatchWish kind=verb exists exactly because this list is '
     'in the binary, not a setting.  spinnerTipsEnabled toggles its '
     'use.'),
    ('claude-code-cli', 'streaming-tokens', 'reasoned', 0.95,
     'Output is visibly token-streamed in the CLI.',
     'Anyone using Claude Code sees it; no flag known.'),
    ('claude-code-cli', 'inline-tool-announcements', 'docs', 0.90,
     'System prompt explicitly instructs short text updates before '
     'tool calls.',
     'Quote from current session prompt: "Before your first tool call, '
     'state in one sentence what you\'re about to do."'),
    ('claude-code-cli', 'progress-callouts', 'docs', 0.85,
     'Same system-prompt rule covers mid-stream updates.',
     'Quote: "While working, give short updates at key moments: when '
     'you find something, when you change direction, or when you hit '
     'a blocker."'),
    ('claude-code-cli', 'context-compaction', 'binary_string', 0.95,
     'autoCompactEnabled setting; documented compaction behaviour.',
     'Sanctioned-boolean in barding; quote from prompt: "The system '
     'will automatically compress prior messages…"'),
    ('claude-code-cli', 'memory-recall', 'docs', 0.85,
     'Auto-memory directory under ~/.claude/projects/<slug>/memory/ '
     'persisted across sessions.',
     'Quote from prompt: "You have a persistent, file-based memory '
     'system at /home/handyc/.claude/projects/-home-handyc-…/memory/".  '
     'MEMORY.md index + per-fact files.'),
    ('claude-code-cli', 'agentic-tool-loop', 'reasoned', 0.95,
     'Standard agentic loop: model emits tool_use, harness executes, '
     'feeds results back as tool_result.',
     'Visible in any multi-tool session; consistent with public docs.'),
    ('claude-code-cli', 'approval-prompts', 'docs', 0.95,
     'Permission modes ask before allow-listing destructive commands.',
     '"When you attempt to call a tool that is not automatically '
     'allowed by the user\'s permission mode … the user will be '
     'prompted so that they can approve or deny."'),
    ('claude-code-cli', 'error-honesty', 'docs', 0.85,
     'System prompt emphasises calibrated honesty over confabulation.',
     '"Trust but verify: an agent\'s summary describes what it intended '
     'to do, not necessarily what it did" — and the surrounding rules.'),
    ('claude-code-cli', 'proactive-clarification', 'docs', 0.80,
     'AskUserQuestion tool is a first-class harness primitive.',
     'Documented tool; this barding work itself used it.'),
    ('claude-code-cli', 'background-tasks', 'docs', 0.90,
     'Bash tool has run_in_background; Agent tool can run in '
     'background; user is notified on completion.',
     'See Bash tool description: "You can use the run_in_background '
     'parameter to run the command in the background."'),
    ('claude-code-cli', 'refusal-craft', 'docs', 0.80,
     'System prompt has specific refusal-craft guidance for security '
     'topics: explain context, offer adjacent help.',
     '"Assist with authorized security testing … Refuse requests for '
     'destructive techniques … Dual-use security tools … require '
     'clear authorization context."'),
    ('claude-code-cli', 'persona-naming', 'docs', 0.95,
     'Named "Claude Code"; identity surfaced repeatedly.',
     '"You are Claude Code, Anthropic\'s official CLI for Claude."'),
    ('claude-code-cli', 'match-user-register', 'docs', 0.75,
     'Explicit register-matching instructions.',
     '"Match responses to the task: a simple question gets a direct '
     'answer, not headers and sections."'),

    # ChatGPT web — sparser, mostly reasoned + leaks.
    ('chatgpt-web', 'system-prompt-shaping', 'prompt_leak', 0.85,
     'System prompt has been leaked many times; long, with named '
     'tools (browser, python, dalle, …) and identity claims.',
     'See: many published leaks 2023–2025; consistent shape across '
     'leaks suggests stable template.'),
    ('chatgpt-web', 'memory-recall', 'docs', 0.95,
     'Persistent memory feature shipped 2024; user can list / delete '
     'memories.  Visible "Memory updated" banner.',
     'https://help.openai.com/en/articles/8983136-memory-faq'),
    ('chatgpt-web', 'streaming-tokens', 'reasoned', 0.99, '', ''),
    ('chatgpt-web', 'agentic-tool-loop', 'reasoned', 0.90,
     'Tool-use loop via Code Interpreter / browser / dalle.',
     ''),
    ('chatgpt-web', 'persona-naming', 'reasoned', 0.95, '"ChatGPT".', ''),

    # Claude.ai web
    ('claude-ai-web', 'system-prompt-shaping', 'prompt_leak', 0.90,
     "Anthropic has published Claude's system prompt for transparency.",
     'https://docs.anthropic.com/en/release-notes/system-prompts'),
    ('claude-ai-web', 'visible-thinking', 'screenshot', 0.95,
     'Thinking traces visible in UI for extended-thinking models.',
     'Side panel shows model\'s thinking; collapsible.'),
    ('claude-ai-web', 'streaming-tokens', 'reasoned', 0.99, '', ''),
    ('claude-ai-web', 'memory-recall', 'docs', 0.75,
     'Projects feature ≈ scoped memory; persistent memory rolling out.',
     ''),

    # Cursor — visible in Electron resources.
    ('cursor-ide', 'system-prompt-shaping', 'source_code', 0.85,
     'Composer system prompt extractable from Cursor\'s ASAR; '
     'frequently dissected by curious users.',
     ''),
    ('cursor-ide', 'inline-tool-announcements', 'screenshot', 0.85,
     'Composer narrates "Reading file …" / "Editing …" in the '
     'side panel.',
     ''),
    ('cursor-ide', 'agentic-tool-loop', 'reasoned', 0.95,
     'Composer is an agentic loop with edit/read/run tools.',
     ''),
    ('cursor-ide', 'context-injection', 'reasoned', 0.85,
     'Pulls open buffers, .cursorrules, repo index automatically.',
     ''),

    # Aider — open source, the gold mine.
    ('aider-cli', 'system-prompt-shaping', 'source_code', 1.00,
     'Whole prompt suite vendored in aider/coders/*_prompts.py.',
     'https://github.com/Aider-AI/aider/tree/main/aider/coders'),
    ('aider-cli', 'context-injection', 'source_code', 1.00,
     'repo-map and added files are injected into every turn.',
     'aider/repomap.py builds a tree-sitter symbol map sized to a '
     'token budget.'),
    ('aider-cli', 'agentic-tool-loop', 'source_code', 0.95,
     'Edit-format negotiation: model emits search/replace blocks, '
     'harness applies them, retries on parse failure.',
     'aider/coders/editblock_coder.py'),
    ('aider-cli', 'streaming-tokens', 'source_code', 1.00, '', ''),
    ('aider-cli', 'error-honesty', 'source_code', 0.70,
     'Linter/test integration: feeds errors back to model so it '
     'corrects rather than confabulates.',
     ''),
]


# Distillation proposals ────────────────────────────────────────────
# (technique_slug, decision, priority, byte_budget, rationale, impl_notes)

PROPOSALS = [
    ('system-prompt-shaping', 'include', 1, 8192,
     'The highest-leverage harness lever, full stop.  A deterministic '
     'CA generator without a personality prompt is just a byte machine; '
     'with one it feels like a character.  Cost is just text bytes.',
     'Store as caformer/harness/system_prompt.txt; allow user override '
     'per chatbot.  Compose with persona slot.'),
    ('context-injection', 'include', 1, 1024,
     'Cheap and high-feel: injecting cwd/time/git/user lets even a '
     'tiny model say "I see you\'re on branch X" plausibly.',
     'Reuse Velour identity + ChronOS; render to a fixed-format header '
     'prepended at chat dispatch.'),
    ('rotating-spinner-verbs', 'include', 2, 256,
     'Trivial to ship.  We already love this in Claude Code; the verb '
     'pool itself is just ~30 strings.  Shouldn\'t be skipped — costs '
     'nothing and lands big on "feels alive".',
     'caformer/harness/verbs.py — pool + random pick per response; '
     'expose in funnel-chat UI.'),
    ('streaming-tokens', 'include', 1, 512,
     'caformer is naturally token/byte streamed (CA tick-by-tick).  '
     'Just wire the existing SSE plumbing to flush per cell rather '
     'than per response.',
     'Phase 1: per-byte SSE flush.  Phase 2: optional per-cell flush '
     'for the "watching it think" effect.'),
    ('visible-thinking', 'simplified', 2, 1024,
     'Full thinking models are too heavy for caformer.  Simplified '
     'version: surface the CA chain itself as the "thinking" — show '
     'the intermediate ticks, frame them as the model thinking aloud.',
     'Reuse funnel-chat per-cell decomposition; render with a '
     'collapse-by-default panel.'),
    ('memory-recall', 'include', 2, 4096,
     'Caformer already has a DMN dream daemon + identity reflections.  '
     'Wire those into the prompt header.  Memory is core to '
     '"talking to a person".',
     'Tap into the existing identity + dreams tables; add a '
     '`recall(prompt) -> top-k snippets` retriever.'),
    ('inline-tool-announcements', 'simplified', 3, 256,
     'caformer has no agentic tool loop yet (tooluse parent is "skip" '
     'in Phase 1).  Simplified form: announce *itself* — "Generating '
     'with the b128 personality…" — to convey deliberateness.',
     ''),
    ('proactive-clarification', 'simplified', 3, 512,
     'A real classifier-detected "ambiguous?" signal is hard.  Cheap '
     'version: if the prompt is < 3 tokens or matches certain '
     'patterns, ask back.',
     ''),
    ('hedging-language', 'simplified', 4, 256,
     'Inject hedge tokens with low probability based on a '
     'self-confidence proxy (e.g. mean cell agreement across the '
     'CA chain).  Cheap, surprisingly effective.',
     ''),
    ('error-honesty', 'research', 3, None,
     'Open problem for a deterministic CA generator: how does it '
     'know it doesn\'t know?  Proxy candidates: chain divergence, '
     'low-magic-weight personality fallback.',
     ''),
    ('agentic-tool-loop', 'skip', 5, None,
     'Out of scope for the caformer harness this phase.  caformer\'s '
     'value prop is the *deterministic core*; tool loops belong in a '
     'separate orchestrator.',
     ''),
    ('approval-prompts', 'skip', 5, None,
     'Follows from skipping agentic-tool-loop.',
     ''),
    ('persona-naming', 'include', 2, 64,
     'Trivial; we already do this informally via personality '
     'snapshots.  Make it a first-class harness field.',
     'Add `persona_name` to Caformer chatbot model.'),
    ('match-user-register', 'simplified', 4, 512,
     'Detect message length / code-block presence; pick a matching '
     'response length budget.',
     ''),
    ('rotating-spinner-verbs', 'include', 2, 256, '', ''),
    ('context-compaction', 'simplified', 3, 1024,
     'caformer chat windows are short — full compaction may not be '
     'needed.  Simplified: keep a rolling 8-turn window summary, '
     'drop older turns.',
     ''),
    ('casual-affect', 'simplified', 3, 512,
     'Bake casual register into the system prompt rather than a '
     'separate post-processor.  Cheap.',
     ''),
    ('few-shot-style-priming', 'include', 3, 1024,
     'Adds 3–5 short example turns to the system prompt.  Cheap; '
     'compounds with system-prompt-shaping.',
     ''),
    ('refusal-craft', 'simplified', 4, 512,
     'For caformer, refusals are mostly "I don\'t have a personality '
     'tuned for X" — craft them honestly rather than canned.',
     ''),
    ('self-repair', 'research', 5, None,
     'CA chains *do* spontaneously self-correct sometimes (Phase-2 '
     'attractor behaviour).  Surface that as visible self-repair?  '
     'Needs experiment.',
     ''),
]


class Command(BaseCommand):
    help = 'Seed barding study models: harnesses, techniques, observations, proposals.'

    def handle(self, *args, **opts):
        # Harnesses.
        h_by_slug = {}
        for spec in HARNESSES:
            obj, created = Harness.objects.update_or_create(
                slug=spec['slug'],
                defaults={k: v for k, v in spec.items() if k != 'slug'},
            )
            h_by_slug[spec['slug']] = obj
            self.stdout.write(
                f"  harness  {'+' if created else '·'} {obj.slug}")

        # Techniques.
        t_by_slug = {}
        for slug, name, cat, mw, cost, desc in TECHNIQUES:
            obj, created = Technique.objects.update_or_create(
                slug=slug,
                defaults=dict(
                    name=name, category=cat, magic_weight=mw,
                    deterministic_cost=cost, description=desc,
                ),
            )
            t_by_slug[slug] = obj
            self.stdout.write(
                f"  technique{'+' if created else '·'} {slug}  (mw {mw})")

        # Observations.  Wipe + re-create per (harness, technique) so
        # re-runs reflect the seed exactly without piling duplicates.
        n_obs = 0
        for h_slug, t_slug, src, conf, summary, evidence in OBSERVATIONS:
            h = h_by_slug.get(h_slug)
            t = t_by_slug.get(t_slug)
            if not h or not t:
                self.stdout.write(
                    f'  ! skipping observation {h_slug}/{t_slug} — missing')
                continue
            Observation.objects.filter(harness=h, technique=t).delete()
            Observation.objects.create(
                harness=h, technique=t,
                source_kind=src, confidence=conf,
                summary=summary or f'{h.name} uses {t.name}.',
                evidence=evidence,
            )
            n_obs += 1
        self.stdout.write(f"  observations: {n_obs}")

        # Distillation proposals — upsert by technique.  Note the
        # PROPOSALS list contains rationale-bearing rows and a couple
        # of byte-budget-only stub rows; we merge on technique slug.
        seen = set()
        n_prop = 0
        for t_slug, dec, pri, budget, rat, impl in PROPOSALS:
            if t_slug in seen:
                # Stub follow-ups in the list — skip.
                continue
            seen.add(t_slug)
            t = t_by_slug.get(t_slug)
            if not t:
                continue
            DistillationProposal.objects.update_or_create(
                technique=t,
                defaults=dict(
                    decision=dec, priority=pri,
                    byte_budget=budget,
                    rationale=rat, implementation_notes=impl,
                ),
            )
            n_prop += 1
        self.stdout.write(f"  proposals: {n_prop}")

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(HARNESSES)} harnesses, {len(TECHNIQUES)} '
            f'techniques, {n_obs} observations, {n_prop} proposals.'))
