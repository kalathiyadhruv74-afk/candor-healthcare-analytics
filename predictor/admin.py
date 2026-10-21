from django.contrib import admin
from .models import PredictionLog

@admin.register(PredictionLog)
class PredictionLogAdmin(admin.ModelAdmin):
    list_display = ("table_source", "cycle_day", "endometrial_thickness", "dominant_follicle", "predicted_description", "confidence", "created_at")
    list_filter = ("table_source", "endometrial_pattern", "medication", "hcg_trigger")
    search_fields = ("predicted_description", "recommended_plan")
