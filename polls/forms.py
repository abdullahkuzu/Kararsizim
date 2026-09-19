from django import forms
from django.core.exceptions import ValidationError

from .models import Poll
from .services import MAX_OPTIONS, MIN_OPTIONS

OPTION_MAX_LENGTH = 80


class PollForm(forms.ModelForm):
    """Seçenekler tek bir `option` alan adıyla, sırayla gelir (JS kapalıyken de çalışır)."""

    class Meta:
        model = Poll
        fields = ("question", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}
        labels = {"question": "Sorun ne?", "description": "Açıklama (isteğe bağlı)"}

    def __init__(self, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        self.raw_options = data.getlist("option") if data is not None else []
        self.options = [text.strip() for text in self.raw_options if text.strip()]
        self.fields["question"].widget.attrs.update({"maxlength": 140, "placeholder": "Bugün sinemaya mı gitsem, restorana mı?"})

    @property
    def option_rows(self):
        rows = list(self.raw_options[:MAX_OPTIONS])
        return rows + [""] * (MAX_OPTIONS - len(rows))

    def clean(self):
        cleaned = super().clean()
        options = self.options
        if len(options) < MIN_OPTIONS:
            raise ValidationError("En az 2 seçenek gerekli.")
        if len(options) > MAX_OPTIONS:
            raise ValidationError("En fazla 5 seçenek ekleyebilirsin.")
        if any(len(text) > OPTION_MAX_LENGTH for text in options):
            raise ValidationError("Her seçenek en fazla 80 karakter olabilir.")
        if len({text.casefold() for text in options}) != len(options):
            raise ValidationError("Aynı seçeneği iki kez yazamazsın.")
        return cleaned
