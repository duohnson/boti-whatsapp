import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'boti_project.settings')
app = Celery('boti_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

from celery.schedules import crontab

app.conf.beat_schedule = {
    'limpiar-sesiones-cada-hora': {
        'task': 'core.tasks.limpiar_sesiones_inactivas',
        'schedule': crontab(minute=0, hour='*/1'),
    },
}
