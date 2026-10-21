from django.db import models

class PredictionLog(models.Model):
    table_source = models.CharField(max_length=50, default="iui_history")
    cycle_day = models.FloatField(default=12.0)
    endometrial_thickness = models.FloatField(default=8.0)
    endometrial_pattern = models.CharField(max_length=50, default="Regular")
    left_max_follicle = models.FloatField(default=0.0)
    right_max_follicle = models.FloatField(default=0.0)
    dominant_follicle = models.FloatField(default=0.0)
    total_follicles = models.IntegerField(default=0)
    hcg_trigger = models.BooleanField(default=False)
    medication = models.CharField(max_length=100, default="LETROZOLE")
    predicted_description = models.CharField(max_length=255)
    confidence = models.FloatField(default=0.0)
    recommended_plan = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.table_source} - Day {self.cycle_day}: {self.predicted_description} ({self.confidence}%)"
