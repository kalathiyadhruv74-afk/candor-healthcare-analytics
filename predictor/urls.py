from django.urls import path
from . import views

urlpatterns = [
    path("", views.root_redirect, name="root"),
    path("iui/", views.iui_page, name="iui_page"),
    path("ivf/", views.ivf_page, name="ivf_page"),
    path("anc-journey/", views.anc_journey_page, name="anc_journey_page"),
    path("opd-prediction/", views.opd_prediction_page, name="opd_prediction_page"),
    path("opd-report/", views.opd_report_page, name="opd_report_page"),
    path("api/opd-prediction/", views.opd_prediction_api, name="opd_prediction_api"),
    path("api/opd-prediction/sync-live/", views.sync_live_opd_api, name="sync_live_opd_api"),
    path("api/opd-analytics/", views.opd_analytics_api, name="opd_analytics_api"),
    path("api/anc-analytics/", views.anc_analytics_api, name="anc_analytics_api"),
    path("api/anc-patients/", views.anc_patients_filter_api, name="anc_patients_filter_api"),
    path("ivf-booking/", views.ivf_booking_report_page, name="ivf_booking_report_page"),
    path("api/ivf-booking-analytics/", views.ivf_booking_analytics_api, name="ivf_booking_analytics_api"),
    path("pharmacy-report/", views.pharmacy_report_page, name="pharmacy_report_page"),
    path("api/pharmacy-analytics/", views.pharmacy_analytics_api, name="pharmacy_analytics_api"),
    path("collection-report/", views.collection_report_page, name="collection_report_page"),
    path("api/collection-analytics/", views.collection_analytics_api, name="collection_analytics_api"),
    path("api/predict/iui/", views.predict_iui_api, name="predict_iui_api"),
    path("api/predict/ivf/", views.predict_ivf_api, name="predict_ivf_api"),
    path("api/predict/plan/", views.predict_plan_api, name="predict_plan_api"),
    path("api/predict/", views.predict_plan_api, name="predict_plan_api_alias"),
    path("compare/protocols/", views.compare_protocols_api, name="compare_protocols_api"),
    path("api/history/", views.history_api, name="history_api"),
]
