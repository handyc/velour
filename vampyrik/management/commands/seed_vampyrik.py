"""Seed vampyrik with a starter set of well-attested folk vampires.

Idempotent: re-running updates existing entries by slug without
duplicating.  The goal is a wide cultural sweep (Europe, MENA, Asia,
the Americas) rather than depth — depth is what the admin UI is for.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from vampyrik.models import (Creature, Origin, Source, Tradition,
                             Trait, Weakness)


TRAITS = [
    # name, kind, description
    ('drinks blood',                'behavioural',
     'Survives on the blood of the living.'),
    ('drains life-force',           'supernatural',
     'Takes essence, breath, or spirit rather than (or in addition to) blood.'),
    ('eats flesh',                  'behavioural',
     'Consumes corpses or the bodies of the living.'),
    ('preys on infants',            'behavioural',
     'Specifically targets newborns, pregnant women, or unborn children.'),
    ('preys on sleepers',           'behavioural',
     'Attacks the sleeping, often the dreamer specifically.'),
    ('shapeshifts',                 'supernatural',
     'Takes other forms — bat, wolf, mist, dog, beautiful woman, owl.'),
    ('flies',                       'supernatural',
     'Travels through the air, by wings, sheer will, or detached body parts.'),
    ('detaches head or organs',     'physical',
     'Separates head, viscera, or torso from the lower body to hunt.'),
    ('pale or bloodless',           'physical',
     'Skin is pale, waxen, or shows no blood when cut.'),
    ('bloated and ruddy',           'physical',
     'Corpse is engorged, dark red or purple, as if freshly fed.'),
    ('has long nails or fangs',     'physical',
     'Distinctive elongated nails, teeth, or tongue.'),
    ('returns from the grave',      'supernatural',
     'Walks again after death; the body is found undecayed.'),
    ('must be invited',             'supernatural',
     'Cannot cross a threshold unless someone living invites it in.'),
    ('cannot cross running water',  'supernatural',
     'Repelled by streams, rivers, or any running water.'),
    ('counts compulsively',         'behavioural',
     'Stops to count scattered grains, seeds, or knots before passing.'),
    ('casts no shadow / reflection','supernatural',
     'Does not appear in mirrors, water, or as a shadow.'),
    ('strigoi-mark birth',          'physical',
     'Born with a caul, a tail, an extra nipple, or red hair.'),

    # Apotropaic (warding) traits — folk practices that keep them off
    ('garlic',                      'apotropaic',
     'Bulbs hung at windows or stuffed into the mouth of the corpse.'),
    ('salt threshold',              'apotropaic',
     'Salt scattered across thresholds, graves, or onto the corpse.'),
    ('iron nails or scissors',      'apotropaic',
     'Iron objects laid on or in the coffin; scissors opened across the chest.'),
    ('mirror or icon',              'apotropaic',
     'Mirror or holy image placed facing the corpse.'),
    ('seeds at the grave',          'apotropaic',
     'Poppy or millet scattered; the revenant must count them all.'),
]


ORIGINS = [
    ('bitten by a vampire',
     'The classic transmission: a victim drained but not finished returns.'),
    ('born with a caul',
     'A baby born with the amniotic veil still over the face is fated to '
     'walk after death.'),
    ('died unbaptised',
     'Souls of children who died unchristened, or adults unshriven, are '
     'said to rise.'),
    ('died excommunicated or cursed',
     'Church curse or sorcerer\'s curse, broken oath, or dying in mortal sin.'),
    ('died by violence',
     'Murder, suicide, drowning, or any sudden uncomposed death.'),
    ('seventh son of a seventh son',
     'A folk lineage of fatedness — the seventh in the line is born to it.'),
    ('cat or dog jumped over corpse',
     'An unguarded corpse becomes a revenant if an animal (most often a '
     'black cat) leaps over it.'),
    ('cursed by witchcraft',
     'Made by a sorcerer, often for vengeance.'),
    ('born of incest',
     'The bastard of forbidden union becomes the creature.'),
    ('willingly became one',
     'A living person who studies the rite and chooses the path.'),
]


WEAKNESSES = [
    # name, destroys, description
    ('sunlight',                True,
     'Direct sun reduces the creature to ash or undoes it utterly. '
     'Strongly associated with the modern literary vampire; in folk '
     'sources sunlight is often only weakening, not lethal.'),
    ('decapitation',            True,
     'Head severed and placed between the legs, or buried elsewhere.'),
    ('stake through the heart', True,
     'Wood (hawthorn, aspen, ash, oak, juniper depending on region) '
     'driven through the chest, pinning the corpse to the grave.'),
    ('cremation',               True,
     'Burning the body to ash is the final and most thorough method.'),
    ('iron through the mouth',  True,
     'A rod or nail driven through the open mouth into the earth beneath.'),
    ('mouth filled with brick or stone', True,
     'Stops the corpse from chewing on its shroud and on the living '
     '(attested in Venetian plague graves, c. 16th c.).'),
    ('running water',           False,
     'Forces a halt or detour; rarely lethal.'),
    ('crucifix or holy symbol', False,
     'Repels by religious authority; Christian and Hindu sources both attest.'),
    ('holy water',              False,
     'Burns the skin like acid; may scatter a revenant.'),
    ('garlic',                  False,
     'Repels by scent; sometimes used to stuff the mouth of a freshly '
     'exhumed corpse.'),
    ('mustard seeds scattered', False,
     'The creature is compelled to gather them all before dawn — sunrise '
     'then catches it.'),
    ('return to grave at dawn', False,
     'Many traditions require the creature to lie in its native earth '
     'each day, making the grave the kill-point.'),
    ('salt scattered on shroud', False,
     'Disrupts the corpse\'s ability to rise; folk apotropaic.'),
]


SOURCES = [
    ('De Masticatione Mortuorum',
     'Michael Ranft',
     '1728',
     'Early scholarly treatment of corpses chewing their shrouds in '
     'Central European plague graves.'),
    ('Dissertation sur les apparitions des esprits',
     'Augustin Calmet',
     '1751',
     'Benedictine compilation of revenant reports from Eastern Europe; '
     'Voltaire ridiculed it, and it became a primary modern source.'),
    ('Dracula',
     'Bram Stoker',
     '1897',
     'Crystallised the modern literary vampire from Eastern European '
     'folklore; many "classic" rules (sunlight death, casts no reflection) '
     'are partly Stoker\'s invention or amplification.'),
    ('Carmilla',
     'Sheridan Le Fanu',
     '1872',
     'Earlier than Dracula; established the seductive female vampire.'),
    ('Vampires, Burial, and Death',
     'Paul Barber',
     '1988',
     'A folklorist–pathologist reading of revenant tales as forensic '
     'misreading of decomposition.'),
    ('The Vampire in Lore and Legend',
     'Montague Summers',
     '1928',
     'Wide if uncritical compendium; useful for breadth of attestation.'),
    ('Various oral traditions, 19th–20th c.',
     '', '', 'Field-collected accounts; specific reciter and locality '
     'usually attached to individual creatures.'),
]


TRADITIONS = [
    {
        'name': 'Romanian',
        'region': 'Romania (Wallachia, Moldavia, Transylvania)',
        'era': 'medieval–modern',
        'summary': 'The strigoi tradition is the densest single body of '
                   'European vampire lore.  The Romanian Orthodox grave-rite '
                   'and the figure of the revenant strigoi (living or dead) '
                   'survived continuously into the 20th century.',
    },
    {
        'name': 'South Slavic',
        'region': 'Serbia, Bulgaria, Bosnia, North Macedonia',
        'era': '17th c. onward (heavily documented)',
        'summary': 'The Serbian "vampir" cases of 1725–1732 (Petar Blagojević '
                   'and Arnold Paole) brought the word into Western European '
                   'writing.  Bulgarian "ustrel" and "krvopijac" are local '
                   'variants.',
    },
    {
        'name': 'Polish & East Slavic',
        'region': 'Poland, Ukraine, Belarus, Russia',
        'era': 'medieval–modern',
        'summary': 'The upiór / upyr / upir lineage — exhumations recorded '
                   'in Polish-Lithuanian villages well into the 19th c.',
    },
    {
        'name': 'Greek',
        'region': 'Greece, Cyprus, the Aegean',
        'era': 'Byzantine–modern',
        'summary': 'The vrykolakas and the older lamia tradition are '
                   'distinct: vrykolakas is the corpse-returner, lamia '
                   'an ancient demoness of childbirth and seduction.',
    },
    {
        'name': 'Filipino',
        'region': 'the Philippines (Tagalog and Visayan regions)',
        'era': 'pre-colonial–modern',
        'summary': 'The aswang complex is exceptionally rich: shape-shifters, '
                   'self-segmenting manananggal, and ghoul-like tiyanak '
                   'collapse "vampire", "witch", and "ghoul" categories.',
    },
    {
        'name': 'Malay',
        'region': 'Malaysia, Indonesia',
        'era': 'pre-colonial–modern',
        'summary': 'The penanggalan is one of the most distinctive vampire '
                   'figures in the world — a flying severed head trailing '
                   'its viscera, which preys on women in childbirth.',
    },
    {
        'name': 'Chinese',
        'region': 'China, Taiwan, southeast Asian diaspora',
        'era': 'Qing-era literary tradition onward',
        'summary': 'The jiangshi is closer to a reanimated corpse than a '
                   'European vampire — driven by qi rather than blood, '
                   'hopping rather than walking, controlled by Taoist priests.',
    },
    {
        'name': 'Caribbean',
        'region': 'Trinidad, Dominica, Haiti',
        'era': 'colonial–modern',
        'summary': 'The soucouyant is a witch-vampire who sheds her skin '
                   'and flies as a fireball at night.',
    },
    {
        'name': 'West African (Ewe)',
        'region': 'Ghana, Togo',
        'era': 'traditional–modern',
        'summary': 'The adze is a firefly-formed witch-spirit that drinks '
                   'blood, with vampire and witchcraft attributes braided.',
    },
    {
        'name': 'Mesopotamian',
        'region': 'ancient Sumer, Akkad, Babylon',
        'era': 'c. 3rd millennium BCE–Hellenistic',
        'summary': 'Ekimmu and Lilitu — restless spirits of the un-buried '
                   'and demoness of the night — are among the oldest '
                   'attested vampire-adjacent figures.',
    },
    {
        'name': 'Hebrew & post-biblical',
        'region': 'Levant, Mediterranean diaspora',
        'era': 'ancient–medieval',
        'summary': 'Lilith and the estries of Talmudic and medieval Hebrew '
                   'sources blood-drinking female spirits of the night.',
    },
    {
        'name': 'Hindu',
        'region': 'South Asia',
        'era': 'ancient–modern',
        'summary': 'The vetala, pishacha, and rakshasa overlap with vampire '
                   'lore at the edges — corpse-possessing spirits, ghouls, '
                   'and shapeshifting flesh-eaters.',
    },
    {
        'name': 'Mexican (folk)',
        'region': 'Mexico',
        'era': 'pre-Columbian–modern',
        'summary': 'The tlahuelpuchi is a witch-vampire of the Tlaxcala '
                   'highlands who specifically targets infants.',
    },
    {
        'name': 'New England',
        'region': 'Rhode Island, Vermont, Connecticut',
        'era': '18th–19th c. tuberculosis epidemics',
        'summary': 'A consumption-driven panic: the "Jewett City vampires" '
                   'and Mercy Brown case (1892) saw corpses exhumed and '
                   'organs burned to halt wasting disease in surviving kin.',
    },
]


CREATURES = [
    {
        'tradition': 'Romanian',
        'name': 'strigoi mort',
        'alt_names': 'strigoii morți (pl.)',
        'summary': 'The dead strigoi: the corpse of someone improperly '
                   'buried, returned to drain their kin.  The classic '
                   'object of the Romanian disinterment ritual.',
        'appearance': 'Corpse found undecayed, flush, blood at the mouth, '
                      'limbs supple.  Sometimes ruddy hair grown long.',
        'behaviour': 'Visits living relatives by night, draining vitality; '
                     'occasionally feeds on the heart specifically.',
        'traits': ['drinks blood', 'returns from the grave', 'pale or bloodless',
                   'bloated and ruddy', 'preys on sleepers',
                   'strigoi-mark birth'],
        'origins': ['born with a caul', 'died unbaptised', 'died by violence',
                    'cat or dog jumped over corpse'],
        'weaknesses': ['stake through the heart', 'decapitation',
                       'cremation', 'iron through the mouth',
                       'garlic', 'mustard seeds scattered'],
        'sources': ['The Vampire in Lore and Legend'],
    },
    {
        'tradition': 'Romanian',
        'name': 'strigoi viu',
        'alt_names': 'strigoii vii (pl.); living strigoi',
        'summary': 'The living strigoi: a witch-like person, born to it, '
                   'whose soul leaves the body at night to feed.  After '
                   'their death they typically become a strigoi mort.',
        'appearance': 'Outwardly normal; a strigoi-mark such as red hair, '
                      'a caul, or being born on a particular feast-day.',
        'behaviour': 'Sleeps deeply at home while the soul wanders.  May '
                     'be a recognisable neighbour in waking life.',
        'traits': ['drains life-force', 'shapeshifts', 'flies',
                   'preys on sleepers', 'strigoi-mark birth'],
        'origins': ['born with a caul', 'seventh son of a seventh son',
                    'born of incest'],
        'weaknesses': ['return to grave at dawn', 'crucifix or holy symbol'],
        'sources': ['The Vampire in Lore and Legend'],
    },
    {
        'tradition': 'Romanian',
        'name': 'moroi',
        'alt_names': 'muroi, moroaică',
        'summary': 'A lesser revenant or a living witch with vampiric '
                   'properties, often associated with cattle-sickness and '
                   'spoilt milk as much as with blood-drinking.',
        'behaviour': 'Steals the strength of livestock and the milk of '
                     'cows; sometimes harms children indirectly.',
        'traits': ['drains life-force', 'preys on infants'],
        'origins': ['died unbaptised', 'born with a caul'],
        'weaknesses': ['garlic', 'mirror or icon'],
    },
    {
        'tradition': 'South Slavic',
        'name': 'vampir',
        'alt_names': 'vampyr, vapir',
        'summary': 'The Serbian revenant of the 1725–32 cases that gave '
                   'the word "vampire" to Western European writing.',
        'appearance': 'Bloated, ruddy corpse with fresh blood at lips and '
                      'nose; nails and hair appearing to have grown.',
        'behaviour': 'Visits sleeping kin, sits on the chest, drains.',
        'traits': ['drinks blood', 'returns from the grave',
                   'bloated and ruddy', 'preys on sleepers'],
        'origins': ['died by violence', 'bitten by a vampire'],
        'weaknesses': ['stake through the heart', 'cremation', 'decapitation'],
        'sources': ['Dissertation sur les apparitions des esprits',
                    'Vampires, Burial, and Death'],
    },
    {
        'tradition': 'Polish & East Slavic',
        'name': 'upiór',
        'alt_names': 'upir, upyr',
        'summary': 'The Slavic revenant.  Polish exhumations sometimes '
                   'placed a sickle around the neck or a stone in the '
                   'mouth to prevent rising.',
        'appearance': 'Corpse engorged; sometimes attested with a '
                      'forked tongue or two hearts.',
        'traits': ['drinks blood', 'returns from the grave',
                   'has long nails or fangs', 'counts compulsively'],
        'origins': ['died excommunicated or cursed', 'died by violence'],
        'weaknesses': ['decapitation', 'cremation',
                       'mouth filled with brick or stone',
                       'seeds at the grave'],
        'sources': ['Vampires, Burial, and Death'],
    },
    {
        'tradition': 'Greek',
        'name': 'vrykolakas',
        'alt_names': 'vurkolakas, vorvolakas',
        'summary': 'Greek revenant: a corpse refused decomposition by '
                   'excommunication, mortal sin, or improper burial.  '
                   'Often less interested in blood than in nuisance — '
                   'knocking on doors, calling names.  Whoever answers dies.',
        'appearance': 'Body in unnatural good condition, often dark and '
                      'puffy ("tympanios" — drum-tight).',
        'behaviour': 'Returns to its village, knocks once at each door; '
                     'answering it is fatal.',
        'traits': ['returns from the grave', 'bloated and ruddy',
                   'preys on sleepers'],
        'origins': ['died excommunicated or cursed', 'died unbaptised'],
        'weaknesses': ['decapitation', 'cremation',
                       'return to grave at dawn',
                       'crucifix or holy symbol'],
    },
    {
        'tradition': 'Greek',
        'name': 'lamia',
        'alt_names': 'lamiai (pl.); empusa (cognate)',
        'summary': 'Ancient demoness, in classical sources the bereaved '
                   'queen who hunts other women\'s children; in later '
                   'sources, a seductress who drains young men.',
        'traits': ['drinks blood', 'shapeshifts', 'preys on infants',
                   'preys on sleepers'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['sunlight', 'crucifix or holy symbol'],
    },
    {
        'tradition': 'Filipino',
        'name': 'manananggal',
        'alt_names': 'tik-tik (Cebuano variant)',
        'summary': 'A woman by day who at night detaches her torso from '
                   'her lower half, sprouts wings, and flies in search '
                   'of pregnant women.  Her elongated proboscis-tongue '
                   'pierces the womb to drink the fetus.',
        'appearance': 'Torso with bat-like wings and a long, thin tongue; '
                      'the lower half remains hidden where she left it.',
        'behaviour': 'Hunts at night; must rejoin her lower half before '
                     'dawn or die.',
        'traits': ['drinks blood', 'detaches head or organs',
                   'flies', 'shapeshifts', 'preys on infants'],
        'origins': ['cursed by witchcraft', 'willingly became one'],
        'weaknesses': ['sunlight', 'salt scattered on shroud',
                       'garlic'],
    },
    {
        'tradition': 'Filipino',
        'name': 'aswang',
        'alt_names': 'aswang (general); various regional forms',
        'summary': 'A category as much as a creature: blood-drinker, '
                   'ghoul, shapeshifter, witch.  Often a respectable '
                   'neighbour by day.',
        'traits': ['drinks blood', 'eats flesh', 'shapeshifts',
                   'preys on infants'],
        'origins': ['cursed by witchcraft', 'willingly became one'],
        'weaknesses': ['salt scattered on shroud', 'garlic',
                       'sunlight'],
    },
    {
        'tradition': 'Malay',
        'name': 'penanggalan',
        'alt_names': 'penanggal',
        'summary': 'At night her head detaches with its trailing viscera '
                   'and flies free, seeking the blood of women in '
                   'childbirth.  By day she sits down, returns the '
                   'organs to her body, and looks like any other woman.',
        'appearance': 'Head trailing glistening intestines, lungs and '
                      'stomach; emits a sweet smell of vinegar from '
                      'soaking the viscera before re-entry.',
        'traits': ['drinks blood', 'detaches head or organs',
                   'flies', 'preys on infants'],
        'origins': ['willingly became one', 'cursed by witchcraft'],
        'weaknesses': ['sunlight', 'iron nails or scissors',
                       'thorny vines (jeruju) over windows'],
    },
    {
        'tradition': 'Chinese',
        'name': 'jiangshi',
        'alt_names': '殭屍; geung-si (Cantonese)',
        'summary': 'A stiff hopping corpse animated by stagnant qi, '
                   'often returned to its native village.  Drains '
                   'qi rather than blood.  Famously hops because rigor '
                   'mortis stiffens the legs.',
        'appearance': 'Greenish-white skin, sometimes mouldy; arms '
                      'rigidly forward; long claw-like nails.',
        'traits': ['drains life-force', 'returns from the grave',
                   'pale or bloodless', 'has long nails or fangs',
                   'counts compulsively'],
        'origins': ['died by violence', 'cursed by witchcraft'],
        'weaknesses': ['Taoist talisman on forehead',
                       'mirror or icon', 'cremation', 'sunlight',
                       'seeds at the grave'],
    },
    {
        'tradition': 'Caribbean',
        'name': 'soucouyant',
        'alt_names': 'soucoyant, ole-higue',
        'summary': 'An old woman by day; at night she sheds her skin, '
                   'flies as a fireball, and slips through keyholes to '
                   'suck the blood of sleepers.  If her skin is salted '
                   'while she\'s out she cannot return to it.',
        'traits': ['drinks blood', 'flies', 'shapeshifts',
                   'preys on sleepers', 'counts compulsively'],
        'origins': ['willingly became one', 'cursed by witchcraft'],
        'weaknesses': ['salt scattered on shroud', 'sunlight',
                       'mustard seeds scattered'],
    },
    {
        'tradition': 'West African (Ewe)',
        'name': 'adze',
        'alt_names': 'adze (Ewe)',
        'summary': 'Witch-spirit in the form of a firefly that slips '
                   'through closed doors to drink the blood of children.  '
                   'Captured, it turns into a human.',
        'traits': ['drinks blood', 'flies', 'shapeshifts',
                   'preys on infants'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['iron nails or scissors'],
    },
    {
        'tradition': 'Mesopotamian',
        'name': 'ekimmu',
        'alt_names': 'edimmu',
        'summary': 'The spirit of someone improperly buried, condemned '
                   'to wander.  Latches onto the living, draining '
                   'strength.  Ancient antecedent of the European revenant.',
        'traits': ['drains life-force', 'returns from the grave',
                   'preys on sleepers'],
        'origins': ['died by violence', 'died unbaptised'],
        'weaknesses': ['return to grave at dawn'],
    },
    {
        'tradition': 'Hebrew & post-biblical',
        'name': 'estrie',
        'alt_names': 'estries (pl.)',
        'summary': 'Medieval Hebrew sources describe female blood-drinking '
                   'demons or witches who require their hair to be loose '
                   'to take flight, and who can be bound by stuffing '
                   'their mouth with earth.',
        'traits': ['drinks blood', 'flies', 'shapeshifts',
                   'preys on infants'],
        'origins': ['cursed by witchcraft', 'willingly became one'],
        'weaknesses': ['mouth filled with brick or stone',
                       'crucifix or holy symbol'],
    },
    {
        'tradition': 'Hindu',
        'name': 'vetala',
        'alt_names': 'baital',
        'summary': 'A corpse-inhabiting spirit; subject of the classical '
                   'Vetalapanchavimshati riddle-stories.  Hangs upside '
                   'down from trees in cremation grounds.',
        'traits': ['returns from the grave', 'shapeshifts',
                   'casts no shadow / reflection'],
        'origins': ['died by violence'],
        'weaknesses': ['cremation', 'crucifix or holy symbol'],
    },
    {
        'tradition': 'Mexican (folk)',
        'name': 'tlahuelpuchi',
        'alt_names': 'tlahuelpuche',
        'summary': 'A witch-vampire of Tlaxcala folklore: typically a '
                   'woman, marked from birth, who at night detaches her '
                   'lower half and flies in animal form to drink the '
                   'blood of infants.',
        'traits': ['drinks blood', 'shapeshifts', 'flies',
                   'detaches head or organs', 'preys on infants',
                   'strigoi-mark birth'],
        'origins': ['born with a caul', 'cursed by witchcraft'],
        'weaknesses': ['garlic', 'iron nails or scissors',
                       'mirror or icon'],
    },
    {
        'tradition': 'New England',
        'name': 'consumption vampire',
        'alt_names': 'Mercy Brown case; Jewett City vampires',
        'summary': 'Late-stage tuberculosis (then called consumption) '
                   'killed family clusters; survivors blamed the '
                   'earlier-buried dead.  Corpses were exhumed; if '
                   'fresh-looking, the heart was burned and the ash '
                   'fed to ailing kin.  Mercy Brown of Exeter, R.I. '
                   '(d. 1892) is the best-documented case.',
        'appearance': 'A corpse fresher than expected after months '
                      'in a cold New England crypt — common, in fact, '
                      'because freezing slows decay.',
        'traits': ['drains life-force', 'returns from the grave',
                   'bloated and ruddy'],
        'origins': ['died by violence'],
        'weaknesses': ['cremation', 'iron through the mouth'],
        'sources': ['Vampires, Burial, and Death'],
    },
]


class Command(BaseCommand):
    help = 'Seed the vampyrik catalogue with a starter set of folk vampires.'

    @transaction.atomic
    def handle(self, *args, **opts):
        # Sources
        source_by_title = {}
        for title, author, year, details in SOURCES:
            src, _ = Source.objects.update_or_create(
                title=title,
                defaults={'author': author, 'year': year, 'details': details})
            source_by_title[title] = src

        # Tags
        trait_by_name = {}
        for name, kind, desc in TRAITS:
            t, _ = Trait.objects.update_or_create(
                name=name,
                defaults={'kind': kind, 'description': desc})
            trait_by_name[name] = t

        origin_by_name = {}
        for name, desc in ORIGINS:
            o, _ = Origin.objects.update_or_create(
                name=name, defaults={'description': desc})
            origin_by_name[name] = o

        weak_by_name = {}
        for name, destroys, desc in WEAKNESSES:
            w, _ = Weakness.objects.update_or_create(
                name=name,
                defaults={'destroys': destroys, 'description': desc})
            weak_by_name[name] = w

        # Traditions
        trad_by_name = {}
        for spec in TRADITIONS:
            t, _ = Tradition.objects.update_or_create(
                name=spec['name'],
                defaults={'region':  spec.get('region', ''),
                          'era':     spec.get('era', ''),
                          'summary': spec.get('summary', '')})
            trad_by_name[spec['name']] = t

        # Creatures
        for spec in CREATURES:
            trad = trad_by_name[spec['tradition']]
            c, _ = Creature.objects.update_or_create(
                tradition=trad,
                name=spec['name'],
                defaults={
                    'alt_names':  spec.get('alt_names', ''),
                    'summary':    spec.get('summary', ''),
                    'appearance': spec.get('appearance', ''),
                    'behaviour':  spec.get('behaviour', ''),
                    'notes':      spec.get('notes', ''),
                })
            # Tags: tolerate unseeded names (silently create a stub) so
            # adding a new tag in a single creature spec doesn't require
            # also amending the TRAITS list.
            def resolve_traits(names):
                out = []
                for n in names:
                    if n in trait_by_name:
                        out.append(trait_by_name[n]); continue
                    t, _ = Trait.objects.get_or_create(name=n,
                        defaults={'kind': 'physical'})
                    trait_by_name[n] = t
                    out.append(t)
                return out
            def resolve_origins(names):
                out = []
                for n in names:
                    if n in origin_by_name:
                        out.append(origin_by_name[n]); continue
                    o, _ = Origin.objects.get_or_create(name=n)
                    origin_by_name[n] = o
                    out.append(o)
                return out
            def resolve_weaknesses(names):
                out = []
                for n in names:
                    if n in weak_by_name:
                        out.append(weak_by_name[n]); continue
                    w, _ = Weakness.objects.get_or_create(
                        name=n, defaults={'destroys': False})
                    weak_by_name[n] = w
                    out.append(w)
                return out

            c.traits.set(resolve_traits(spec.get('traits', [])))
            c.origins.set(resolve_origins(spec.get('origins', [])))
            c.weaknesses.set(resolve_weaknesses(spec.get('weaknesses', [])))
            c.sources.set([source_by_title[s] for s in spec.get('sources', [])
                           if s in source_by_title])

        self.stdout.write(self.style.SUCCESS(
            f'vampyrik seeded: {Tradition.objects.count()} traditions, '
            f'{Creature.objects.count()} creatures, '
            f'{Trait.objects.count()} traits, '
            f'{Origin.objects.count()} origins, '
            f'{Weakness.objects.count()} weaknesses.'))
