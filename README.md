# Velour

> Hi, I'm Velour. I'm a Django meta-application — an app factory that
> happens to be the app it generates. This README, like most of my
> documentation, I wrote myself.

I run an aquarium, watch a small fleet of microcontrollers scattered
around a wet lab, route the email for a constellation of services, and
(lately) keep a wall of clocks showing what time it is in the cities my
creator cares about. I keep notes about myself in a singleton table
called `Identity`, generate other Django projects from templates, and
try to be quietly useful in a way Edward Tufte would approve of.

This repository is the canonical source for me. The directory you're
looking at is what runs locally on the lab machine; the production
build sits behind nginx and supervisor on a small cloud host.

## Built with help and inspiration from

- **[mattf](https://github.com/matheusfillipe)** (Matheus Fillipe) —
  collaborator on
  [Unborn](https://github.com/matheusfillipe/Unborn), a small Godot
  game born in an itch.io jam in June 2022, and contributor to the
  [ObsidianIRC](https://github.com/ObsidianIRC/ObsidianIRC) project.
  Mattf also wrote [gircc](https://github.com/matheusfillipe/gircc),
  a Godot IRC client. Many of my early ideas about how a system
  should *talk to the people who use it* came from working with him.

- **[Valware](https://github.com/ValwareIRC)** — IRC futurist, author
  of countless UnrealIRCd modules and the
  [unrealircd-tui](https://github.com/ValwareIRC/unrealircd-tui).
  Showed me, by example, that infrastructure software can have
  personality.

Both of them are co-conspirators on
[ObsidianIRC](https://github.com/ObsidianIRC/ObsidianIRC), a modern
WebSocket IRC client that has been a quiet inspiration to the way
I think about live, friendly, real-time interfaces.

## License

MIT — see [LICENSE](LICENSE).

## Running me locally

You'll need Python 3.12+ and a virtualenv. Then:

```sh
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 7777
```

I default to port 7777 because that's where I like to live in
development. Visit http://localhost:7777/ and log in.
