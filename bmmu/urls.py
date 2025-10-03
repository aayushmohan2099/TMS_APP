from django.urls import path
from . import views

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", views.home_view, name="home"),
    path("login/", views.custom_login, name="custom_login"),
    path("logout/", views.custom_logout, name="custom_logout"),
    path('signup/', views.signup, name='signup'),
    
    # Wrapper dashboard (canonical route)
    path("dashboard/", views.dashboard, name="dashboard"),

    # AJAX loader for app fragments
    path("dashboard/load/<str:app_name>/", views.load_app_content, name="load_app_content"),

    # BMMU endpoint for import/export/blueprint - redirects to wrapper for GET
    path("bmmu/dashboard/", views.bmmu_dashboard, name="bmmu_dashboard"),

    # Add single beneficiary (fragment + POST)
    path("bmmu/add/", views.bmmu_add_beneficiary, name="bmmu_add_beneficiary"),

    # Delete beneficiaries (fragment + POST to delete)
    path("bmmu/delete/", views.bmmu_delete_beneficiaries, name="bmmu_delete_beneficiaries"),

    path('beneficiary/<int:pk>/', views.bmmu_beneficiary_detail, name='bmmu_beneficiary_detail'),

    # Training Program Management Portal (Batch Creator)
    path('tms/create_batch/', views.tms_create_batch, name='tms_create_batch'),

    # Training Program Management view (needed by redirects and direct route)
    path("training-program-management/", views.training_program_management, name="training_program_management"),

    # --- Training Partner URLs ---
    path("partner/", views.training_partner_dashboard, name="training_partner_dashboard"),
    path("partner/profile/", views.partner_profile, name="partner_profile"),
    path("partner/propose_dates/", views.partner_propose_dates, name="partner_propose_dates"),
    path("partner/batch/<int:batch_id>/", views.partner_view_batch, name="partner_view_batch"),
    path("partner/batch/<int:batch_id>/upload_attendance/", views.partner_upload_attendance, name="partner_upload_attendance"),
    path("partner/batch/<int:batch_id>/upload_media/", views.partner_upload_media, name="partner_upload_media"),
    path("partner/batch/<int:batch_id>/invoice/", views.partner_generate_invoice, name="partner_generate_invoice"),
    path("partner/centre-registration/", views.training_partner_centre_registration, name="training_partner_centre_registration"),
    path("partner/attendance/", views.training_partner_attendance, name="training_partner_attendance"),
    # --- Master Trainer URLs ---
    path("master-trainer/", views.master_trainer_dashboard, name="master_trainer_dashboard"),
    path("master-trainer/profile/", views.master_trainer_profile, name="master_trainer_profile"),
    path("master-trainer/education/", views.master_trainer_education, name="master_trainer_education"),
    path("master-trainer/certificate/<int:pk>/delete/", views.master_trainer_certificate_delete, name="master_trainer_certificate_delete"),

    # BMMUs Training Plan Creator
    path('training-plan/create/', views.create_training_plan, name='create_training_plan'),

    # BMMUs Batch Nomination
    path('batch/nominate/', views.nominate_batch, name='nominate_batch'),

    # SMMUs dashboard URLs
    path('smmu/dashboard/', views.smmu_dashboard, name='smmu_dashboard'),
    path('smmu/requests/', views.smmu_training_requests, name='smmu_training_requests'),
    path('smmu/request/<int:batch_id>/', views.smmu_request_detail, name='smmu_request_detail'),
    path('api/districts/', views.api_districts_for_mandal, name='api_districts_for_mandal'),

    # DMMU URLs
    path('dmmu/dashboard/', views.dmmu_dashboard, name='dmmu_dashboard'),
    path('dmmu/requests/', views.dmmu_training_requests, name='dmmu_training_requests'),
    path('dmmu/request/<int:batch_id>/', views.dmmu_request_detail, name='dmmu_request_detail'),

]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
