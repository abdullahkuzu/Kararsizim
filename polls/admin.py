from django.contrib import admin
from django.db.models import Count

from .models import Option, Poll, RateLimitHit, Report, Vote


class OptionInline(admin.TabularInline):
    model = Option
    extra = 0
    fields = ("position", "text", "vote_count")


class ReportInline(admin.TabularInline):
    model = Report
    extra = 0
    fields = ("user", "created_at")
    readonly_fields = ("user", "created_at")
    can_delete = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description="Seçili anketleri kapat")
def close_polls(modeladmin, request, queryset):
    updated = queryset.filter(status=Poll.Status.ACTIVE).update(status=Poll.Status.CLOSED)
    modeladmin.message_user(request, f"{updated} anket kapatıldı.")


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("question", "author", "status", "total_votes", "report_count", "created_at")
    list_filter = ("status",)
    search_fields = ("question", "public_id", "author__username")
    readonly_fields = ("public_id", "total_votes", "created_at")
    inlines = [OptionInline, ReportInline]
    actions = [close_polls]
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_report_count=Count("reports", distinct=True))

    @admin.display(description="Bildirim", ordering="_report_count")
    def report_count(self, obj):
        return obj._report_count


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("poll", "user", "created_at")
    list_select_related = ("poll", "user")
    raw_id_fields = ("poll", "user")
    readonly_fields = ("reporter_key", "created_at")
    date_hierarchy = "created_at"


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("poll", "option", "user", "created_at")
    list_select_related = ("poll", "option", "user")
    raw_id_fields = ("poll", "option", "user")


@admin.register(RateLimitHit)
class RateLimitHitAdmin(admin.ModelAdmin):
    list_display = ("scope", "created_at")
    list_filter = ("scope",)
    readonly_fields = ("scope", "ip_hash", "created_at")
