"""Forms for Agora Phase 2 — instructor-side resource attach + grade
entry + student-side enrollment confirmation."""

from django import forms
from django.contrib.contenttypes.models import ContentType

from .models import Enrollment, ResourceLink


# Content types most worth linking to, kept to a useful shortlist so
# the picker doesn't drown in internal Django tables. Expanded as new
# app integrations come online.
_LINKABLE_APP_MODELS = [
    ('studious', 'work'),
    ('studious', 'scholar'),
    ('studious', 'claim'),
    ('muka',     'sentence'),
    ('muka',     'language'),
    ('oneliner', 'oneliner'),
    ('reckoner', 'task'),
    ('aggregator', 'article'),
]


def _linkable_content_type_queryset():
    """Filter ContentType down to a curated set so the resource-add
    picker shows only things it makes sense to attach to a section.
    """
    q = ContentType.objects.none()
    for app_label, model in _LINKABLE_APP_MODELS:
        q = q.union(
            ContentType.objects.filter(app_label=app_label, model=model),
        )
    return ContentType.objects.filter(pk__in=q.values_list('pk', flat=True))


class ResourceLinkForm(forms.ModelForm):
    class Meta:
        model = ResourceLink
        fields = ['kind', 'title', 'content_type', 'object_id',
                  'external_url', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['content_type'].queryset = _linkable_content_type_queryset()
        self.fields['content_type'].required = False
        self.fields['object_id'].required = False
        self.fields['content_type'].help_text = (
            'Pick a Velour app/model to link this resource to. Leave '
            'blank if the resource lives only at an external URL.'
        )
        self.fields['external_url'].help_text = (
            'Optional. Used when the resource lives outside Velour '
            '(journal article, dataset, video).'
        )

    def clean(self):
        cleaned = super().clean()
        ct = cleaned.get('content_type')
        oid = cleaned.get('object_id')
        url = cleaned.get('external_url')

        # Either (both CT and object_id) or external_url — at least one.
        has_internal = bool(ct and oid)
        if not has_internal and not url:
            raise forms.ValidationError(
                'Provide either an internal target (content type + '
                'object id) or an external URL.'
            )
        # content_type without object_id is incomplete.
        if (ct and not oid) or (oid and not ct):
            raise forms.ValidationError(
                'Both content type and object id are required for an '
                'internal target.'
            )
        # Validate object_id actually exists if internal target set.
        if has_internal:
            model = ct.model_class()
            if model and not model.objects.filter(pk=oid).exists():
                raise forms.ValidationError(
                    f'No {model.__name__} with id={oid} exists.'
                )
        return cleaned


class GradeEntryForm(forms.Form):
    """Bulk grade entry — one row per enrollment in a section.

    The view assembles this form dynamically: one CharField per
    enrollment, named grade_<enrollment_id>, plus one ChoiceField
    status_<enrollment_id>.
    """

    def __init__(self, *args, enrollments=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._enrollments = list(enrollments or [])
        for e in self._enrollments:
            self.fields[f'grade_{e.pk}'] = forms.CharField(
                required=False, max_length=4, initial=e.grade,
                widget=forms.TextInput(attrs={'size': 4}),
            )
            self.fields[f'status_{e.pk}'] = forms.ChoiceField(
                choices=Enrollment.STATUS_CHOICES,
                initial=e.status,
            )

    def rows(self):
        """Yield (enrollment, grade_field, status_field) triples for
        the template to render."""
        for e in self._enrollments:
            yield (e, self[f'grade_{e.pk}'], self[f'status_{e.pk}'])

    def save(self):
        for e in self._enrollments:
            grade = self.cleaned_data.get(f'grade_{e.pk}') or ''
            status = self.cleaned_data.get(f'status_{e.pk}') or e.status
            if e.grade != grade or e.status != status:
                e.grade = grade
                e.status = status
                e.save(update_fields=['grade', 'status'])
