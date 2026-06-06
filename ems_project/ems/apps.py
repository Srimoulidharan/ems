from django.apps import AppConfig


class EmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ems"

    def ready(self):
        # Importing views is avoided here. Demo users are seeded from views.seed_defaults()
        # whenever login or protected pages are opened.
        pass
