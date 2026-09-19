from django.contrib.auth.forms import BaseUserCreationForm
from django.core.exceptions import ValidationError

from .models import User

RESERVED_USERNAMES = {
    "admin", "root", "api", "static", "anket", "giris", "kayit", "cikis", "kullanici", "hakkinda",
}


class RegisterForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Kullanıcı adı"
        self.fields["username"].help_text = "3–20 karakter; harf, rakam ve alt çizgi."
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autocapitalize": "none"})
        self.fields["email"].label = "E-posta"
        self.fields["email"].required = True
        self.fields["email"].help_text = "Kimseye gösterilmez."
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["password1"].label = "Parola"
        self.fields["password1"].help_text = "En az 8 karakter. Çok yaygın veya sadece rakamdan oluşan parolalar kabul edilmez."
        self.fields["password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["password2"].label = "Parola (tekrar)"
        self.fields["password2"].help_text = ""
        self.fields["password2"].widget.attrs["autocomplete"] = "new-password"

    def clean_username(self):
        username = self.cleaned_data["username"]
        if username.lower() in RESERVED_USERNAMES:
            raise ValidationError("Bu kullanıcı adı kullanılamaz. Başka bir tane seç.")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Bu kullanıcı adı alınmış. Başka bir tane seç.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Bu e-posta ile zaten bir hesap var. Giriş yapmayı dene.")
        return email
