from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render

from .forms import RegisterForm


def register(request):
    if request.user.is_authenticated:
        return redirect("polls:index")

    form = RegisterForm(request.POST) if request.method == "POST" else RegisterForm()
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            form.add_error(None, "Bu kullanıcı adı veya e-posta az önce başkası tarafından alındı. Farklı bir tane dene.")
        else:
            login(request, user)
            messages.success(request, f"Hoş geldin, @{user.username}")
            return redirect("polls:index")
    return render(request, "accounts/register.html", {"form": form})


class SiteLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
