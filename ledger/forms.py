from django import forms

from .models import Workbook


class NewWorkbookForm(forms.ModelForm):
    class Meta:
        model = Workbook
        fields = ['title']
