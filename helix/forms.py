from django import forms


class UploadForm(forms.Form):
    """Either pick a file or paste sequence text directly. The detail
    view's parse_text sniffs the format from the first non-blank line."""

    file = forms.FileField(
        required=False,
        help_text='FASTA (.fa, .fasta, .fna) or GenBank (.gb, .gbk, .genbank).',
    )
    pasted = forms.CharField(
        required=False, widget=forms.Textarea(attrs={
            'rows': 10, 'spellcheck': 'false',
            'style': 'font-family: ui-monospace, monospace; font-size: 0.8rem;',
            'placeholder': '>my_sequence\nACGTACGTACGT...\n   — or —   \nLOCUS ...',
        }),
    )
    title_override = forms.CharField(
        required=False, max_length=300,
        help_text='Optional — overrides the title from the first record. '
                  'Multi-record uploads keep the original titles.',
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('file') and not cleaned.get('pasted', '').strip():
            raise forms.ValidationError(
                'Provide either a file or pasted text.'
            )
        return cleaned


class FetchNCBIForm(forms.Form):
    """Pull one or more sequences from NCBI's Entrez efetch endpoint by
    accession. The view does the HTTP request synchronously per
    accession with a per-record timeout — fine for the small/medium
    accessions Helix is designed around (everything from a 2.7 kb
    plasmid up to a few-Mb chromosome). Genome-scale fetches should
    use ``manage.py fetch_helix_corpus`` instead."""

    FORMAT_CHOICES = [
        ('gbwithparts', 'GenBank (sequence + annotations) — preferred'),
        ('fasta',       'FASTA (sequence only) — faster, no features'),
    ]

    accessions = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4, 'spellcheck': 'false',
            'style': 'font-family: ui-monospace, monospace; font-size: 0.85rem;',
            'placeholder': 'NC_001416.1\nNC_045512.2\nL09137.2',
        }),
        help_text='One accession per line, or comma/space-separated. '
                  'Examples: NC_001416 (λ phage, 48 kb), NC_045512 '
                  '(SARS-CoV-2, 30 kb), L09137 (pUC19, 2.7 kb).',
    )
    format = forms.ChoiceField(
        choices=FORMAT_CHOICES, initial='gbwithparts',
        help_text='GenBank brings annotations along (CDS, gene, mRNA, '
                  'misc_feature, …). FASTA is just the bases.',
    )
    email = forms.EmailField(
        required=False,
        help_text='Optional — NCBI Entrez asks for a contact address. '
                  'Defaults to the project user if blank.',
    )

    def clean_accessions(self):
        text = (self.cleaned_data.get('accessions') or '').strip()
        if not text:
            raise forms.ValidationError('Provide at least one accession.')
        # Split on commas, semicolons, whitespace (incl. newlines).
        import re
        parts = [p.strip() for p in re.split(r'[,;\s]+', text) if p.strip()]
        # Sanity-check: NCBI accessions are alphanumerics + underscore +
        # an optional .version suffix. Reject obviously bogus tokens
        # before we hit the network.
        bad = [p for p in parts if not re.match(r'^[A-Za-z0-9_.]+$', p)]
        if bad:
            raise forms.ValidationError(
                f'Not a valid accession: {", ".join(bad[:3])}'
                + ('…' if len(bad) > 3 else '')
            )
        if len(parts) > 20:
            raise forms.ValidationError(
                'Cap is 20 accessions per request; for bigger batches '
                'use `manage.py fetch_helix_corpus --only A,B,C…`.'
            )
        return parts
