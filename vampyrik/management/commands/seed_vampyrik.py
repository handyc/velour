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

    # Newer traits for expanded creatures
    ('haunts grave-mounds',         'behavioural',
     'Lives in or near its own burial mound; the Norse draugr is the '
     'classical case.'),
    ('superhuman strength',         'supernatural',
     'Lifts boulders, crushes bone, swells to enormous size.'),
    ('chews its own shroud',        'behavioural',
     'The Central European nachzehrer eats its grave-clothes (then its '
     'own body, then drains kin at a distance).  Sound the 18th c. '
     'rationalists used to "prove" the corpse was still alive.'),
    ('rides a victim like a horse', 'behavioural',
     'The Akan asanbosam and various witch-vampires straddle and '
     'exhaust the sleeper rather than draining blood directly.'),
    ('iron hooks for feet',         'physical',
     'The asanbosam hangs from trees by hooked iron feet and drops on '
     'passing prey.'),
    ('hops or jumps',               'behavioural',
     'Cannot walk normally; rigor or anatomy forces hopping.  Jiangshi '
     'is the canonical case; nachzehrer also.'),
    ('eats children',               'behavioural',
     'Specifically devours small children rather than draining blood.'),
    ('drinks from the toes',        'physical',
     'The Albanian shtriga sucks blood from the great toe of a sleeper '
     'rather than the neck.'),
    ('breathes through the navel',  'physical',
     'The pricolici and a few other revenants are said to be recognised '
     'by an unblinking, navel-sourced breath that crosses thresholds.'),
    ('sweet smell',                 'physical',
     'A distinctive perfume (often vinegar, jasmine, or rot-sweet) '
     'announces the creature’s approach.'),
    ('hairy palms / strange eyes',  'physical',
     'Folk markers of the secret vampire: hair on the inside of the '
     'palm, eyes that don’t close in sleep, a tail at the base of '
     'the spine.'),

    # New apotropaics
    ('bury face-down',              'apotropaic',
     'Inverted burial — face into the soil so the revenant chews itself '
     'free into nothing.'),
    ('rice or sand to count',       'apotropaic',
     'Same compulsion as poppy-seeds, scaled up; tropical and East '
     'Asian variant.'),
    ('thorny vines at windows',     'apotropaic',
     'The Malay jeruju vine, Sri Lankan nelli, and others; the trailing '
     'organs catch and the creature is fixed in place until dawn.'),
    ('shedding skin marker',        'physical',
     'Soucouyant, asema, leyak — the daytime shape is recognised by an '
     'imperfectly-reattached skin (slightly puffy, sweet-smelling, or '
     'reddened).'),
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
    ('died in childbirth',
     'Mother and infant lost together; the Aztec civateteo and many '
     'Mediterranean spirits arise this way.'),
    ('greedy in life',
     'In Norse and West African sources a person who hoarded wealth in '
     'life rises to guard the grave.'),
    ('died of plague',
     'Mass death plus shallow burial — the European 1700s revenant '
     'panic is essentially plague-driven misreading of decomposition.'),
    ('sired by a vampire',
     'A child fathered by a revenant (a dhampir in Balkan lore) is '
     'born half-vampire and may grow into one.'),
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
    {
        'name': 'Norse',
        'region': 'Iceland, Norway, the medieval Norse cultural sphere',
        'era': 'Viking Age and later, c. 9th–13th c.',
        'summary': 'The draugr / aptrgangr — "again-walker" — is a corpse '
                   'that resists rest, growing in strength and size with '
                   'grievance.  Less interested in blood than in violence: '
                   'it guards its grave-goods, crushes intruders, and '
                   'walks among the living to wreck what it once owned.',
    },
    {
        'name': 'Germanic & Alpine',
        'region': 'Germany, Austria, Silesia, parts of Switzerland',
        'era': '17th–18th c. plague-era',
        'summary': 'The nachzehrer (corpse who chews its own shroud and '
                   'drains kin at a distance) and the neuntöter (the '
                   '"nine-killer", a revenant that takes nine days to '
                   'incubate in the grave and then kills nine kin in nine '
                   'days) sit at the heart of the German revenant tradition.',
    },
    {
        'name': 'Albanian',
        'region': 'Albania, Kosovo, parts of Macedonia',
        'era': 'oral, attested 19th–20th c.',
        'summary': 'The shtriga is a witch who detaches her body or her '
                   'soul at night to drink blood from sleeping children — '
                   'specifically from the great toe.  Her child, the '
                   'dhampir, is the canonical vampire-hunter.',
    },
    {
        'name': 'Croatian & Istrian',
        'region': 'Croatia, Slovenia, parts of Bosnia',
        'era': 'medieval–modern',
        'summary': 'A dualistic tradition: the kudlak is the night-walking '
                   'revenant, but every village also has its kresnik — '
                   'a child born with a caul who fights kudlaks on '
                   'behalf of the living, often in the form of an animal.',
    },
    {
        'name': 'Czech & Slovak',
        'region': 'Bohemia, Moravia, Slovakia',
        'era': '17th–19th c. (heavily documented by Habsburg officials)',
        'summary': 'The nelapsi (a name that translates roughly as '
                   '"the unwearied one") is the local revenant, attested '
                   'in the 1755 Visum et Repertum that the Empress Maria '
                   'Theresa commissioned to investigate Moravian '
                   'exhumations.  Stops at thresholds; counts seeds.',
    },
    {
        'name': 'Portuguese & Galician',
        'region': 'Portugal, Galicia (Iberian north-west)',
        'era': 'medieval–modern',
        'summary': 'The bruxa or bruxsa is a witch-woman who transforms '
                   'into a bird (often a screech-owl) at night, slips '
                   'down a chimney, and drinks from the navel of '
                   'sleeping children.  Children with epileptic fits '
                   'were said to be bruxa-touched.',
    },
    {
        'name': 'Japanese',
        'region': 'Japan',
        'era': 'medieval Heian–Edo and modern yōkai compilations',
        'summary': 'Japan’s vampire-adjacent yōkai are several: nukekubi '
                   '(detachable-head); the kappa (river-dwelling '
                   'blood-and-organ thief); kasha (corpse-stealing '
                   'cat-demon); plus the gakidō hungry ghosts on the '
                   'edge of Buddhist cosmology.  Less unified than a '
                   'single creature category, more a tonal field.',
    },
    {
        'name': 'Akan (Ashanti)',
        'region': 'Ghana, Côte d’Ivoire',
        'era': 'traditional, recorded from 19th c.',
        'summary': 'The asanbosam is a forest vampire that perches in '
                   'trees on iron hooks where its feet should be, '
                   'dropping on travellers.  The obayifo is its '
                   'witch-vampire cousin: a respectable neighbour by '
                   'day, a glowing light by night, eater of children.',
    },
    {
        'name': 'Sri Lankan',
        'region': 'Sri Lanka',
        'era': 'pre-Buddhist substrate, surviving in modern folk practice',
        'summary': 'The riri yaka (the "blood demon") is one of the '
                   '18 sanni demons of folk illness — invoked, '
                   'placated, and exorcised through the elaborate '
                   'sanni yakuma masked rite.  Distinct from the '
                   'urban manifestation of vampires arriving with '
                   'colonial-era literature.',
    },
    {
        'name': 'Aztec & Nahua',
        'region': 'central Mexico',
        'era': 'pre-Columbian, surviving in syncretic folk Catholicism',
        'summary': 'The civateteo were the deified spirits of women '
                   'who died in childbirth, returning on certain '
                   'unlucky days to seize children and pregnant women.  '
                   'Cihuateotl (sing.) shrines marked crossroads where '
                   'food and copal were left to appease them.',
    },
    {
        'name': 'Mapuche & Chilean',
        'region': 'south-central Chile, parts of Argentine Patagonia',
        'era': 'pre-colonial, oral and in regional ufology',
        'summary': 'The peuchen is a flying serpent that paralyses prey '
                   'with its gaze and drains them of blood — '
                   'occasionally adapted in 20th c. Chilean folklore '
                   'into the "chupacabras" narrative, though the '
                   'peuchen substantially predates it.',
    },
    {
        'name': 'Australian (Aboriginal)',
        'region': 'New South Wales and surrounding territories',
        'era': 'oral, traditional',
        'summary': 'The yara-ma-yha-who is a small, red-skinned tree '
                   'creature with suckers on its fingertips and toes, '
                   'which drops on travellers napping in the shade '
                   'and drains them — but only enough to weaken, then '
                   'swallows the victim whole, vomits them up, and '
                   'leaves them shorter and redder than before.  '
                   'Repeated encounters turn the victim into one.',
    },
    {
        'name': 'Bulgarian (folk)',
        'region': 'Bulgaria',
        'era': '17th–19th c. revenant panics',
        'summary': 'A dense corpus distinct from the South-Slavic '
                   'vampir: ustrel (revenant who attacks livestock '
                   'first, humans later) and krvopijac ("blood-drinker") '
                   'are the most common variants.  A specialist '
                   'vampirdzhija could trap one in a bottle.',
    },
    {
        'name': 'Surinamese & Guyanese',
        'region': 'Suriname, Guyana, eastern Caribbean',
        'era': 'colonial–modern',
        'summary': 'The asema (Sranan Tongo) is a person who at night '
                   'sheds skin and travels as a glowing ball to drink '
                   'blood.  Closely related to the Caribbean '
                   'soucouyant, but distinct in its lineage from '
                   'Akan/Maroon traditions of West African origin.',
    },
    {
        'name': 'Balinese',
        'region': 'Bali, eastern Java',
        'era': 'living folk-religious tradition',
        'summary': 'The leyak is a witch who studies the black art of '
                   '"pengiwan", learning at night to detach her head '
                   'with viscera trailing.  Rangda — queen of the '
                   'leyaks — is enacted as the great mask-villain of '
                   'the Calon Arang dance-drama.',
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

    # Additions to existing traditions
    {
        'tradition': 'Romanian',
        'name': 'pricolici',
        'alt_names': 'pricoliciu',
        'summary': 'A werewolf–vampire crossover: the soul of an '
                   'unrighteous Romanian peasant returns as a black '
                   'wolf with red eyes, sometimes joined by a pack '
                   'of similar revenants.  Hunts livestock and lone '
                   'travellers; in some accounts drinks blood from '
                   'the throat as a wolf and then resumes human form '
                   'by daylight.',
        'traits': ['drinks blood', 'shapeshifts',
                   'returns from the grave',
                   'breathes through the navel'],
        'origins': ['died by violence', 'cursed by witchcraft'],
        'weaknesses': ['decapitation', 'cremation'],
    },
    {
        'tradition': 'Filipino',
        'name': 'tiyanak',
        'alt_names': 'patianak; impakto',
        'summary': 'A vampiric ghost-baby: the soul of an unbaptised '
                   'infant or stillbirth, taking the form of a '
                   'crying child by the roadside.  A traveller who '
                   'picks it up to comfort it discovers fangs and '
                   'is exsanguinated; some accounts add a long '
                   'serpentine tongue.',
        'appearance': 'A perfectly normal newborn until taken up; '
                      'then features sharpen — red eyes, long fangs, '
                      'a wrinkled grandfatherly face.',
        'traits': ['drinks blood', 'shapeshifts',
                   'preys on sleepers'],
        'origins': ['died unbaptised', 'died in childbirth'],
        'weaknesses': ['turn clothing inside-out',
                       'sunlight', 'crucifix or holy symbol'],
    },
    {
        'tradition': 'Hindu',
        'name': 'pishacha',
        'alt_names': 'piśāca',
        'summary': 'A flesh-eating spirit listed in the Atharvaveda '
                   'as the lowest order of demons.  Lurks at '
                   'cremation grounds, crossroads, and empty '
                   'houses.  Possesses the living to feed through '
                   'them; can be exorcised with mantras of Rudra.',
        'traits': ['eats flesh', 'shapeshifts',
                   'casts no shadow / reflection', 'preys on sleepers'],
        'origins': ['died by violence', 'died unbaptised',
                    'cursed by witchcraft'],
        'weaknesses': ['crucifix or holy symbol',
                       'cremation', 'sunlight'],
    },
    {
        'tradition': 'Hindu',
        'name': 'rakshasa (blood-drinking class)',
        'alt_names': 'rākṣasa; nairṛta',
        'summary': 'The blood-drinking subset of the great rakshasa '
                   'order — distinct from the warrior asuras.  A '
                   'shapeshifter who appears as a beautiful person '
                   'to deceive; eats human flesh and drinks blood '
                   'from corpses on the battlefield.  Most powerful '
                   'at twilight and during the new moon.',
        'traits': ['drinks blood', 'eats flesh',
                   'shapeshifts', 'superhuman strength'],
        'origins': ['cursed by witchcraft', 'willingly became one',
                    'born of incest'],
        'weaknesses': ['sunlight', 'crucifix or holy symbol',
                       'cremation'],
    },
    {
        'tradition': 'Hebrew & post-biblical',
        'name': 'Lilith',
        'alt_names': 'Lilītu; al-Karina',
        'summary': 'The night-demoness of Mesopotamian and post-biblical '
                   'Hebrew tradition: in the Alphabet of Ben Sira '
                   'she is Adam’s first wife who refused submission '
                   'and was banished, returning to take the children '
                   'of those who would not name her.  Targets newborns '
                   'specifically, especially in the first eight days.',
        'appearance': 'Long hair (loose; she cannot fly with it bound), '
                      'sometimes wings of an owl, sometimes serpentine '
                      'below the waist.',
        'traits': ['drinks blood', 'preys on infants',
                   'flies', 'shapeshifts'],
        'origins': ['cursed by witchcraft', 'willingly became one'],
        'weaknesses': ['amulet inscribed with the names of three angels',
                       'crucifix or holy symbol', 'sunlight'],
    },
    {
        'tradition': 'South Slavic',
        'name': 'dhampir',
        'alt_names': 'dhampyr; (Albanian dhampir, "fang-toothed")',
        'summary': 'The half-vampire son of a male revenant and a '
                   'living woman.  Looks human and lives among the '
                   'living, but can see invisible vampires — the '
                   'professional vampire-hunter of Albanian and '
                   'Roma communities, summoned for a fee and a '
                   'meal.  Often dies young.',
        'traits': ['drinks blood', 'casts no shadow / reflection',
                   'hairy palms / strange eyes'],
        'origins': ['sired by a vampire'],
        'weaknesses': ['return to grave at dawn'],
    },

    # New entries for new traditions
    {
        'tradition': 'Norse',
        'name': 'draugr',
        'alt_names': 'haugbúi (mound-dweller); aptrgangr (again-walker)',
        'summary': 'The corpse that refuses to lie still.  Found '
                   'in the Eyrbyggja saga and Grettis saga.  '
                   'Possesses a heavy, smoke-stained, blue-black '
                   'flesh that grows hard as horn; can grow to '
                   'giant size; crushes and gnaws.  Guards its '
                   'grave-goods jealously and may sit on the lintel '
                   'of its hall doing mischief through the dark months.',
        'appearance': 'Bloated, blue-black or hel-blár, swollen '
                      'beyond human size; eyes open and clouded.',
        'behaviour': 'Crushes intruders to its barrow; rides '
                     'rooftops; cuts down livestock; sends sendings '
                     '(detached projections of malice) at distant kin.',
        'traits': ['returns from the grave', 'superhuman strength',
                   'haunts grave-mounds', 'bloated and ruddy',
                   'casts no shadow / reflection'],
        'origins': ['greedy in life', 'died by violence',
                    'died excommunicated or cursed'],
        'weaknesses': ['decapitation', 'cremation',
                       'iron nails or scissors'],
    },
    {
        'tradition': 'Germanic & Alpine',
        'name': 'nachzehrer',
        'alt_names': 'aufhocker; doppelsauger',
        'summary': 'The corpse that "after-gnaws".  Famously chews '
                   'its own shroud, then its own limbs; the chewing '
                   'noise heard at the graveside was 18th c. proof '
                   'the corpse still lived.  Drains kin at a distance '
                   '— a wasting illness in the village traces back '
                   'to a chewing corpse.',
        'appearance': 'A corpse with a missing thumb or finger '
                      '(eaten); soaked, mottled shroud half-swallowed.',
        'traits': ['chews its own shroud', 'drains life-force',
                   'bloated and ruddy', 'returns from the grave'],
        'origins': ['died by violence', 'died of plague',
                    'born with a caul'],
        'weaknesses': ['mouth filled with brick or stone',
                       'decapitation', 'iron through the mouth'],
    },
    {
        'tradition': 'Germanic & Alpine',
        'name': 'neuntöter',
        'alt_names': 'Nine-killer',
        'summary': 'A specifically lethal variant of the nachzehrer: '
                   'spends nine days in the grave maturing, then '
                   'kills nine kin in nine days — usually starting '
                   'with the closest relation.  The neuntöter is '
                   'the typical diagnosis when an entire household '
                   'is cleared by sequential consumption deaths.',
        'traits': ['drains life-force', 'returns from the grave',
                   'preys on sleepers'],
        'origins': ['died of plague', 'died unbaptised',
                    'died excommunicated or cursed'],
        'weaknesses': ['stake through the heart', 'decapitation',
                       'cremation', 'mouth filled with brick or stone'],
        'sources': ['Vampires, Burial, and Death'],
    },
    {
        'tradition': 'Albanian',
        'name': 'shtriga',
        'alt_names': 'shtrige; štriga (Kosovo)',
        'summary': 'A witch-vampire who specifically targets '
                   'children, drinking blood from the great toe '
                   'while they sleep.  Recognised when the child '
                   'wakes pale and listless without bite-marks at '
                   'the neck.  By day she is an old woman in the '
                   'village; by night her soul leaves her body to '
                   'fly as a moth or bee.',
        'traits': ['drinks blood', 'shapeshifts', 'flies',
                   'preys on infants', 'drinks from the toes',
                   'hairy palms / strange eyes'],
        'origins': ['willingly became one',
                    'cursed by witchcraft'],
        'weaknesses': ['silver coin under the pillow',
                       'mustard seeds scattered',
                       'crucifix or holy symbol'],
    },
    {
        'tradition': 'Croatian & Istrian',
        'name': 'kudlak',
        'alt_names': 'kuzlak; vukodlak',
        'summary': 'The night-walking dead of Istria.  Rises from '
                   'a grave dug too shallow or with the body '
                   'improperly composed.  Attacks kin first, then '
                   'livestock, then strangers.  Each village '
                   'traditionally has its own kresnik (a person '
                   'born with a caul) who duels the kudlak in '
                   'animal form to keep it down.',
        'traits': ['drinks blood', 'returns from the grave',
                   'shapeshifts'],
        'origins': ['born with a caul', 'died by violence',
                    'died unbaptised'],
        'weaknesses': ['stake through the heart',
                       'decapitation', 'cremation'],
    },
    {
        'tradition': 'Czech & Slovak',
        'name': 'nelapsi',
        'alt_names': 'nelapsí',
        'summary': 'The Slovak revenant of the Visum et Repertum '
                   'reports.  Walks the village by night, opening '
                   'doors, calling family members by name — '
                   'whoever answers wastes.  Distinctively unable '
                   'to cross a threshold over which a sickle has '
                   'been laid.',
        'traits': ['drains life-force', 'returns from the grave',
                   'counts compulsively',
                   'must be invited'],
        'origins': ['died unbaptised', 'died by violence'],
        'weaknesses': ['iron nails or scissors',
                       'seeds at the grave',
                       'decapitation'],
        'sources': ['Dissertation sur les apparitions des esprits'],
    },
    {
        'tradition': 'Portuguese & Galician',
        'name': 'bruxa',
        'alt_names': 'bruxsa; coca',
        'summary': 'A witch-woman who at night becomes a screech '
                   'owl, slides down the chimney, and drinks from '
                   'the navel of sleeping infants.  Recognised on '
                   'the morning after by a bluish bruise the size '
                   'of a thumbprint at the child’s navel.',
        'traits': ['drinks blood', 'shapeshifts', 'flies',
                   'preys on infants'],
        'origins': ['willingly became one',
                    'cursed by witchcraft'],
        'weaknesses': ['salt threshold', 'iron nails or scissors',
                       'crucifix or holy symbol'],
    },
    {
        'tradition': 'Japanese',
        'name': 'nukekubi',
        'alt_names': '抜首; rokurokubi',
        'summary': 'A person who appears entirely normal by day; '
                   'at night the head detaches and floats free, '
                   'biting and drinking from sleepers.  The body '
                   'remains in bed.  If the body is moved while '
                   'the head is away — even rotated — the head '
                   'cannot reattach and dies at dawn.',
        'appearance': 'Floating head with bared teeth; a red ring '
                      'sometimes visible around the throat by day.',
        'traits': ['drinks blood', 'detaches head or organs',
                   'flies', 'preys on sleepers',
                   'hairy palms / strange eyes'],
        'origins': ['cursed by witchcraft', 'willingly became one'],
        'weaknesses': ['sunlight', 'iron nails or scissors',
                       'shedding skin marker'],
    },
    {
        'tradition': 'Japanese',
        'name': 'kasha',
        'alt_names': '火車 (fiery cart)',
        'summary': 'A cat-formed yōkai that descends in a storm '
                   'to steal corpses from funerals — particularly '
                   'those of the morally compromised — and devours '
                   'them on the way to hell.  Rural temples carved '
                   'guard-cats into ridge-tiles to ward against it.',
        'traits': ['eats flesh', 'shapeshifts',
                   'returns from the grave'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['salt threshold', 'iron nails or scissors',
                       'crucifix or holy symbol'],
    },
    {
        'tradition': 'Akan (Ashanti)',
        'name': 'asanbosam',
        'alt_names': 'sasabonsam',
        'summary': 'A forest spirit that hangs from tree-branches '
                   'by iron hooks where its feet should be, '
                   'dropping on travellers and biting through bone '
                   'with iron teeth.  Distinctively large and '
                   'long-armed; sometimes covered in matted hair.',
        'appearance': 'Tall, thin, hairy; iron hooks for feet; '
                      'iron teeth; bloodshot eyes.',
        'traits': ['drinks blood', 'iron hooks for feet',
                   'superhuman strength',
                   'has long nails or fangs'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['iron nails or scissors',
                       'crucifix or holy symbol'],
    },
    {
        'tradition': 'Akan (Ashanti)',
        'name': 'obayifo',
        'alt_names': 'obeah-witch',
        'summary': 'A witch-vampire who lives among the living by '
                   'day as a respectable neighbour and at night '
                   'emerges as a flying light to suck blood from '
                   'children and from cocoa pods (causing the '
                   'plantation’s slow decline).  An obayifo is '
                   'usually identified after death by the unusual '
                   'preservation of the corpse.',
        'traits': ['drinks blood', 'flies', 'shapeshifts',
                   'preys on infants',
                   'shedding skin marker'],
        'origins': ['cursed by witchcraft', 'willingly became one'],
        'weaknesses': ['sunlight', 'iron nails or scissors',
                       'salt threshold'],
    },
    {
        'tradition': 'Sri Lankan',
        'name': 'riri yaka',
        'alt_names': 'rīri yaka (the blood demon)',
        'summary': 'One of the eighteen sanni demons of folk Sri '
                   'Lankan medicine.  Held responsible for '
                   'haemorrhagic fevers, vomiting blood, and the '
                   'delirium of the dying.  Exorcised through the '
                   'sanni yakuma masked dance-ritual, in which the '
                   'demon is summoned, named, fed, and dismissed.',
        'traits': ['drinks blood', 'shapeshifts',
                   'preys on sleepers'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['thorny vines at windows',
                       'crucifix or holy symbol',
                       'mustard seeds scattered'],
    },
    {
        'tradition': 'Aztec & Nahua',
        'name': 'civateteo',
        'alt_names': 'cihuateteo (sing. cihuateotl)',
        'summary': 'The deified spirits of women who died in '
                   'childbirth — fallen warriors of the cosmic '
                   'second front.  On the five unlucky days of '
                   'each twenty-day veintena they descended from '
                   'the west to seize children left out at '
                   'dusk and drive men mad.  Marked crossroads '
                   'with their offering shrines.',
        'appearance': 'A pale woman with chalk-white face, '
                      'unkempt hair, and a bone-skirt; sometimes '
                      'walking on her knees.',
        'traits': ['preys on infants', 'preys on sleepers',
                   'flies', 'pale or bloodless'],
        'origins': ['died in childbirth'],
        'weaknesses': ['crucifix or holy symbol',
                       'sunlight'],
    },
    {
        'tradition': 'Mapuche & Chilean',
        'name': 'peuchen',
        'alt_names': 'piuchen; piwüchen',
        'summary': 'A flying serpent of the Mapuche tradition '
                   'whose stare paralyses prey before it drains '
                   'them of blood.  Can change form (toad, bird, '
                   'small dragon).  Frequently associated with '
                   'unaccounted livestock deaths — the cultural '
                   'antecedent of the 20th c. "chupacabras".',
        'traits': ['drinks blood', 'shapeshifts', 'flies',
                   'preys on sleepers'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['salt threshold', 'sunlight',
                       'mustard seeds scattered'],
    },
    {
        'tradition': 'Australian (Aboriginal)',
        'name': 'yara-ma-yha-who',
        'alt_names': 'yara-ma',
        'summary': 'A small red figure with no teeth but with '
                   'suction-cup fingertips and toes.  Hides in '
                   'the canopy of fig trees and drops on whoever '
                   'rests in the shade.  Drains some blood, '
                   'swallows the victim whole, regurgitates them '
                   'shorter and redder than before — and after '
                   'enough encounters the victim transforms into '
                   'one.',
        'appearance': 'A small humanoid, entirely red, with a big '
                      'head, a soft toothless mouth, and grasping '
                      'fingers and toes ending in suckers.',
        'traits': ['drinks blood', 'preys on sleepers',
                   'shapeshifts'],
        'origins': ['cursed by witchcraft'],
        'weaknesses': ['sunlight'],
    },
    {
        'tradition': 'Bulgarian (folk)',
        'name': 'ustrel',
        'alt_names': 'ustrelica',
        'summary': 'A newly-arisen revenant: spends nine days '
                   'beneath the grave gathering strength, then '
                   'emerges first on livestock (sheep, cattle) '
                   'before progressing to humans.  Recognisable '
                   'because the morning brings dead animals with '
                   'no obvious wound.',
        'traits': ['drinks blood', 'returns from the grave',
                   'preys on infants'],
        'origins': ['died unbaptised', 'died of plague'],
        'weaknesses': ['stake through the heart', 'cremation',
                       'iron through the mouth'],
    },
    {
        'tradition': 'Bulgarian (folk)',
        'name': 'krvopijac',
        'alt_names': 'krvopiec (Polish cognate)',
        'summary': 'The Bulgarian "blood-drinker": a corpse that '
                   'returns with one nostril missing.  Specialist '
                   'vampirdzhija (vampire-hunters) could see them '
                   'and trap one inside a glass bottle baited with '
                   'a piece of the creature’s favourite food, '
                   'sealing it with an icon and throwing the bottle '
                   'into a fire.',
        'traits': ['drinks blood', 'returns from the grave',
                   'sweet smell'],
        'origins': ['died excommunicated or cursed'],
        'weaknesses': ['cremation', 'crucifix or holy symbol',
                       'iron nails or scissors',
                       'seeds at the grave'],
    },
    {
        'tradition': 'Surinamese & Guyanese',
        'name': 'asema',
        'alt_names': 'azeman',
        'summary': 'A person who at night slips out of their skin '
                   '(folded carefully and hidden in a calabash), '
                   'becoming a glowing blue or red ball that '
                   'travels through keyholes to drink blood.  If '
                   'the skin is salted while she is out she cannot '
                   'return to it and is found writhing in fire at '
                   'dawn.',
        'traits': ['drinks blood', 'flies', 'shapeshifts',
                   'shedding skin marker',
                   'preys on sleepers'],
        'origins': ['willingly became one',
                    'cursed by witchcraft'],
        'weaknesses': ['salt threshold', 'salt scattered on shroud',
                       'rice or sand to count',
                       'sunlight'],
    },
    {
        'tradition': 'Balinese',
        'name': 'leyak',
        'alt_names': 'léak',
        'summary': 'A witch who at night detaches her head with '
                   'organs trailing and flies to feed.  Studies '
                   'the black art "pengiwan" under the queen-leyak '
                   'Rangda, whose mask plays the great villain of '
                   'the Calon Arang dance.  Particularly hostile '
                   'to women in labour.',
        'appearance': 'A flying head with lungs and intestines '
                      'streaming behind; long tongue and protruding '
                      'fangs.  By day, an old woman.',
        'traits': ['drinks blood', 'detaches head or organs',
                   'flies', 'preys on infants', 'shapeshifts'],
        'origins': ['willingly became one',
                    'cursed by witchcraft'],
        'weaknesses': ['sunlight', 'thorny vines at windows',
                       'iron nails or scissors',
                       'crucifix or holy symbol'],
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
