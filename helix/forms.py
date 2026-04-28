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
