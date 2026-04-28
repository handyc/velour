from django import forms

from .models import Document, Section, Style


class NewDocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title']


class SectionForm(forms.ModelForm):
    class Meta:
        model = Section
        fields = ['title', 'body', 'style', 'level',
                  'primary_language', 'paragraph_direction']
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 12,
                'class': 'quill-body',
                'spellcheck': 'true',
            }),
            'title': forms.TextInput(attrs={'class': 'quill-section-title'}),
        }

    def __init__(self, *args, document=None, **kwargs):
        super().__init__(*args, **kwargs)
        if document is not None:
            self.fields['style'].queryset = Style.objects.filter(document=document)
            # Section's primary_language picker — restrict to languages
            # enabled on this document.
            from .models import DocumentLanguage
            enabled_ids = DocumentLanguage.objects.filter(
                document=document).values_list('language_id', flat=True)
            self.fields['primary_language'].queryset = (
                self.fields['primary_language'].queryset.filter(id__in=enabled_ids)
            )
        elif self.instance.pk and self.instance.document_id:
            self.fields['style'].queryset = self.instance.document.styles.all()


class StyleForm(forms.ModelForm):
    class Meta:
        model = Style
        fields = ['name', 'kind', 'css_rules']
        widgets = {
            'css_rules': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': '{"font_family": "Charter", "font_size": "11pt"}',
                'style': 'font-family: ui-monospace, monospace;',
            }),
        }
