"""Thin wrappers around Biopython's SeqIO for the two formats Phase 1
ships: FASTA and GenBank.

Each parser returns a list of dicts (one per record in the input).
The dict shape matches what ``views.import_records`` will pass to
``SequenceRecord.objects.create`` and ``AnnotationFeature.objects.create``.

Why dicts and not Django objects: parsers stay pure and unit-testable
without the DB; the import view is the single place that owns
persistence + transactional rollback.
"""

from io import StringIO

from Bio import SeqIO


# Heuristic: if the sequence has any U (uracil) and no T, call it RNA.
def _detect_seq_type(seq, declared_molecule_type=''):
    s = str(seq).upper()
    declared = (declared_molecule_type or '').upper()
    if 'RNA' in declared:
        return 'RNA'
    if 'DNA' in declared:
        return 'DNA'
    if 'PROTEIN' in declared or 'AA' in declared:
        return 'protein'
    # Heuristic from the bases.
    if 'U' in s and 'T' not in s:
        return 'RNA'
    bases = set(s) - {'-', 'N'}
    nucleo = set('ACGTU')
    if bases.issubset(nucleo):
        return 'RNA' if 'U' in bases else 'DNA'
    return 'protein'


def _qualifiers_to_jsonable(qualifiers):
    """Biopython feature.qualifiers values are lists of strings; copy
    them into plain dict-of-lists-of-strings so they survive JSONField
    round-trips."""
    out = {}
    for k, v in qualifiers.items():
        if isinstance(v, (list, tuple)):
            out[k] = [str(x) for x in v]
        else:
            out[k] = str(v)
    return out


def parse_fasta(text, filename=''):
    """Parse FASTA text → list of record-dicts. FASTA carries no
    feature annotations, so each record's ``features`` list is empty."""
    records = []
    for rec in SeqIO.parse(StringIO(text), 'fasta'):
        seq_text = str(rec.seq)
        records.append({
            'title': (rec.description or rec.id).strip(),
            'accession': rec.id,
            'organism': '',
            'sequence_type': _detect_seq_type(seq_text),
            'sequence': seq_text,
            'source_format': 'fasta',
            'source_filename': filename,
            'description': rec.description,
            'metadata': {},
            'features': [],
        })
    return records


def parse_genbank(text, filename=''):
    """Parse GenBank text → list of record-dicts. Each record carries
    its features (gene / CDS / mRNA / regulatory / etc.) with
    coordinates and qualifiers."""
    records = []
    for rec in SeqIO.parse(StringIO(text), 'genbank'):
        ann = rec.annotations or {}
        molecule_type = ann.get('molecule_type', '')

        features = []
        for feat in rec.features:
            # SimpleLocation carries .start / .end as ExactPosition;
            # int() works on those. Compound locations (joins) collapse
            # to their outermost extent for Phase 1 — reasonable for
            # the track view, lossy for splice-aware rendering. Phase 2.
            try:
                start = int(feat.location.start)
                end = int(feat.location.end)
                strand = feat.location.strand
            except Exception:
                continue
            features.append({
                'feature_type': feat.type,
                'start': start,
                'end': end,
                'strand': strand if strand in (-1, 0, 1) else 1,
                'qualifiers': _qualifiers_to_jsonable(feat.qualifiers),
            })

        records.append({
            'title': rec.description or rec.id,
            'accession': rec.id,
            'organism': ann.get('organism', ''),
            'sequence_type': _detect_seq_type(rec.seq, molecule_type),
            'sequence': str(rec.seq),
            'source_format': 'genbank',
            'source_filename': filename,
            'description': rec.description,
            'metadata': {
                'molecule_type': molecule_type,
                'date': ann.get('date', ''),
                'topology': ann.get('topology', ''),
                'taxonomy': ann.get('taxonomy', []),
                'keywords': ann.get('keywords', []),
            },
            'features': features,
        })
    return records


def parse_text(text, filename=''):
    """Sniff the format from the first non-blank line and dispatch."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('>'):
            return 'fasta', parse_fasta(text, filename)
        if stripped.startswith('LOCUS'):
            return 'genbank', parse_genbank(text, filename)
        break
    raise ValueError(
        'Could not detect format — first non-blank line is neither '
        '">..." (FASTA) nor "LOCUS..." (GenBank).'
    )
