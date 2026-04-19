"""Seed Marco the waiter (canonical) + a starter Town with one hex.

Idempotent. Safe to re-run; updates Marco's record in place.
"""

from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand

from agents.factory import random_aether_world
from agents.models import Agent, Town, TownCell, default_bio


class Command(BaseCommand):
    help = "Seed Marco the waiter + a starter town."

    def handle(self, *args, **opts):
        town, town_created = Town.objects.update_or_create(
            slug='velour-town',
            defaults={
                'name':         'Velour',
                'description':  ('The shared town that hosts Velour Cafe and '
                                 'its sister scenes. A small place; everyone '
                                 'knows everyone.'),
                'founded_year': 1924,
                'population_target': 200_000,
            },
        )

        # Centre cell of the hex grid is the Cafe scene if Aether has it.
        from aether.models import World
        cafe = World.objects.filter(slug__icontains='cafe').first()
        cell, _ = TownCell.objects.update_or_create(
            town=town, q=0, r=0,
            defaults={
                'label': 'piazza',
                'world': cafe,
            },
        )

        # Six neighbours, no worlds attached yet — just reserved cells.
        for dq, dr in TownCell.HEX_NEIGHBOURS:
            TownCell.objects.update_or_create(
                town=town, q=dq, r=dr,
                defaults={'label': f'block ({dq},{dr})'},
            )

        bio = default_bio()
        bio['occupation']  = 'waiter'
        bio['backstory']   = (
            'Marco has worked at the Velour Cafe since he was nineteen. '
            'He grew up two streets over, behind the church, and he can name '
            'every regular by their preferred coffee. People say he is the '
            'memory of the piazza. He hums opera under his breath when he '
            'thinks no one is listening.'
        )
        bio['personality'] = ['patient', 'observant', 'talkative', 'loyal']
        bio['favorites']   = {
            'aether_world':  cafe.slug if cafe else '',
            'language':      'it',
            'tileset':       'kawaii-pastel',
        }
        bio['appearance']  = {
            'hair':           'black, greying at the temples',
            'eye_color':      'brown',
            'skin_tone':      'olive',
            'clothing_style': 'black waistcoat, white shirt, black bow tie',
        }
        bio['voice']       = {'pitch': 0.95, 'rate': 0.95,
                              'voice_name': 'it-IT-DiegoNeural'}

        marco_origin = cafe or random_aether_world()

        marco, marco_created = Agent.objects.update_or_create(
            slug='marco-andolini',
            defaults={
                'name':         'Marco',
                'family_name':  'Andolini',
                'gender':       'm',
                'birthdate':    datetime.date(1971, 3, 14),
                'town':         town,
                'origin_world': marco_origin,
                'current_cell': cell,
                'face_seed':    481977,
                'bio_json':     bio,
            },
        )
        marco.full_clean()  # enforce byte budget

        self.stdout.write(self.style.SUCCESS(
            f"town: {'created' if town_created else 'updated'} {town.slug}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"marco: {'created' if marco_created else 'updated'} "
            f"({marco.bio_size_bytes()} B bio, "
            f"~{marco.estimated_row_bytes()} B row)"
        ))
