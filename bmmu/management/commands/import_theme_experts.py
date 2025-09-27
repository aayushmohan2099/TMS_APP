# bmmu/management/commands/import_theme_experts.py
import os
from django.core.management.base import BaseCommand, CommandError
import pandas as pd
from django.db import transaction
from bmmu.models import TrainingPlan, TrainingPartner, User

class Command(BaseCommand):
    help = "Populate TrainingPlan.theme_expert, theme_expert_contact and training_partner from an Excel file."

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, default='/mnt/data/TrainingTheme details.xlsx', help='Path to Excel file')
        parser.add_argument('--sheet', type=str, default=0, help='Sheet name or index')

    def handle(self, *args, **options):
        path = options['file']
        sheet = options['sheet']
        if not os.path.exists(path):
            raise CommandError(f"File not found: {path}")

        self.stdout.write(f"Reading {path} (sheet={sheet}) ...")
        df = pd.read_excel(path, sheet_name=sheet)

        # expected columns to be present (flexible): Theme, ThemeExpertUsername, ThemeExpertFullName, ThemeExpertContact, TrainingPartnerName
        # adapt to your excel column names - check df.columns and edit below if needed
        cols = [c.strip() for c in df.columns]

        # print columns found
        self.stdout.write("Found columns: " + ", ".join(cols))

        # try common column names variations
        theme_col = next((c for c in cols if c.lower() in ('theme','training theme','trainingtheme')), None)
        expert_user_col = next((c for c in cols if c.lower() in ('themeexpertusername','theme_expert_username','theme_expert','smmu_user','smmu_username')), None)
        expert_name_col = next((c for c in cols if c.lower() in ('themeexpertfullname','theme_expert_fullname','theme_expert_name','smmu_name')), None)
        expert_contact_col = next((c for c in cols if c.lower() in ('themeexpertcontact','theme_expert_contact','contact_no','contact','contactno')), None)
        partner_col = next((c for c in cols if c.lower() in ('trainingpartner','trainng_partner','training_partner_name','training partner','partner','partnername')), None)

        if not theme_col:
            raise CommandError("Could not detect a Theme column in Excel. Columns found: " + ", ".join(cols))

        updated = 0
        errors = []

        with transaction.atomic():
            for idx, row in df.iterrows():
                theme_val = str(row.get(theme_col)).strip() if pd.notna(row.get(theme_col)) else ''
                if not theme_val:
                    continue

                # Find TrainingPlan rows for this theme (case-insensitive)
                q = TrainingPlan.objects.filter(theme__iexact=theme_val)
                if not q.exists():
                    # try contains
                    q = TrainingPlan.objects.filter(theme__icontains=theme_val)

                if not q.exists():
                    errors.append(f"Row {idx+2}: No TrainingPlan found for theme '{theme_val}'")
                    continue

                # Try resolve expert User
                expert_user = None
                if expert_user_col and pd.notna(row.get(expert_user_col)):
                    uname = str(row.get(expert_user_col)).strip()
                    try:
                        expert_user = User.objects.filter(username__iexact=uname).first()
                    except Exception:
                        expert_user = None
                if not expert_user and expert_name_col and pd.notna(row.get(expert_name_col)):
                    full = str(row.get(expert_name_col)).strip()
                    expert_user = User.objects.filter(first_name__icontains=full.split()[0]).first() or None

                # Partner lookup
                partner_obj = None
                if partner_col and pd.notna(row.get(partner_col)):
                    pname = str(row.get(partner_col)).strip()
                    partner_obj = TrainingPartner.objects.filter(name__iexact=pname).first()
                    if not partner_obj:
                        partner_obj = TrainingPartner.objects.filter(name__icontains=pname).first()

                contact_val = None
                if expert_contact_col and pd.notna(row.get(expert_contact_col)):
                    contact_val = str(row.get(expert_contact_col)).strip()

                # Now update matched training plans
                for tp in q:
                    if expert_user:
                        tp.theme_expert = expert_user
                    if contact_val:
                        tp.theme_expert_contact = contact_val
                    if partner_obj:
                        tp.training_partner = partner_obj
                    tp.save()
                    updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} TrainingPlan rows."))
        if errors:
            self.stdout.write(self.style.WARNING("Some rows had issues:"))
            for e in errors[:50]:
                self.stdout.write(self.style.WARNING(e))
