from django.urls import path
from . import views, tms_custom

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
    path('bmmu/trainings-list/', views.bmmu_trainings_list, name='bmmu_trainings_list'),
    path('bmmu/request/<int:request_id>/', views.bmmu_request_detail, name='bmmu_request_detail'),
    path('bmmu/batch/<int:batch_id>/view/', views.bmmu_batch_view, name='bmmu_batch_view'),
    path('bmmu/batch/<int:batch_id>/attendance/<str:date_str>/', views.bmmu_batch_attendance_date, name='bmmu_batch_attendance_date'),
    
    # Add single beneficiary (fragment + POST)
    path("bmmu/add/", views.bmmu_add_beneficiary, name="bmmu_add_beneficiary"),

    # Delete beneficiaries (fragment + POST to delete)
    path("bmmu/delete/", views.bmmu_delete_beneficiaries, name="bmmu_delete_beneficiaries"),

    path('beneficiary/<int:pk>/', views.bmmu_beneficiary_detail, name='bmmu_beneficiary_detail'),
    path('beneficiary/<int:pk>/update/', views.bmmu_beneficiary_update, name='bmmu_beneficiary_update'),

    # Training Program Management Portal (Batch Creator)
    path('tms/create_request/', tms_custom.create_training_request, name='create_training_request'),

    # Training Program Management view (needed by redirects and direct route)
    path("training-program-management/", views.training_program_management, name="training_program_management"),

    # --- Training Partner URLs ---
    path("partner/", views.training_partner_dashboard, name="training_partner_dashboard"),
    path("partner/profile/", views.partner_profile, name="partner_profile"),
    path("partner/propose_dates/", views.partner_propose_dates, name="partner_propose_dates"),
    path('partner/requests/', views.partner_view_requests, name='partner_view_requests'),
    path('partner/request/<int:request_id>/', views.partner_view_request, name='partner_view_request'),
    path('bmmu/partner/create_batches/<int:request_id>/', views.partner_create_batches, name='partner_create_batches'),
    path("partner/batch/<int:batch_id>/upload_attendance/", views.partner_upload_attendance, name="partner_upload_attendance"),
    path("partner/batch/<int:batch_id>/upload_media/", views.partner_upload_media, name="partner_upload_media"),
    path("partner/batch/<int:batch_id>/invoice/", views.partner_generate_invoice, name="partner_generate_invoice"),
    path("partner/centre-registration/", views.training_partner_centre_registration, name="training_partner_centre_registration"),
    path('partner/ongoing-trainings/', views.partner_ongoing_trainings, name='partner_ongoing_trainings'),
    path('partner/batch/<int:batch_id>/attendance/', views.attendance_per_batch, name='attendance_per_batch'),

    # --- Master Trainer URLs ---
    path("master-trainer/", views.master_trainer_dashboard, name="master_trainer_dashboard"),
    path("master-trainer/profile/", views.master_trainer_profile, name="master_trainer_profile"),
    path("master-trainer/education/", views.master_trainer_education, name="master_trainer_education"),
    path("master-trainer/certificate/<int:pk>/delete/", views.master_trainer_certificate_delete, name="master_trainer_certificate_delete"),

    # BMMUs Training Plan Creator
    path('training-plan/create/', views.create_training_plan, name='create_training_plan'),

    # BMMUs Batch Nomination
    path('bmmu/nominate-batch/', views.nominate_batch, name='nominate_batch'),

    # SMMUs dashboard URLs
    path('smmu/dashboard/', views.smmu_dashboard, name='smmu_dashboard'),
    path('smmu/requests/', views.smmu_training_requests, name='smmu_training_requests'),
    path('smmu/request/<int:batch_id>/', views.smmu_request_detail, name='smmu_request_detail'),
    path('api/districts/', views.api_districts_for_mandal, name='api_districts_for_mandal'),
    path('smmu/partner-target/create/', views.smmu_create_partner_target, name='smmu_create_partner_target'),


    # DMMU URLs
    path('dmmu/dashboard/', views.dmmu_dashboard, name='dmmu_dashboard'),
    path('dmmu/requests/', views.dmmu_training_requests, name='dmmu_training_requests'),
    path('dmmu/request/<int:request_id>/', views.dmmu_request_detail, name='dmmu_request_detail'),
    path('dmmu/batch/<int:batch_id>/detail/', views.dmmu_batch_detail_ajax, name='dmmu_batch_detail_ajax'),
    path(
        "dmmu/batch/<int:batch_id>/attendance/<str:date_str>/",
        views.dmmu_batch_attendance_date,
        name="dmmu_batch_attendance_date",
    ),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
