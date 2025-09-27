# bmmu/migrations/XXXX_create_through_and_new_m2m.py
from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):

    dependencies = [
        ('bmmu', '0017_remove_beneficiary_ekyc_registered_on_and_more'),
    ]


    operations = [
        # Create BeneficiaryBatchRegistration (through model)
        migrations.CreateModel(
            name='BeneficiaryBatchRegistration',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('registered_on_start', models.BooleanField(default=False, verbose_name='Registered on start (eKYC)')),
                ('ekyc_registered_on', models.DateTimeField(blank=True, null=True, verbose_name='eKYC registered on')),
                ('certificate_issued', models.BooleanField(default=False, verbose_name='Certificate issued')),
                ('attendance', models.PositiveIntegerField(blank=True, null=True, verbose_name='Attendance (days)')),
                ('remarks', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='beneficiarybatchregistrations', to='bmmu.Batch')),
                ('beneficiary', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='beneficiarybatchregistrations', to='bmmu.Beneficiary')),
            ],
            options={
                'unique_together': {('beneficiary', 'batch')},
                'verbose_name': 'Beneficiary Batch Registration',
                'verbose_name_plural': 'Beneficiary Batch Registrations',
            },
        ),

        # Create TrainerBatchParticipation (through model)
        migrations.CreateModel(
            name='TrainerBatchParticipation',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('participated', models.BooleanField(default=False)),
                ('status', models.CharField(default='DRAFT', max_length=20, choices=[('DRAFT', 'Draft'), ('ONGOING', 'Ongoing'), ('COMPLETED', 'Completed'), ('CANCELLED','Cancelled')])),
                ('remarks', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trainerparticipations', to='bmmu.Batch')),
                ('trainer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trainerparticipations', to='bmmu.MasterTrainer')),
            ],
            options={
                'unique_together': {('trainer', 'batch')},
                'verbose_name': 'Trainer Batch Participation',
                'verbose_name_plural': 'Trainer Batch Participations',
            },
        ),

        # Add new M2M fields on Batch named beneficiaries_v2 and trainers_v2 using through models
        migrations.AddField(
            model_name='batch',
            name='beneficiaries_v2',
            field=models.ManyToManyField(blank=True, through='bmmu.BeneficiaryBatchRegistration', related_name='batches_v2', to='bmmu.Beneficiary'),
        ),
        migrations.AddField(
            model_name='batch',
            name='trainers_v2',
            field=models.ManyToManyField(blank=True, through='bmmu.TrainerBatchParticipation', related_name='batches_v2', to='bmmu.MasterTrainer'),
        ),
    ]
